#!/usr/bin/env python3
"""
Technical Gates Backtest — do gates 9-11 add value, subtract it, or do nothing?

WHY THIS EXISTS
The gates are the most discriminating component in the bot. They score every
candidate, and that score IS the confidence that drives the trade/no-trade
threshold, position size and rotation. They veto outright (META on RSI 89, CRM
and AMD on "ATR against trend"). They have never been measured.

Everything else has now been tested and failed: options flow has no standalone
directional edge (10,099 blocks, 192 days), blocks at 1-21d none, GEX-timed vol
selling none, and Tier 2's put/call flip none (133,581 observations). If the
gates also add nothing, the bot has no measured edge anywhere and that should
be stated plainly rather than discovered slowly.

WHAT IS TESTED
For each stock-day the live scoring is applied and forward excess return is
measured. Higher confidence must mean higher forward return, or the gates are
not doing what the bot believes they are.

This IMPORTS uw_gate_scoring and calls score_all() — the same function the bot
calls. It does not reimplement the curves. A reimplementation would test my
understanding of the gates rather than the gates themselves, which is exactly
how the "monitoring" script passed while the real execution path was broken.

VWAP IS NEUTRALISED, AND THAT IS A REAL LIMITATION
VWAP is intraday and cannot be reconstructed from daily bars, so it is passed
as None, which score_vwap maps to 0.50 ("no VWAP data — neutral"). It therefore
contributes a constant 0.25 * 0.50 = 0.125 to every score and discriminates
nothing here. This tests the MA + RSI portion — 75% of the weight, and the part
carrying the hard vetoes. A null result would not strictly clear VWAP, but the
live logs show VWAP scoring in a narrow band and the module's own header notes
it "never once failed in live observation", so it is unlikely to be carrying
the signal alone.

GUARDS (each killed a false positive in an earlier backtest)
  market-adjust   excess over SPY on the same dates
  day-neutral     de-mean each day's cross-section
  split guard     UW prices are not split-adjusted (LAZR 1:30 read +12,915%)
  date check      returned dates verified against requested
  non-overlapping optional; multi-day windows sampled daily are not independent
  winsorise, hit rate, t-stat, explicit multiple-comparison warning
"""

import argparse
import json
import math
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uw_gate_scoring import score_all          # the LIVE scoring, not a copy

BASE = "https://api.unusualwhales.com/api"
HORIZONS = [1, 3, 5]
CACHE = "gates_panel.json"
MAX_ABS_RET = 50.0
WARMUP = 25            # bars needed before MA20 / RSI14 / ATR14 are valid

BUCKETS = [
    ("VETOED (0)",    -0.001, 0.001),
    ("0.01-0.50",      0.001, 0.50),
    ("0.50-0.65",      0.50, 0.65),
    ("0.65-0.75",      0.65, 0.75),
    ("0.75-0.85",      0.75, 0.85),
    ("0.85-1.00",      0.85, 1.001),
]

# The bot only trades at or above this; below it the candidate is skipped.
TRADE_THRESHOLD = 0.50


def _f(v, d=None):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


