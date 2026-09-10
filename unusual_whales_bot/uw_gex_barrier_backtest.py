#!/usr/bin/env python3
"""
Do dealer-gamma walls make better barriers than ATR?

THE QUESTION
Production places barriers at 0.75 ATR (stop) and 1.0 ATR (target). ATR is a
BACKWARD-looking width - it says how much this name has moved lately, not
where it is likely to stall. The classic claim for gamma is that large
dealer-gamma strikes act as support and resistance, because hedging flows
lean against price near them. If that is true, a barrier placed AT a gamma
wall should be touched differently from one placed at an arbitrary ATR
distance.

This is the one input on this project with a surviving result: dealer gamma
predicts move MAGNITUDE (SPY 0.53% at high gamma vs 0.87% at low, t+2.9,
surviving a trailing-vol control). It has already FAILED as a timing signal
(uw_vol_backtest.py: spreads +0.077/+0.080/+0.099/-0.077, all |t|<1), so the
prior here is not favourable. Barriers are a magnitude application, which is
the only place it has ever measured as real.

DATA
  /stock/{t}/greek-exposure/strike?date=D   full strike ladder, call_gex and
      put_gex per strike, ~480 strikes, one request, genuinely historical
      (payload date matches the requested date - verified before building;
      /option-trades?date= does NOT, which is why this is checked not assumed)
  /stock/{t}/ohlc/1d?date=D                 daily bars for path resolution

NO LOOK-AHEAD
greek-exposure/strike?date=D is D's END-OF-DAY snapshot. An entry at D's open
can only use D-1's profile, so the wall map comes from the previous session.
Using D's own profile to place a barrier for D would be reading the answer.

TIE-BREAKING IS PESSIMISTIC AND SYMMETRIC
Daily bars cannot say whether the high or the low came first. When a bar
touches both barriers the trade is scored as a STOP. That is the pessimistic
assumption, and it is applied identically to both barrier sets, so it cannot
favour one over the other.

SPLIT GUARD
UW daily OHLC is NOT split-adjusted (LAZR's 1:30 reverse split once read as a
+12,915% ten-day return). Any bar moving >50% against the previous close is
dropped.

THE BAR, DECLARED BEFORE THE RUN
  1. GEX expectancy > ATR expectancy on the POOLED sample, and
  2. the paired difference reaches |t| >= 2, and
  3. the sign is consistent across the majority of individual tickers.
Pooling correlated tickers inflates t - the vol backtest hit exactly that
trap at a pooled t+4.4 across four ETFs - so (3) is what stops a single
name's noise from carrying the result.
"""

import argparse
import json
import math
import os
import statistics as st
import sys
import time
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

BASE = "https://api.unusualwhales.com/api"

# Production values, from uw_execution_safeguards.
ATR_STOP_MULT = 0.75
ATR_TARGET_MULT = 1.0
ATR_PERIOD = 14
HOLD_DAYS = 3
MIN_WALL_DIST = 0.002      # a wall closer than 0.2% is noise, not a level
MAX_WALL_DIST = 0.10       # beyond 10% it is not a barrier for a 3-day hold


def _f(v, d=None):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


