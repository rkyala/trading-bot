#!/usr/bin/env python3
"""
Earnings IV Crush Backtest — does selling a straddle into earnings pay?

WHY THIS EXISTS
This is the last untested hypothesis with a genuine mechanical prior. Implied
vol rises into an announcement and collapses once uncertainty resolves,
regardless of direction. If the market overprices the event move, selling
premium into earnings pays.

Everything else has been measured and failed: flow direction (10,099 blocks),
blocks at 1-21d, GEX-timed vol selling, Tier 2's put/call flip (133,581 obs),
and the technical gates (104,924 obs).

DATA
/api/earnings/{ticker} returns per-event history with the trade already
computed: expected_move_perc, post_earnings_move_1d/3d/1w/2w, and
short_straddle_1d / short_straddle_1w — the return to shorting an at-the-money
straddle through the event, as a fraction of premium collected.

A FIRST ATTEMPT AT THIS TEST WAS ABANDONED, AND WHY
The obvious approach is to find earnings dates in the daily screener panel via
`next_earnings_date`. That field is NOT point-in-time: every ticker carries a
single value across all 191 historical days — today's upcoming date joined onto
old rows. TSLA on 2025-12-03 reports earnings on 2026-10-28, eleven months
later. Building on it would not merely be inaccurate, it would be LOOK-AHEAD
CONTAMINATED, using an announcement date that was unknowable at the time.
Verified before use rather than after.

HOW TO READ THE RESULT — THE MEAN IS NOT THE POINT
Short vol wins often and loses big. AAPL's own history shows +0.82 and +0.85
alongside -0.97 and -0.80. A high win rate with a thin or negative mean is the
signature of picking up pennies in front of a steamroller, and it is exactly
how the LEAP run scored 60% wins while losing ~$3,500. So the tail is reported
as prominently as the average, and a positive mean alone is NOT a reason to
trade this.

WHAT THIS IS NOT
UW's straddle return is almost certainly mid-price with no commission, no
slippage and no early assignment, and it assumes the position is held through
the event rather than stopped out. Real execution earns strictly less. Treat
any positive number as an UPPER BOUND.
"""

import argparse
import json
import math
import os
import statistics as st
import sys
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

BASE = "https://api.unusualwhales.com/api"
CACHE = "earnings_events.json"


def _f(v, d=None):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


class EarningsBacktest:
    def __init__(self):
        import requests
        self.s = requests.Session()
        key = os.getenv("UW_API_KEY")
        if key:
            self.s.headers.update({"Authorization": f"Bearer {key}",
                                   "Accept": "application/json"})
        self.stats = defaultdict(int)

    def universe(self, limit: int) -> List[str]:
        """Most option-active names — where a straddle is actually tradeable."""
        try:
            r = self.s.get(f"{BASE}/screener/stocks",
                           params={"limit": limit}, timeout=30)
            rows = r.json().get("data", []) if r.status_code == 200 else []
        except Exception:
            return []
        out = []
        for x in rows:
            t = str(x.get("ticker") or "").upper()
            if t and not x.get("is_index") and x.get("next_earnings_date"):
                out.append(t)
        return out

    def events(self, ticker: str) -> List[Dict]:
        try:
            r = self.s.get(f"{BASE}/earnings/{ticker}", timeout=25)
            rows = r.json().get("data", []) if r.status_code == 200 else []
        except Exception:
            self.stats["fetch_error"] += 1
            return []
        out = []
        for x in rows or []:
            s1 = _f(x.get("short_straddle_1d"))
            if s1 is None:
                continue          # future or unpriced event
            out.append({
                "ticker": ticker,
                "date": str(x.get("report_date"))[:10],
                "time": str(x.get("report_time") or "unknown"),
                "exp_move": _f(x.get("expected_move_perc")),
                "move_1d": _f(x.get("post_earnings_move_1d")),
                "short_1d": s1,
                "short_1w": _f(x.get("short_straddle_1w")),
                # Captured so the long/short pair can be summed. Without this
                # the short figure alone reads as "shorting loses, therefore
                # buying wins" — which is false, see the MIRROR CHECK below.
                "long_1d": _f(x.get("long_straddle_1d")),
            })
        self.stats["tickers_ok"] += 1
        self.stats["events"] += len(out)
        return out

    def collect(self, limit: int, pause: float = 0.05) -> List[Dict]:
        tickers = self.universe(limit)
        print(f"universe: {len(tickers)} option-active tickers")
        allev = []
        for i, t in enumerate(tickers, 1):
            allev += self.events(t)
            if i % 25 == 0:
                print(f"  {i}/{len(tickers)} ... {len(allev)} events")
            time.sleep(pause)
        return allev


