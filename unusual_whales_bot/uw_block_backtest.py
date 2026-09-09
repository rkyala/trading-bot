#!/usr/bin/env python3
"""
Whale-Block Backtest — do large opening option positions predict the underlying
over DAYS and WEEKS?

WHY THIS EXISTS
The aggregate-flow backtest (uw_flow_backtest.py) found no intraday edge: the
strongest ask-side signals slightly UNDERPERFORMED baseline at 30/60/120
minutes. Two hypotheses survived that result:

    1. edge lives in individual large BLOCKS, not aggregate flow
    2. edge lives at LONGER horizons than we hold

This tests both at once.

FINDING BLOCKS IN HISTORY
The raw /option-trades feed silently ignores `date`, so individual alerts have
no history. But a block that genuinely opens a position leaves a fingerprint:
open interest jumps the next morning. /market/oi-change?date= IS historical
(verified 3, 10 and 30 days back) and carries everything needed:

    curr_oi, oi_diff_plain        the size of the position that opened
    prev_ask_volume / bid_volume  who initiated — bought or sold
    prev_multi_leg_volume         whether it was a spread
    prev_total_premium            conviction in dollars

So the OI print reconstructs the block without needing the alert feed.

WHAT IS EXCLUDED, AND WHY
  multi-leg   PCG on 2026-08-28 showed volume 247,197 of which 245,031 was
              multi-leg and 245,000 neutral — a spread, not a directional bet.
              The largest OI changes are frequently spreads, so including them
              would measure something other than whale conviction.
  sold blocks a call SOLD is bearish, a put SOLD is bullish; direction comes
              from ask vs bid volume, never from call/put alone.
  small       below a premium floor it is not a whale.

ENTRY TIMING (no look-ahead)
A row carries last_date (when the block traded) and curr_date (when the
resulting OI was published). The block is only KNOWABLE on curr_date, so entry
is taken at the curr_date close and returns are measured from there. This gives
up the block-day move entirely — deliberately, because that move is not
capturable by anyone reading OI.

GUARDS
  Dates returned are verified against dates requested (the flow endpoint's
  silent-ignore behaviour would otherwise measure one day repeated N times).
  Forward returns use daily bars strictly after the OI date, and every result
  is reported against the unconditional return over the same windows.
"""

import argparse
import os
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

HORIZON_DAYS = [1, 3, 5, 10, 21]     # ~1d, 3d, 1w, 2w, 1m of trading

CONVICTION_BUCKETS = [
    ("$250k-1M",   250_000,   1_000_000),
    ("$1M-5M",   1_000_000,   5_000_000),
    ("$5M-20M",  5_000_000,  20_000_000),
    (">$20M",   20_000_000, 10**12),
]


def _f(v, d=0.0) -> float:
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


