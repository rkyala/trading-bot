#!/usr/bin/env python3
"""
Put/Call Flip Backtest — does a bearish premium flip predict underperformance?

WHY THIS EXISTS
Tier 2's dominant exit rule fires when a held name's option flow "flips"
bearish: bearish premium share > 0.55 triggers an exit at 90% confidence. On
2026-09-09 it fired on 6-9 of 9 open positions every single minute. Acting on
it would have flattened the book repeatedly, yet nobody has ever checked
whether the signal predicts anything.

The rule was ALSO broken until commit fbaba02: net_call_premium is signed and
was being clamped at zero, making the ratio exactly 1.0 for any name with net
call selling. Every shadow observation logged before that commit is an artifact
and is not evidence. This backtest is the first real test of the idea.

WHAT IS TESTED
/api/screener/stocks?date= serves a year of daily per-stock option positioning
(net_call_premium, net_put_premium, close, ...) for the 500 most active names.
For each day the bearish share is computed exactly as the live rule computes
it after the sign fix:

    bullish = max(net_call_prem, 0) + max(-net_put_prem, 0)
    bearish = max(-net_call_prem, 0) + max(net_put_prem, 0)
    ratio   = bearish / (bullish + bearish)

then forward returns are measured against the rule's own threshold.

The rule claims a HIGH ratio precedes weakness. So the rule is right only if
high-ratio names show NEGATIVE excess returns. Returns here are NOT signed by
the signal — a negative number in a high-ratio bucket means the rule worked.

HONEST LIMITATION — READ BEFORE ACTING ON THIS
The live rule reads INTRADAY net-prem-ticks and exits within minutes. This
tests the DAILY aggregate at daily horizons, because that is what has history.
They are related but not identical signals. A null here is strong evidence
against the idea in general but does not strictly prove the intraday variant
is worthless; a positive result here would not prove the intraday variant works
either. It is the closest test the available data supports, and it is far
better than the current state, which is no test at all.

GUARDS (each of these killed a false positive in an earlier backtest)
  market-adjust   excess over SPY on the same dates. Raw returns made large
                  option blocks look predictive at +2.74% t+2.9 until this was
                  applied, whereupon the effect vanished — it was beta.
  day-neutral     de-mean each day's cross-section. Names with heavy option
                  activity are high-beta, so in a rising tape they all beat
                  SPY regardless of signal.
  split guard     UW prices are NOT split-adjusted. LAZR's 1:30 reverse split
                  read as +12,915% and alone manufactured a t = -4.2.
  date check      every returned date is verified against the date requested.
  winsorise + hit rate + explicit multiple-comparison warning.
"""

import argparse
import math
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

BASE = "https://api.unusualwhales.com/api"
HORIZONS = [1, 3, 5]

# The live rule's own threshold, so the test asks the same question the bot does.
RULE_THRESHOLD = 0.55

BUCKETS = [
    ("0.0-0.3 bullish", 0.0, 0.30),
    ("0.3-0.45",        0.30, 0.45),
    ("0.45-0.55 mixed", 0.45, 0.55),
    ("0.55-0.7 FLIP",   0.55, 0.70),
    ("0.7-1.0 STRONG",  0.70, 1.0001),
]

MAX_ABS_RET = 50.0      # beyond this is a split/corporate action, not a return


def _f(v, d=None):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