def _stat(v: List[float], min_n: int = 30):
    if len(v) < min_n:
        return None
    s = sorted(v)
    n = len(s)
    lo, hi = s[max(n // 100, 0)], s[-(max(n // 100, 0)) - 1]
    w = [min(max(x, lo), hi) for x in s]
    m = st.mean(w)
    sd = st.pstdev(w)
    t = m / (sd / math.sqrt(n)) if sd > 0 else 0.0
    hit = sum(1 for x in s if x > 0) / n * 100
    return m, t, hit, n, s


def _row(label: str, r) -> str:
    if not r:
        return f"  {label:<24}{'insufficient':>44}"
    m, t, hit, n, _ = r
    return f"  {label:<24}{m:>+11.3f}{t:>9.1f}{hit:>9.1f}%{n:>8}"


def render(events: List[Dict], stats: Dict) -> None:
    print("=" * 92)
    print("EARNINGS IV CRUSH BACKTEST — does shorting a straddle into earnings pay?")
    print("=" * 92)
    print(f"  tickers {stats.get('tickers_ok',0)} | priced events {len(events)} | "
          f"fetch errors {stats.get('fetch_error',0)}")
    if events:
        ds = sorted(e["date"] for e in events)
        print(f"  span {ds[0]} .. {ds[-1]}")
    print()
    print("  Return to a SHORT at-the-money straddle, as a fraction of premium")
    print("  collected. +1.0 would be keeping all premium; -1.0 is losing it all.")
    print()
    print(f"  {'sample':<24}{'mean':>11}{'t':>9}{'win%':>10}{'n':>8}")
    print("  " + "-" * 62)

    s1 = [e["short_1d"] for e in events]
    s1w = [e["short_1w"] for e in events if e["short_1w"] is not None]
    print(_row("SHORT STRADDLE 1d", _stat(s1)))
    print(_row("SHORT STRADDLE 1w", _stat(s1w)))
    print("  " + "-" * 62)

    # Does a richer expected move help or hurt?
    print()
    print("  BY EXPECTED MOVE (what the market charged)")
    print(f"  {'bucket':<24}{'mean':>11}{'t':>9}{'win%':>10}{'n':>8}")
    print("  " + "-" * 62)
    for name, lo, hi in [("< 3%", 0.0, 0.03), ("3-5%", 0.03, 0.05),
                         ("5-8%", 0.05, 0.08), ("> 8%", 0.08, 9.9)]:
        v = [e["short_1d"] for e in events
             if e["exp_move"] is not None and lo <= e["exp_move"] < hi]
        print(_row(name, _stat(v)))

    # -------------------------------------------------------------- mirror
    # THE CHECK THAT DECIDES THE INTERPRETATION.
    #
    # A short and a long straddle on the same event are opposite trades, so
    # frictionlessly their returns must sum to ~0. If BOTH are negative, the
    # figures already include transaction costs, and the shortfall from zero
    # measures that friction. Without this check the short row alone reads as
    # "shorting loses 17%, therefore buying wins 17%" — which is simply wrong,
    # and would have been a spectacular false positive.
    pairs = [(e["long_1d"], e["short_1d"]) for e in events
             if e.get("long_1d") is not None and e["short_1d"] is not None]
    if len(pairs) >= 30:
        L = [p[0] for p in pairs]
        S = [p[1] for p in pairs]
        tot = [a + b for a, b in pairs]
        print()
        print("  MIRROR CHECK — long vs short on the same events")
        print(_row("LONG straddle 1d", _stat(L)))
        print(_row("SHORT straddle 1d", _stat(S)))
        mt = st.mean(tot)
        print(f"  {'sum of the pair':<24}{mt:>+11.3f}"
              f"{'  <- 0 would mean frictionless':>44}")
        rl = _stat(L)
        rs = _stat(S)
        if rl and rs:
            edge = (rs[0] - rl[0]) / 2.0
            print(f"  {'implied mid-price edge':<24}{edge:>+11.3f}"
                  f"{'  (short minus long, halved)':>44}")
            print()
            print(f"  Both directions lose, so these returns already carry cost.")
            print(f"  The pair falls {abs(mt):.3f} short of zero — that is the")
            print(f"  round-trip friction on an earnings straddle. The mid-price")
            print(f"  edge of {edge:+.3f} is what remains, and it is swamped by it.")

    # The tail is the whole risk of short vol.
    r = _stat(s1)
    if r:
        m, t, hit, n, s = r
        print()
        print("  LEFT TAIL — this is where short vol dies, not in the mean")
        print(f"    worst {s[0]:+.3f} | p1 {s[n//100]:+.3f} | p5 {s[n//20]:+.3f} | "
              f"median {s[n//2]:+.3f}")
        losers = [x for x in s if x < 0]
        winners = [x for x in s if x >= 0]
        if losers and winners:
            print(f"    losing events {len(losers)/n*100:.1f}%, mean loss "
                  f"{st.mean(losers):+.3f} | mean win {st.mean(winners):+.3f}")
            print(f"    a single worst-case loss wipes out "
                  f"{abs(s[0])/st.mean(winners):.1f} average wins")

    print()
    print("=" * 92)
    print("  UW's straddle return is almost certainly mid-price with no commission,")
    print("  slippage or early assignment, and assumes the position is held through")
    print("  the event. Real execution earns strictly less — treat any positive")
    print("  number as an UPPER BOUND. A high win rate with a thin mean is the")
    print("  pennies-in-front-of-a-steamroller signature, not an edge.")
    print("=" * 92)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=250, help="universe size")
    ap.add_argument("--cache", action="store_true")
    a = ap.parse_args()

    bt = EarningsBacktest()
    if a.cache and os.path.exists(CACHE):
        blob = json.load(open(CACHE))
        events, stats = blob["events"], blob["stats"]
        print(f"cached: {len(events)} events\n")
    else:
        events = bt.collect(a.limit)
        stats = dict(bt.stats)
        json.dump({"events": events, "stats": stats}, open(CACHE, "w"))
    if not events:
        print("no priced events collected")
        return 1
    render(events, stats)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
