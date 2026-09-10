#!/usr/bin/env python3
"""
Does the market's implied move place better barriers than ATR?

THE MOTIVATION
Production sizes barriers with ATR - a BACKWARD-looking width. The one thing
on this project that has ever beaten a competitor in a controlled test is
IMPLIED volatility: in uw_vol_forecast.py, given the most favourable possible
target (|move|) and relevant features, a ridge model beat trailing RV
(test rho 0.512 vs 0.466) and still LOST to implied (0.522). Implied vol was
the best magnitude estimate found anywhere in this work, and it has never
been used for the one job that is purely a magnitude question: barrier width.

    /stock/{t}/interpolated-iv?date=D   IV interpolated to FIXED day horizons,
        so implied_move_perc at days=HOLD is the market's expected move over
        exactly the holding period. Historical (verified, re-checked per fetch).

WHY NOT WIDTH-MATCH (the obvious control, and why it is wrong here)
The GEX barrier test failed partly on a width confound: its barriers were 14%
wider, so they were stopped less by arithmetic rather than by better levels.
The instinct is to width-match this test. That would make it VACUOUS - if both
methods place barriers at the same total width in the same 0.75:1.0 ratio,
they are the identical barrier. The hypothesis here IS a width claim.

So the metric is width-INVARIANT instead:

    for barriers at -s% and +t%, a driftless random walk resolves to the
    target first with probability s/(s+t)

    edge = P(target first | resolved) - mean(s/(s+t))

edge is zero for ANY width if price is a driftless random walk, so it cannot
be inflated by simply widening the stop. A method with a real edge places
barriers where the walk is not driftless - where price actually stalls or
runs. Comparing edge_iv against edge_atr is then a fair fight between two
placements regardless of their sizes.

Mean return is reported too, but only as description - it is width-sensitive
and is NOT the criterion.

NO LOOK-AHEAD
interpolated-iv?date=D is D's end-of-day curve, so an entry at D's open uses
D-1. Same rule as the gamma test.

TIE-BREAKING
Daily bars cannot order the high and the low. A bar touching both scores as a
STOP - pessimistic, applied identically to both methods.

THE BAR, DECLARED BEFORE THE RUN
  1. edge_iv > edge_atr on the pooled sample, and
  2. the paired per-trade difference reaches |t| >= 2, and
  3. the sign holds on a majority of individual tickers.
(3) is what killed the gamma test: it passed pooled, but AMD alone was 70% of
the effect and dropping three names turned it negative. Pooling correlated
names inflates t.
"""

import argparse
import math
import os
import statistics as st
import sys
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uw_gex_barrier_backtest import GexBarrier, _f, ATR_PERIOD

BASE = "https://api.unusualwhales.com/api"

ATR_STOP_MULT = 0.75      # production
ATR_TARGET_MULT = 1.0     # production
HOLD_DAYS = 3
# Implied move is a ~1 sigma number. Applied at the same 0.75:1.0 asymmetry as
# production so the SHAPE is held constant and only the SIZING SOURCE differs.
IV_STOP_MULT = 0.75
IV_TARGET_MULT = 1.0


class IvBarrier(GexBarrier):
    def implied_move(self, ticker: str, day: str, horizon: int) -> Optional[float]:
        """
        Implied move fraction over `horizon` calendar-ish days, from the
        previous session's curve. Picks the nearest available `days` node and
        scales by sqrt(time) if it is not an exact match.
        """
        rows = self._get(f"/stock/{ticker}/interpolated-iv", {"date": day})
        if not rows:
            self.stats["gex_empty"] += 1
            return None
        if str(rows[0].get("date") or "")[:10] != day:
            self.stats["gex_empty"] += 1
            return None
        best, bestd = None, None
        for r in rows:
            d = _f(r.get("days"))
            im = _f(r.get("implied_move_perc"))
            if d is None or im is None or d <= 0 or im <= 0:
                continue
            gap = abs(d - horizon)
            if bestd is None or gap < bestd:
                best, bestd = (d, im), gap
        if not best:
            self.stats["gex_empty"] += 1
            return None
        d, im = best
        self.stats["gex_ok"] += 1
        # sqrt-time rescale when the node is not exactly the holding horizon
        return im * math.sqrt(horizon / d) if d != horizon else im

    def run_ticker(self, ticker: str, days: int) -> List[Dict]:
        today = date.today()
        sessions, i = [], 1
        while len(sessions) < days and i < days * 2 + 40:
            d = today - timedelta(days=i)
            if d.weekday() < 5:
                sessions.append(d.isoformat())
            i += 1
        sessions.sort()

        hist = self.bars(ticker, sessions[-1], days + ATR_PERIOD + 30)
        if len(hist) < ATR_PERIOD + HOLD_DAYS + 5:
            return []
        idx = {b["t"]: n for n, b in enumerate(hist)}

        rows = []
        for day in sessions:
            n = idx.get(day)
            if n is None or n < ATR_PERIOD + 1 or n + HOLD_DAYS >= len(hist):
                continue
            prev_day = hist[n - 1]["t"]                 # NO LOOK-AHEAD
            im = self.implied_move(ticker, prev_day, HOLD_DAYS)
            if not im:
                continue
            spot = hist[n]["o"]
            a = self.atr(hist[:n + 1])
            if not a or spot <= 0:
                continue
            path = hist[n + 1:n + 1 + HOLD_DAYS]
            if len(path) < HOLD_DAYS:
                continue

            sets = {
                "atr": (spot - ATR_STOP_MULT * a, spot + ATR_TARGET_MULT * a),
                "iv":  (spot * (1 - IV_STOP_MULT * im), spot * (1 + IV_TARGET_MULT * im)),
            }
            for tag, (s, t) in sets.items():
                if s <= 0 or t <= spot:
                    continue
                kind, px = self.resolve(path, s, t)
                sd = (spot - s) / spot * 100          # positive magnitude
                td = (t - spot) / spot * 100
                rows.append({"ticker": ticker, "day": day, "method": tag,
                             "kind": kind, "ret": (px / spot - 1.0) * 100,
                             "s": sd, "t": td,
                             "baseline": sd / (sd + td) if (sd + td) > 0 else 0.5})
        return rows