class PCFlipBacktest:
    def __init__(self, non_overlapping: bool = False):
        self.non_overlapping = non_overlapping
        import requests
        self.s = requests.Session()
        key = os.getenv("UW_API_KEY")
        if key:
            self.s.headers.update({"Authorization": f"Bearer {key}",
                                   "Accept": "application/json"})
        self.stats = defaultdict(int)

    # ------------------------------------------------------------------ data

    def screener(self, day: str, limit: int = 500) -> List[Dict]:
        try:
            r = self.s.get(f"{BASE}/screener/stocks",
                           params={"date": day, "limit": limit}, timeout=30)
            rows = r.json().get("data", []) if r.status_code == 200 else []
        except Exception:
            self.stats["fetch_error"] += 1
            return []
        if not rows:
            return []
        # The flow endpoint silently ignored an unsupported `date` param, so
        # every returned date is checked rather than trusted.
        got = str(rows[0].get("date") or "")[:10]
        if got and got != day:
            self.stats["date_mismatch"] += 1
            return []
        self.stats["days_ok"] += 1
        return rows

    @staticmethod
    def bearish_share(row: Dict) -> Optional[float]:
        """Identical computation to the live rule after the sign fix."""
        c = _f(row.get("net_call_premium"))
        p = _f(row.get("net_put_premium"))
        if c is None or p is None:
            return None
        bullish = max(c, 0.0) + max(-p, 0.0)
        bearish = max(-c, 0.0) + max(p, 0.0)
        tot = bullish + bearish
        if tot <= 0:
            return None
        return bearish / tot

    # -------------------------------------------------------------- assembly

    def collect(self, days_back: int, limit: int) -> Tuple[Dict, Dict, Dict]:
        """Returns (closes[day][ticker], signal[day][ticker])."""
        today = date.today()
        days, i = [], 1
        while len(days) < days_back and i < days_back * 2 + 30:
            d = today - timedelta(days=i)
            if d.weekday() < 5:
                days.append(d.isoformat())
            i += 1
        days.sort()

        closes: Dict[str, Dict[str, float]] = {}
        signal: Dict[str, Dict[str, float]] = {}
        mag: Dict[str, Dict[str, float]] = {}
        for day in days:
            rows = self.screener(day, limit)
            if not rows:
                continue
            cl, sg, mg = {}, {}, {}
            for r in rows:
                t = str(r.get("ticker") or "").upper()
                px = _f(r.get("close"))
                if not t or px is None or px <= 0:
                    continue
                if r.get("is_index"):
                    continue          # not tradeable as shares
                cl[t] = px
                s = self.bearish_share(r)
                if s is not None:
                    sg[t] = s
                    c = _f(r.get("net_call_premium"), 0.0) or 0.0
                    pp = _f(r.get("net_put_premium"), 0.0) or 0.0
                    mg[t] = abs(c) + abs(pp)     # total directional premium
            if cl:
                closes[day] = cl
                signal[day] = sg
                mag[day] = mg
        return closes, signal, mag

    # --------------------------------------------------------------- scoring

    def score(self, closes: Dict, signal: Dict) -> Dict:
        days = sorted(closes)
        idx = {d: k for k, d in enumerate(days)}
        raw = defaultdict(list)      # (bucket, h) -> excess returns
        pool = defaultdict(list)     # (day, h)    -> all excess, for de-meaning
        recs = []

        for day in days:
            k = idx[day]
            for h in HORIZONS:
                if k + h >= len(days):
                    continue
                # NON-OVERLAPPING: a 5-day window measured every day overlaps
                # 4/5 with its neighbour, so t-stats computed on the full daily
                # panel are inflated by roughly sqrt(h). Sampling every h-th day
                # makes each window independent. This is the same correction
                # that cut the VRP t-stats from +12.5 to +3.1.
                if self.non_overlapping and (k % h) != 0:
                    continue
                fwd = days[k + h]
                spy0, spy1 = closes[day].get("SPY"), closes[fwd].get("SPY")
                if not spy0 or not spy1:
                    self.stats["no_spy"] += 1
                    continue
                mkt = (spy1 - spy0) / spy0 * 100

                for t, s in signal.get(day, {}).items():
                    p0 = closes[day].get(t)
                    p1 = closes[fwd].get(t)
                    if not p0 or not p1:
                        continue
                    ret = (p1 - p0) / p0 * 100
                    if abs(ret) > MAX_ABS_RET:
                        self.stats["skip_split"] += 1
                        continue
                    exc = ret - mkt
                    pool[(day, h)].append(exc)
                    recs.append((day, h, t, s, exc))
                    self.stats["obs"] += 1

        day_mean = {k: st.mean(v) for k, v in pool.items() if v}
        neutral = defaultdict(list)
        for day, h, t, s, exc in recs:
            nv = exc - day_mean.get((day, h), 0.0)
            for name, lo, hi in BUCKETS:
                if lo <= s < hi:
                    raw[(name, h)].append(exc)
                    neutral[(name, h)].append(nv)
                    break
        # the rule's own binary cut
        rule = defaultdict(list)
        for day, h, t, s, exc in recs:
            key = ("FIRES (>0.55)" if s > RULE_THRESHOLD else "quiet (<=0.55)", h)
            rule[key].append(exc - day_mean.get((day, h), 0.0))

        return {"raw": raw, "neutral": neutral, "rule": rule,
                "stats": dict(self.stats)}