class BlockBacktest:
    def __init__(self, verbose: bool = False):
        import requests
        self.s = requests.Session()
        key = os.getenv("UW_API_KEY")
        if key:
            self.s.headers.update({"Authorization": f"Bearer {key}",
                                   "Accept": "application/json"})
        self.base = "https://api.unusualwhales.com/api"
        self.verbose = verbose
        self._bars: Dict[str, List[Dict]] = {}
        self.stats = defaultdict(int)

    # ------------------------------------------------------------------ data

    # The endpoint caps out at 200 (500 returns 422). Rows come back ranked by
    # size of OI change, so the top 200 IS the whale universe for that day.
    def oi_changes(self, day: str, limit: int = 200) -> List[Dict]:
        self.stats["days_requested"] += 1
        try:
            r = self.s.get(f"{self.base}/market/oi-change",
                           params={"date": day, "limit": limit}, timeout=20)
            rows = r.json().get("data", []) if r.status_code == 200 else []
        except Exception:
            return []
        if not rows:
            return []
        got = str(rows[0].get("curr_date"))[:10]
        if got != day:
            self.stats["date_mismatch"] += 1
            return []
        self.stats["days_ok"] += 1
        return rows

    def daily_bars(self, ticker: str) -> List[Dict]:
        if ticker in self._bars:
            return self._bars[ticker]
        try:
            r = self.s.get(f"{self.base}/stock/{ticker}/ohlc/1d",
                           params={"limit": 800}, timeout=20)
            rows = r.json().get("data", []) if r.status_code == 200 else []
        except Exception:
            rows = []
        out = []
        for b in rows or []:
            if b.get("market_time") not in (None, "r"):
                continue
            try:
                out.append({"d": str(b.get("date") or b.get("start_time"))[:10],
                            "c": float(b["close"])})
            except (KeyError, TypeError, ValueError):
                continue
        out.sort(key=lambda x: x["d"])
        # ---------------------------------------------------------------
        # SPLIT GUARD. UW's daily OHLC is NOT split-adjusted. LAZR's 1:30
        # reverse split showed up as a +12,915% ten-day "return" and single-
        # handedly took the 10d standard deviation from 10.5 to 132, which
        # manufactured a t = -4.2 in the day-neutral table out of nothing.
        # Flag any bar-to-bar move beyond +-50%; windows spanning one are
        # unusable. This also drops a handful of genuine biotech gaps, which
        # is the right trade: those are unhedgeable binary events, not
        # something the bot could size into.
        # ---------------------------------------------------------------
        for i in range(1, len(out)):
            p, c = out[i - 1]["c"], out[i]["c"]
            out[i]["jump"] = bool(p > 0 and abs(c / p - 1.0) > 0.50)
        if out:
            out[0]["jump"] = False
        self._bars[ticker] = out
        return out

    @staticmethod
    def _spans_split(bars: List[Dict], i0: int, i1: int) -> bool:
        return any(b.get("jump") for b in bars[i0 + 1:i1 + 1])

    # -------------------------------------------------------------- blocking

    def classify(self, row: Dict, min_premium: float,
                 min_oi_gain: int) -> Optional[Tuple[str, float, str]]:
        """
        Is this OI print a directional whale block?

        Returns (direction, premium, symbol) or None.
        """
        oi_gain = _f(row.get("oi_diff_plain"))
        if oi_gain < min_oi_gain:
            return None

        prem = _f(row.get("prev_total_premium"))
        if prem < min_premium:
            self.stats["skip_small"] += 1
            return None

        vol = _f(row.get("volume"))
        multi = _f(row.get("prev_multi_leg_volume"))
        neutral = _f(row.get("prev_neutral_volume"))
        # Spreads and neutral prints are not directional conviction.
        if vol > 0 and (multi + neutral) / vol > 0.30:
            self.stats["skip_multileg"] += 1
            return None

        ask = _f(row.get("prev_ask_volume"))
        bid = _f(row.get("prev_bid_volume"))
        if ask + bid <= 0:
            return None
        # Require a clear aggressor; balanced prints carry no directional read.
        if ask / (ask + bid) < 0.60 and bid / (ask + bid) < 0.60:
            self.stats["skip_unsided"] += 1
            return None

        bought = ask > bid
        sym = str(row.get("option_symbol") or "")
        underlying = str(row.get("underlying_symbol") or "")
        # OCC symbol: UNDERLYING + YYMMDD + C|P + 8-digit strike, so the
        # right-hand 9 characters are always C/P plus the strike. Anchoring on
        # the right avoids depending on the underlying's length.
        if not underlying or len(sym) < 15:
            return None
        cp = sym[-9]
        if cp not in ("C", "P"):
            self.stats["skip_badsym"] += 1
            return None
        is_call = cp == "C"
        # a bought call or a sold put is bullish; the inverse is bearish
        direction = "bullish" if (is_call == bought) else "bearish"
        return direction, prem, underlying

    # -------------------------------------------------------------- backtest

    def spy_return(self, day: str, horizon: int) -> Optional[float]:
        """
        SPY's return over the SAME window, for market adjustment.

        Without this the tables measure beta, not information: in the 40-day
        sample the market rose ~5%, which made every bullish block look
        prescient and every bearish block look wrong regardless of content.
        """
        bars = self.daily_bars("SPY")
        idx = next((k for k, b in enumerate(bars) if b["d"] >= day), None)
        if idx is None or idx + horizon >= len(bars):
            return None
        p0 = bars[idx]["c"]
        return (bars[idx + horizon]["c"] - p0) / p0 * 100 if p0 > 0 else None

    def collect(self, days_back: int, min_premium: float,
                min_oi_gain: int) -> List[Dict]:
        """
        One pass over history producing raw per-block records.

        Kept separate from scoring so the same sample can be sliced several
        ways without re-hitting the API — and so the day-neutral adjustment
        below can see the whole cross-section.
        """
        records: List[Dict] = []

        today = date.today()
        days, i = [], 2                      # start 2 days back so OI settled
        while len(days) < days_back and i < days_back * 2 + 20:
            d = today - timedelta(days=i)
            if d.weekday() < 5:
                days.append(d.isoformat())
            i += 1

        for day in days:
            for row in self.oi_changes(day):
                cls = self.classify(row, min_premium, min_oi_gain)
                if not cls:
                    continue
                direction, prem, ticker = cls

                bars = self.daily_bars(ticker)
                if not bars:
                    continue
                idx = next((k for k, b in enumerate(bars) if b["d"] >= day), None)
                if idx is None or idx >= len(bars) - 1:
                    self.stats["no_bars"] += 1
                    continue
                p0 = bars[idx]["c"]
                if p0 <= 0:
                    continue

                self.stats["blocks"] += 1
                bucket = next((n for n, lo, hi in CONVICTION_BUCKETS
                               if lo <= prem < hi), None)
                exc = {}
                for h in HORIZON_DAYS:
                    j = idx + h
                    mkt = self.spy_return(day, h)
                    if j >= len(bars) or mkt is None:
                        continue
                    if self._spans_split(bars, idx, j):
                        self.stats["skip_split"] += 1
                        continue
                    raw = (bars[j]["c"] - p0) / p0 * 100
                    # Excess over the market on the same dates. A bearish block
                    # is "right" when the name UNDERPERFORMS SPY, not when it
                    # falls outright.
                    exc[h] = raw - mkt
                if exc:
                    records.append({"day": day, "ticker": ticker,
                                    "dir": direction, "prem": prem,
                                    "bucket": bucket, "exc": exc})
        return records

    def run(self, days_back: int, min_premium: float, min_oi_gain: int) -> Dict:
        return self.score(self.collect(days_back, min_premium, min_oi_gain))

    # --------------------------------------------------------------- scoring

    def score(self, records: List[Dict]) -> Dict:
        """
        Aggregate records, with and without day-neutralisation.

        DAY-NEUTRAL is the important one. Names that attract huge option OI are
        high-beta names, so in a rising tape the whole block universe beats SPY
        no matter what the blocks said — the first run showed exactly that
        (+2.61% at 21d, t+5.7, for the universe irrespective of direction).
        Subtracting each DAY's cross-sectional mean excess asks the only
        question that matters: among the names whales touched that day, did the
        ones they touched BULLISHLY outperform the ones they touched BEARISHLY?
        """
        # per-day, per-horizon cross-sectional mean, for neutralisation
        day_mean: Dict[Tuple[str, int], float] = {}
        pool = defaultdict(list)
        for r in records:
            for h, v in r["exc"].items():
                pool[(r["day"], h)].append(v)
        for k, v in pool.items():
            day_mean[k] = statistics.mean(v)

        results, baseline, by_dir = (defaultdict(list) for _ in range(3))
        by_bucket_dir, neutral = defaultdict(list), defaultdict(list)

        for r in records:
            sign = 1.0 if r["dir"] == "bullish" else -1.0
            for h, v in r["exc"].items():
                signed = sign * v
                nv = sign * (v - day_mean.get((r["day"], h), 0.0))
                baseline[h].append(v)
                by_dir[(r["dir"], h)].append(signed)
                neutral[(r["dir"], h)].append(nv)
                if r["bucket"]:
                    results[(r["bucket"], h)].append(signed)
                    by_bucket_dir[(r["bucket"], r["dir"], h)].append(nv)

        return {"results": results, "baseline": baseline, "by_dir": by_dir,
                "neutral": neutral, "by_bucket_dir": by_bucket_dir,
                "stats": dict(self.stats), "n": len(records)}