class GexBarrier:
    def __init__(self):
        import requests
        self.s = requests.Session()
        key = os.getenv("UW_API_KEY")
        if key:
            self.s.headers.update({"Authorization": f"Bearer {key}",
                                   "Accept": "application/json"})
        self.stats = {"gex_ok": 0, "gex_empty": 0, "ohlc_ok": 0, "split": 0}

    def _get(self, path: str, params: Dict) -> List[Dict]:
        for attempt in range(3):
            try:
                r = self.s.get(f"{BASE}{path}", params=params, timeout=30)
                if r.status_code == 200:
                    return r.json().get("data") or []
                if r.status_code == 429:
                    time.sleep(2 * (attempt + 1))
                    continue
                return []
            except Exception:
                time.sleep(1)
        return []

    # ------------------------------------------------------------------ data

    def gex_profile(self, ticker: str, day: str) -> List[Dict]:
        rows = self._get(f"/stock/{ticker}/greek-exposure/strike", {"date": day})
        if not rows:
            self.stats["gex_empty"] += 1
            return []
        # Guard the historical claim on every fetch rather than trusting the
        # one-off probe: a payload dated differently than requested is live
        # data wearing a date parameter.
        if str(rows[0].get("date") or "")[:10] != day:
            self.stats["gex_empty"] += 1
            return []
        self.stats["gex_ok"] += 1
        return rows

    def bars(self, ticker: str, day: str, n: int) -> List[Dict]:
        """
        Daily regular-session bars, most recent n.

        Two traps here, both already paid for elsewhere in this repo:

        `?date=D` returns only D's own bars, NOT history ending at D - the
        first version of this function used it and every ticker produced zero
        entries because the session index never overlapped. History comes from
        the bulk fetch with no date parameter.

        Each date appears THREE times, market_time pr/r/po (pre, regular,
        post). Without the filter, "yesterday's close" is whichever of the
        three sorted last, and the ATR is computed over interleaved sessions.
        Only market_time == "r" is the real daily bar.
        """
        rows = self._get(f"/stock/{ticker}/ohlc/1d", {"limit": min(n * 4, 750)})
        out = []
        for r in rows:
            if str(r.get("market_time") or "") != "r":
                continue
            o, h, l, c = (_f(r.get("open")), _f(r.get("high")),
                          _f(r.get("low")), _f(r.get("close")))
            if None in (o, h, l, c) or c <= 0:
                continue
            out.append({"t": str(r.get("date") or "")[:10],
                        "o": o, "h": h, "l": l, "c": c})
        out.sort(key=lambda x: x["t"])
        # SPLIT GUARD - UW daily OHLC is not split-adjusted.
        clean = [out[0]] if out else []
        for i in range(1, len(out)):
            if out[i - 1]["c"] > 0 and abs(out[i]["c"] / out[i - 1]["c"] - 1.0) > 0.50:
                self.stats["split"] += 1
                break
            clean.append(out[i])
        if clean:
            self.stats["ohlc_ok"] += 1
        return clean

    # -------------------------------------------------------------- barriers

    @staticmethod
    def atr(bars: List[Dict], period: int = ATR_PERIOD) -> Optional[float]:
        if len(bars) < period + 1:
            return None
        trs = []
        for i in range(1, len(bars)):
            p = bars[i - 1]["c"]
            trs.append(max(bars[i]["h"] - bars[i]["l"],
                           abs(bars[i]["h"] - p), abs(bars[i]["l"] - p)))
        if len(trs) < period:
            return None
        a = sum(trs[-period:]) / period
        return a if a > 0 else None

    @staticmethod
    def walls(profile: List[Dict], spot: float) -> Tuple[Optional[float], Optional[float]]:
        """
        Nearest dominant gamma strike above and below spot.

        Net gex per strike is call_gex + put_gex (put_gex arrives negative).
        The barrier above is the largest-magnitude strike above spot; below,
        the largest below. "Largest" not "nearest": a wall is a level because
        size sits there, and the nearest strike is usually just the next
        increment on the ladder.
        """
        up, dn = [], []
        for r in profile:
            k = _f(r.get("strike"))
            if k is None or k <= 0:
                continue
            net = abs((_f(r.get("call_gex"), 0.0) or 0.0) + (_f(r.get("put_gex"), 0.0) or 0.0))
            if net <= 0:
                continue
            d = k / spot - 1.0
            if MIN_WALL_DIST < d < MAX_WALL_DIST:
                up.append((net, k))
            elif -MAX_WALL_DIST < d < -MIN_WALL_DIST:
                dn.append((net, k))
        target = max(up)[1] if up else None
        stop = max(dn)[1] if dn else None
        return stop, target

    @staticmethod
    def resolve(path: List[Dict], stop: float, target: float) -> Tuple[str, float]:
        """
        First barrier touched over the holding path. Both touched in one bar
        scores as a stop - pessimistic, and applied to both barrier sets.
        """
        for b in path:
            hit_s, hit_t = b["l"] <= stop, b["h"] >= target
            if hit_s:
                return "stop", stop
            if hit_t:
                return "target", target
        return "timeout", path[-1]["c"] if path else 0.0

    # ------------------------------------------------------------------ run

    def run_ticker(self, ticker: str, days: int) -> List[Dict]:
        today = date.today()
        sessions, i = [], 1
        while len(sessions) < days and i < days * 2 + 40:
            d = today - timedelta(days=i)
            if d.weekday() < 5:
                sessions.append(d.isoformat())
            i += 1
        sessions.sort()

        hist = self.bars(ticker, sessions[-1], days + ATR_PERIOD + 20)
        if len(hist) < ATR_PERIOD + HOLD_DAYS + 5:
            return []
        idx = {b["t"]: n for n, b in enumerate(hist)}

        rows = []
        for day in sessions:
            n = idx.get(day)
            # Need ATR history behind and a full holding path ahead.
            if n is None or n < ATR_PERIOD + 1 or n + HOLD_DAYS >= len(hist):
                continue

            prev_day = hist[n - 1]["t"]          # NO LOOK-AHEAD: D-1 profile
            prof = self.gex_profile(ticker, prev_day)
            if not prof:
                continue

            spot = hist[n]["o"]
            a = self.atr(hist[:n + 1])
            if not a or spot <= 0:
                continue

            path = hist[n + 1:n + 1 + HOLD_DAYS]
            if len(path) < HOLD_DAYS:
                continue

            g_stop, g_target = self.walls(prof, spot)
            if g_stop is None or g_target is None:
                continue

            a_stop = spot - ATR_STOP_MULT * a
            a_target = spot + ATR_TARGET_MULT * a
            if a_stop <= 0:
                continue

            for tag, s, t in (("atr", a_stop, a_target), ("gex", g_stop, g_target)):
                kind, px = self.resolve(path, s, t)
                rows.append({"ticker": ticker, "day": day, "method": tag,
                             "kind": kind, "ret": (px / spot - 1.0) * 100,
                             "stop_d": (s / spot - 1.0) * 100,
                             "tgt_d": (t / spot - 1.0) * 100})
        return rows