def edge_stats(rows: List[Dict], method: str) -> Dict:
    r = [x for x in rows if x["method"] == method]
    if not r:
        return {}
    res = [x for x in r if x["kind"] in ("stop", "target")]
    if not res:
        return {}
    hits = [1.0 if x["kind"] == "target" else 0.0 for x in res]
    base = [x["baseline"] for x in res]
    diff = [h - b for h, b in zip(hits, base)]
    n = len(diff)
    sd = st.pstdev(diff)
    rets = [x["ret"] for x in r]
    return {"n": len(r), "nres": n,
            "edge": st.mean(diff) * 100,
            "t": st.mean(diff) / (sd / math.sqrt(n)) if sd else 0.0,
            "phit": st.mean(hits) * 100, "pbase": st.mean(base) * 100,
            "width": st.mean([x["s"] + x["t"] for x in r]),
            "mean": st.mean(rets), "to%": sum(1 for x in r if x["kind"] == "timeout") / len(r) * 100}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="SPY,QQQ,IWM,AAPL,NVDA,TSLA,META,AMD,MSFT,AMZN")
    ap.add_argument("--days", type=int, default=90)
    a = ap.parse_args()

    tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
    bt = IvBarrier()

    print("=" * 96)
    print("IMPLIED MOVE vs ATR AS BARRIERS  (width-invariant metric)")
    print("=" * 96)
    print(f"  hold {HOLD_DAYS}d | ATR {ATR_STOP_MULT}/{ATR_TARGET_MULT} | "
          f"IV {IV_STOP_MULT}/{IV_TARGET_MULT} x implied move | IV from PREVIOUS session")
    print("  edge = P(target first | resolved) - s/(s+t)   [0 for a driftless walk at ANY width]")
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
    print(f"  {'method':<8}{'n':>6}{'edge pp':>10}{'t':>8}{'P(tgt)':>9}{'baseline':>10}"
          f"{'width':>8}{'timeout%':>10}{'mean %':>9}")
    print("  " + "-" * 78)
    res = {}
    for m in ("atr", "iv"):
        s = edge_stats(allrows, m)
        res[m] = s
        if s:
            print(f"  {m:<8}{s['n']:>6}{s['edge']:>+10.2f}{s['t']:>+8.2f}"
                  f"{s['phit']:>8.1f}%{s['pbase']:>9.1f}%{s['width']:>7.2f}%"
                  f"{s['to%']:>9.1f}%{s['mean']:>+9.3f}")
    print("  " + "-" * 78)
    print("  edge > 0 means the barrier resolved to target MORE often than its")
    print("  own width implies - i.e. the placement, not the size, did work.")

    # Paired per-trade difference on the same (ticker, day).
    pair = {}
    for x in allrows:
        if x["kind"] in ("stop", "target"):
            pair.setdefault((x["ticker"], x["day"]), {})[x["method"]] = \
                (1.0 if x["kind"] == "target" else 0.0) - x["baseline"]
    diffs = [v["iv"] - v["atr"] for v in pair.values() if "iv" in v and "atr" in v]
    tt = 0.0
    print()
    if diffs:
        n = len(diffs)
        sd = st.pstdev(diffs)
        tt = st.mean(diffs) / (sd / math.sqrt(n)) if sd else 0.0
        print(f"  PAIRED (iv - atr) edge: n={n}  mean {st.mean(diffs)*100:+.2f}pp  t {tt:+.2f}")

    print()
    print(f"  {'ticker':<8}{'atr edge':>11}{'iv edge':>10}{'diff':>9}{'n':>6}")
    print("  " + "-" * 44)
    wins, tot = 0, 0
    for t, r in per_ticker.items():
        sa, si = edge_stats(r, "atr"), edge_stats(r, "iv")
        if not sa or not si:
            continue
        tot += 1
        d = si["edge"] - sa["edge"]
        wins += 1 if d > 0 else 0
        print(f"  {t:<8}{sa['edge']:>+11.2f}{si['edge']:>+10.2f}{d:>+9.2f}{sa['nres']:>6}")
    print("  " + "-" * 44)

    ok1 = bool(res.get("iv") and res.get("atr") and res["iv"]["edge"] > res["atr"]["edge"])
    ok2 = bool(diffs) and abs(tt) >= 2.0 and st.mean(diffs) > 0
    ok3 = tot > 0 and wins > tot / 2
    print()
    print("  BAR DECLARED BEFORE THE RUN:")
    print(f"    (1) IV edge beats ATR edge pooled:  {'PASS' if ok1 else 'FAIL'}")
    print(f"    (2) paired |t| >= 2 and positive:   {'PASS' if ok2 else 'FAIL'}  (t={tt:+.2f})")
    print(f"    (3) majority of tickers positive:   {'PASS' if ok3 else 'FAIL'}  ({wins}/{tot})")
    print()
    print(f"  VERDICT: {'PASSES - worth wiring' if (ok1 and ok2 and ok3) else 'FAILS - keep ATR barriers'}")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    sys.exit(main())