def _cell(v: List[float], min_n: int = 30) -> str:
    """
    mean with t-stat. |t| < 2 means the mean is not distinguishable from 0.

    The t-stat here is OPTIMISTIC and should be read as an upper bound. It
    assumes independent observations, but a 21-day window measured on
    consecutive days overlaps ~20/21 with its neighbour, and several blocks
    often land on the same ticker the same day. Effective sample size is far
    below n, so a cell needs to clear |t|=2 comfortably to mean anything.
    """
    if len(v) < min_n:
        return f"{'n=' + str(len(v)):>20}"
    s = sorted(v)
    n = len(s)
    # Winsorise at 1/99 so a residual bad print cannot set the mean.
    lo, hi = s[n // 100], s[-(n // 100) - 1]
    w = [min(max(x, lo), hi) for x in s]
    m = statistics.mean(w)
    sd = statistics.pstdev(w) if n > 1 else 0.0
    t = (m / (sd / (n ** 0.5))) if sd > 0 else 0.0
    # Hit rate: share positive. Immune to outliers entirely; 50% = no signal.
    hit = sum(1 for x in s if x > 0) / n * 100
    return f"{m:>+6.2f}% t{t:>+5.1f} {hit:>4.1f}%"[:20].rjust(20)


def render(out: Dict) -> None:
    res, base, by_dir, st = out["results"], out["baseline"], out["by_dir"], out["stats"]
    print("=" * 96)
    print("WHALE-BLOCK BACKTEST — do large opening positions predict, over days?")
    print("Returns are EXCESS OVER SPY on the same dates, then signed by block direction.")
    print("=" * 96)
    print(f"  days ok {st.get('days_ok',0)} | date mismatch {st.get('date_mismatch',0)} | "
          f"blocks {st.get('blocks',0)}")
    print(f"  excluded: multi-leg/neutral {st.get('skip_multileg',0)} | "
          f"unsided {st.get('skip_unsided',0)} | too small {st.get('skip_small',0)} | "
          f"no bars {st.get('no_bars',0)}")

    if not st.get("blocks"):
        print("\n  No qualifying blocks — nothing can be concluded.")
        return

    hs = HORIZON_DAYS
    print(f"\n  {'CONVICTION':<14}" + "".join(f"{str(h)+'d':>20}" for h in hs))
    print("  " + "-" * (14 + 20 * len(hs)))
    for name, _, _ in CONVICTION_BUCKETS:
        print(f"  {name:<14}" + "".join(_cell(res.get((name, h), [])) for h in hs))
    print("  " + "-" * (14 + 20 * len(hs)))
    print(f"  {'ALL (unsigned)':<14}" + "".join(_cell(base.get(h, [])) for h in hs))

    print(f"\n  {'BY DIRECTION':<14}" + "".join(f"{str(h)+'d':>20}" for h in hs))
    print("  " + "-" * (14 + 20 * len(hs)))
    for d in ("bullish", "bearish"):
        print(f"  {d:<14}" + "".join(_cell(by_dir.get((d, h), [])) for h in hs))

    print("\n  DAY-NEUTRAL — each day's cross-section de-meaned, so the tape cannot")
    print("  flatter one side. This is the table that decides it.\n")
    neu, bd = out["neutral"], out["by_bucket_dir"]
    print(f"  {'BY DIRECTION':<14}" + "".join(f"{str(h)+'d':>20}" for h in hs))
    print("  " + "-" * (14 + 20 * len(hs)))
    for d in ("bullish", "bearish"):
        print(f"  {d:<14}" + "".join(_cell(neu.get((d, h), [])) for h in hs))

    print(f"\n  {'CONVICTION x DIR':<20}" + "".join(f"{str(h)+'d':>20}" for h in hs))
    print("  " + "-" * (20 + 20 * len(hs)))
    for name, _, _ in CONVICTION_BUCKETS:
        for d in ("bullish", "bearish"):
            print(f"  {name + ' ' + d:<20}"
                  + "".join(_cell(bd.get((name, d, h), [])) for h in hs))

    print("\n" + "=" * 96)
    print("  READ THIS TABLE AS: |t| < 2 means the cell is indistinguishable from zero,")
    print("  no matter how good the mean looks. 'ALL (unsigned)' is the block universe's")
    print("  own tilt vs SPY — a conviction row only shows edge if it beats THAT.")
    print("  Both directions must be positive in the DAY-NEUTRAL table. If only the")
    print("  bullish side is, the 'signal' is beta and will invert in a down tape.")
    print("  ~50 cells are shown, so 2-3 crossing |t|=2 by chance is EXPECTED. A real")
    print("  effect shows as a coherent block -- rising with conviction, both directions,")
    print("  hit rate away from 50% -- not as one lone significant cell.")
    print("=" * 96)


CACHE = "block_backtest_records.json"


def main():
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--min-premium", type=float, default=250_000)
    ap.add_argument("--min-oi-gain", type=int, default=1000)
    ap.add_argument("--cache", action="store_true",
                    help="reuse block_backtest_records.json if present")
    a = ap.parse_args()

    bt = BlockBacktest()
    records = None
    if a.cache and os.path.exists(CACHE):
        with open(CACHE) as fh:
            blob = json.load(fh)
        records = [{**r, "exc": {int(k): v for k, v in r["exc"].items()}}
                   for r in blob["records"]]
        bt.stats.update(blob.get("stats", {}))
        print(f"cached sample: {len(records)} blocks over {blob.get('days')} weekdays\n")
    if records is None:
        print(f"lookback {a.days} weekdays | min premium ${a.min_premium:,.0f} | "
              f"min OI gain {a.min_oi_gain:,}\n")
        records = bt.collect(a.days, a.min_premium, a.min_oi_gain)
        with open(CACHE, "w") as fh:
            json.dump({"days": a.days, "min_premium": a.min_premium,
                       "stats": dict(bt.stats), "records": records}, fh)

    render(bt.score(records))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