def summarise(rows: List[Dict], method: str) -> Dict:
    r = [x for x in rows if x["method"] == method]
    if not r:
        return {}
    rets = [x["ret"] for x in r]
    n = len(rets)
    sd = st.pstdev(rets)
    return {"n": n, "mean": st.mean(rets),
            "t": st.mean(rets) / (sd / math.sqrt(n)) if sd else 0.0,
            "stop%": sum(1 for x in r if x["kind"] == "stop") / n * 100,
            "tgt%": sum(1 for x in r if x["kind"] == "target") / n * 100,
            "to%": sum(1 for x in r if x["kind"] == "timeout") / n * 100,
            "wstop": st.mean([x["stop_d"] for x in r]),
            "wtgt": st.mean([x["tgt_d"] for x in r])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="SPY,QQQ,IWM,AAPL,NVDA,TSLA,META,AMD")
    ap.add_argument("--days", type=int, default=60)
    a = ap.parse_args()

    tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
    bt = GexBarrier()

    print("=" * 94)
    print("GEX WALLS vs ATR AS BARRIERS")
    print("=" * 94)
    print(f"  ATR {ATR_STOP_MULT}/{ATR_TARGET_MULT} (production) | hold {HOLD_DAYS}d | "
          f"walls from PREVIOUS session | ties score as STOP")
    print()

    allrows, per_ticker = [], {}
    for t in tickers:
        r = bt.run_ticker(t, a.days)
        if r:
            allrows += r
            per_ticker[t] = r
        print(f"  {t:<6} {len(r)//2:>4} entries")
    print(f"\n  fetch: {bt.stats}")

    if not allrows:
        print("  no data")
        return 1

    print()
    print(f"  {'method':<8}{'n':>6}{'mean %':>10}{'t':>8}{'stop%':>8}{'target%':>9}"
          f"{'timeout%':>10}{'stop dist':>11}{'tgt dist':>10}")
    print("  " + "-" * 80)
    res = {}
    for m in ("atr", "gex"):
        s = summarise(allrows, m)
        res[m] = s
        if s:
            print(f"  {m:<8}{s['n']:>6}{s['mean']:>+10.3f}{s['t']:>+8.2f}"
                  f"{s['stop%']:>7.1f}%{s['tgt%']:>8.1f}%{s['to%']:>9.1f}%"
                  f"{s['wstop']:>+10.2f}%{s['wtgt']:>+9.2f}%")
    print("  " + "-" * 80)

    # Paired difference, same (ticker, day) under both methods.
    pair = {}
    for x in allrows:
        pair.setdefault((x["ticker"], x["day"]), {})[x["method"]] = x["ret"]
    diffs = [v["gex"] - v["atr"] for v in pair.values() if "gex" in v and "atr" in v]
    print()
    if diffs:
        n = len(diffs)
        sd = st.pstdev(diffs)
        tt = st.mean(diffs) / (sd / math.sqrt(n)) if sd else 0.0
        print(f"  PAIRED (gex - atr): n={n}  mean {st.mean(diffs):+.3f}%  t {tt:+.2f}")
    else:
        tt, n = 0.0, 0

    # Per-ticker sign consistency.
    print()
    print(f"  {'ticker':<8}{'atr mean':>11}{'gex mean':>11}{'diff':>10}")
    print("  " + "-" * 40)
    wins = 0
    for t, r in per_ticker.items():
        sa, sg = summarise(r, "atr"), summarise(r, "gex")
        if not sa or not sg:
            continue
        d = sg["mean"] - sa["mean"]
        wins += 1 if d > 0 else 0
        print(f"  {t:<8}{sa['mean']:>+11.3f}{sg['mean']:>+11.3f}{d:>+10.3f}")
    print("  " + "-" * 40)

    print()
    print("  BAR DECLARED BEFORE THE RUN:")
    ok1 = bool(res.get("gex") and res.get("atr") and res["gex"]["mean"] > res["atr"]["mean"])
    ok2 = abs(tt) >= 2.0 and st.mean(diffs) > 0 if diffs else False
    ok3 = wins > len(per_ticker) / 2
    print(f"    (1) GEX beats ATR pooled:        {'PASS' if ok1 else 'FAIL'}")
    print(f"    (2) paired |t| >= 2 and positive:{'PASS' if ok2 else 'FAIL'}  (t={tt:+.2f})")
    print(f"    (3) majority of tickers positive:{'PASS' if ok3 else 'FAIL'}  ({wins}/{len(per_ticker)})")
    print()
    print(f"  VERDICT: {'PASSES - worth wiring' if (ok1 and ok2 and ok3) else 'FAILS - keep ATR barriers'}")
    print("=" * 94)
    return 0


if __name__ == "__main__":
    sys.exit(main())