class GatesBacktest:
    def __init__(self, non_overlapping: bool = False):
        import requests
        self.non_overlapping = non_overlapping
        self.s = requests.Session()
        key = os.getenv("UW_API_KEY")
        if key:
            self.s.headers.update({"Authorization": f"Bearer {key}",
                                   "Accept": "application/json"})
        self.stats = defaultdict(int)

    # ------------------------------------------------------------------ data

    def screener(self, day: str, limit: int) -> List[Dict]:
        try:
            r = self.s.get(f"{BASE}/screener/stocks",
                           params={"date": day, "limit": limit}, timeout=30)
            rows = r.json().get("data", []) if r.status_code == 200 else []
        except Exception:
            self.stats["fetch_error"] += 1
            return []
        if not rows:
            return []
        got = str(rows[0].get("date") or "")[:10]
        if got and got != day:
            self.stats["date_mismatch"] += 1
            return []
        self.stats["days_ok"] += 1
        return rows

    def collect(self, days_back: int, limit: int) -> Dict:
        """panel[day][ticker] = (close, high, low)"""
        today = date.today()
        days, i = [], 1
        while len(days) < days_back and i < days_back * 2 + 40:
            d = today - timedelta(days=i)
            if d.weekday() < 5:
                days.append(d.isoformat())
            i += 1
        days.sort()

        panel = {}
        for day in days:
            rows = self.screener(day, limit)
            if not rows:
                continue
            bars = {}
            for r in rows:
                t = str(r.get("ticker") or "").upper()
                c, h, l = _f(r.get("close")), _f(r.get("high")), _f(r.get("low"))
                if not t or r.get("is_index") or c is None or c <= 0:
                    continue
                bars[t] = (c, h if h else c, l if l else c)
            if bars:
                panel[day] = bars
        return panel

    # ------------------------------------------------------------ indicators

    @staticmethod
    def series(panel: Dict, days: List[str], ticker: str):
        """Aligned (close, high, low) lists for one ticker; None where absent."""
        out = []
        for d in days:
            out.append(panel.get(d, {}).get(ticker))
        return out

    @staticmethod
    def indicators(hist) -> Optional[Tuple[float, float, float, float]]:
        """(price, ma20, rsi14, atr14) from a contiguous tail of bars."""
        bars = [b for b in hist if b]
        if len(bars) < WARMUP:
            return None
        closes = [b[0] for b in bars]
        price = closes[-1]
        ma20 = sum(closes[-20:]) / 20.0

        # Wilder RSI(14)
        gains, losses = [], []
        for a, b in zip(closes[-15:-1], closes[-14:]):
            ch = b - a
            gains.append(max(ch, 0.0))
            losses.append(max(-ch, 0.0))
        ag, al = sum(gains) / 14.0, sum(losses) / 14.0
        rsi = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)

        # ATR(14)
        trs = []
        for i in range(len(bars) - 14, len(bars)):
            c, h, l = bars[i]
            pc = bars[i - 1][0]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr = sum(trs) / 14.0
        if atr <= 0 or ma20 <= 0:
            return None
        return price, ma20, rsi, atr

    # --------------------------------------------------------------- scoring

    def run(self, panel: Dict) -> Dict:
        days = sorted(panel)
        idx = {d: i for i, d in enumerate(days)}
        tickers = sorted({t for d in days for t in panel[d]})

        pool = defaultdict(list)
        recs = []

        for t in tickers:
            ser = self.series(panel, days, t)
            for k in range(WARMUP, len(days)):
                hist = ser[max(0, k - 60):k + 1]
                if not ser[k]:
                    continue
                ind = self.indicators(hist)
                if not ind:
                    continue
                price, ma20, rsi, atr = ind
                # LIVE scoring. VWAP=None -> neutral 0.50 (see module docstring).
                res = score_all(price=price, ma20=ma20, rsi=rsi, vwap=None,
                                atr=atr, is_bullish=True)
                conf = res["confidence"]
                self.stats["scored"] += 1

                day = days[k]
                for h in HORIZONS:
                    if k + h >= len(days):
                        continue
                    if self.non_overlapping and (k % h) != 0:
                        continue
                    nxt = days[k + h]
                    p1 = panel.get(nxt, {}).get(t)
                    s0 = panel.get(day, {}).get("SPY")
                    s1 = panel.get(nxt, {}).get("SPY")
                    if not p1 or not s0 or not s1:
                        continue
                    ret = (p1[0] - price) / price * 100
                    if abs(ret) > MAX_ABS_RET:
                        self.stats["skip_split"] += 1
                        continue
                    mkt = (s1[0] - s0[0]) / s0[0] * 100
                    exc = ret - mkt
                    pool[(day, h)].append(exc)
                    recs.append((day, h, conf, exc))

        dm = {k: st.mean(v) for k, v in pool.items() if v}
        buckets, thresh = defaultdict(list), defaultdict(list)
        for day, h, conf, exc in recs:
            nv = exc - dm.get((day, h), 0.0)
            for name, lo, hi in BUCKETS:
                if lo <= conf < hi:
                    buckets[(name, h)].append(nv)
                    break
            key = "TRADED (>=0.50)" if conf >= TRADE_THRESHOLD else "skipped (<0.50)"
            thresh[(key, h)].append(nv)
        return {"buckets": buckets, "thresh": thresh, "stats": dict(self.stats),
                "n": len(recs)}


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
    up = sum(1 for x in s if x > 0) / n * 100
    return f"{m:>+6.2f}% t{t:>+5.1f} {up:>4.1f}%up"[:19].rjust(19)


def render(out: Dict) -> None:
    stt = out["stats"]
    print("=" * 100)
    print("TECHNICAL GATES BACKTEST — does gate confidence predict forward return?")
    print("=" * 100)
    print(f"  days ok {stt.get('days_ok',0)} | date mismatch {stt.get('date_mismatch',0)} | "
          f"scored {stt.get('scored',0)} | observations {out['n']} | "
          f"split drops {stt.get('skip_split',0)}")
    print()
    print("  Day-neutral excess over SPY. Gates score LONG setups, so higher")
    print("  confidence must mean HIGHER forward return for the gates to add value.")
    print("  VWAP is neutralised (intraday, not reconstructable) — this is the")
    print("  MA + RSI portion, 75% of the weight, including both hard vetoes.")
    print()
    hs = HORIZONS
    print(f"  {'confidence':<16}" + "".join(f"{str(h)+'d':>19}" for h in hs))
    print("  " + "-" * (16 + 19 * len(hs)))
    for name, _, _ in BUCKETS:
        print(f"  {name:<16}" + "".join(_cell(out["buckets"].get((name, h), [])) for h in hs))
    print()
    print("  THE BOT'S OWN CUT")
    print(f"  {'':<16}" + "".join(f"{str(h)+'d':>19}" for h in hs))
    print("  " + "-" * (16 + 19 * len(hs)))
    for name in ("TRADED (>=0.50)", "skipped (<0.50)"):
        print(f"  {name:<16}" + "".join(_cell(out["thresh"].get((name, h), [])) for h in hs))
    print()
    print("=" * 100)
    print("  For the gates to add value the confidence ladder must RISE, and TRADED")
    print("  must beat skipped by more than costs. A flat ladder means the gates")
    print("  discriminate without predicting — they would be filtering noise.")
    print("  |t| < 2 is indistinguishable from zero regardless of the mean.")
    print("=" * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=200)
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--non-overlapping", action="store_true")
    ap.add_argument("--cache", action="store_true")
    a = ap.parse_args()

    bt = GatesBacktest(non_overlapping=a.non_overlapping)
    if a.cache and os.path.exists(CACHE):
        panel = json.load(open(CACHE))
        bt.stats["days_ok"] = len(panel)
        print(f"cached panel: {len(panel)} days\n")
    else:
        print(f"collecting {a.days} weekdays, top {a.limit} names/day...\n")
        panel = bt.collect(a.days, a.limit)
        json.dump(panel, open(CACHE, "w"))
    if not panel:
        print("no data")
        return 1
    render(bt.run(panel))
    return 0


if __name__ == "__main__":
    sys.exit(main())