def _cell(v: List[float], min_n: int = 100) -> str:
    if len(v) < min_n:
        return f"{'n=' + str(len(v)):>19}"
    s = sorted(v)
    n = len(s)
    lo, hi = s[n // 100], s[-(n // 100) - 1]
    w = [min(max(x, lo), hi) for x in s]
    m = st.mean(w)
    sd = st.pstdev(w)
    t = m / (sd / math.sqrt(n)) if sd > 0 else 0.0
    neg = sum(1 for x in s if x < 0) / n * 100
    return f"{m:>+6.2f}% t{t:>+5.1f} {neg:>4.1f}%dn"[:19].rjust(19)


def render(out: Dict) -> None:
    st_ = out["stats"]
    print("=" * 100)
    print("PUT/CALL FLIP BACKTEST — does a bearish premium flip precede underperformance?")
    print("=" * 100)
    print(f"  days ok {st_.get('days_ok',0)} | date mismatch {st_.get('date_mismatch',0)} | "
          f"observations {st_.get('obs',0)} | split-guard drops {st_.get('skip_split',0)}")
    print()
    print("  Excess return over SPY, day-neutral. NOT signed by the signal.")
    print("  The rule claims high ratio precedes weakness, so the rule is RIGHT only")
    print("  if high-ratio rows are NEGATIVE. '%dn' is the share of negative returns;")
    print("  50% is a coin flip.")
    print()

    hs = HORIZONS
    for label, key in (("DAY-NEUTRAL EXCESS", "neutral"), ("RAW EXCESS (vs SPY only)", "raw")):
        print(f"  {label}")
        print(f"  {'bucket':<18}" + "".join(f"{str(h)+'d':>19}" for h in hs))
        print("  " + "-" * (18 + 19 * len(hs)))
        for name, _, _ in BUCKETS:
            print(f"  {name:<18}" + "".join(_cell(out[key].get((name, h), [])) for h in hs))
        print()

    print("  THE RULE'S OWN CUT (day-neutral)")
    print(f"  {'':<18}" + "".join(f"{str(h)+'d':>19}" for h in hs))
    print("  " + "-" * (18 + 19 * len(hs)))
    for name in ("FIRES (>0.55)", "quiet (<=0.55)"):
        print(f"  {name:<18}" + "".join(_cell(out["rule"].get((name, h), [])) for h in hs))

    print()
    print("=" * 100)
    print("  HOW TO READ: for the rule to be worth acting on, the FIRES row must be")
    print("  clearly NEGATIVE and separated from the quiet row by more than costs.")
    print("  |t| < 2 is indistinguishable from zero however good the mean looks, and")
    print("  ~30 cells are shown so 1-2 crossing |t|=2 by chance is expected.")
    print("  Daily aggregate is a PROXY for the intraday signal the live rule uses.")
    print("=" * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--non-overlapping", action="store_true")
    ap.add_argument("--cache", action="store_true")
    a = ap.parse_args()
    print(f"lookback {a.days} weekdays, top {a.limit} names/day\n")
    bt = PCFlipBacktest(non_overlapping=a.non_overlapping)
    import json as _j
    CACHE = "pcflip_panel.json"
    if a.cache and os.path.exists(CACHE):
        blob = _j.load(open(CACHE))
        closes, signal, mag = blob["closes"], blob["signal"], blob.get("mag", {})
        bt.stats.update(blob.get("stats", {}))
        print(f"cached panel: {len(closes)} days\n")
    else:
        closes, signal, mag = bt.collect(a.days, a.limit)
        _j.dump({"closes": closes, "signal": signal, "mag": mag,
                 "stats": dict(bt.stats)}, open(CACHE, "w"))
    if not closes:
        print("no data collected")
        return 1
    render(bt.score(closes, signal))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
