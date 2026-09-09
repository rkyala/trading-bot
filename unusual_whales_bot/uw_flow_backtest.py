#!/usr/bin/env python3
"""
Flow-Prediction Backtest — does ask-side option flow predict forward returns?

THE QUESTION
Everything in this bot rests on one unverified premise: that following
buyer-initiated (ask-side) option flow predicts where the underlying goes.
Nothing has ever tested it. Forward paper trading would take weeks.

/stock/{ticker}/net-prem-ticks accepts a `date` and returns per-minute
ask/bid-split volume going back at least 60 days, so the premise is testable
against history right now.

    call_volume_ask_side / call_volume_bid_side
    put_volume_ask_side  / put_volume_bid_side

SIGNAL — the same directional logic the live bot uses
    bullish = calls BOUGHT + puts SOLD
    bearish = puts  BOUGHT + calls SOLD
    signal  = (bullish - bearish) / (bullish + bearish)      in [-1, +1]

This is deliberately identical to classify_alert()'s reasoning: a call hit on
the bid is bearish, a put hit on the bid is bullish. Raw call/put volume is not
used anywhere, because it is exactly the trap that made GOOGL look bullish and
IWM look bearish when both were the opposite.

WHAT IT CANNOT TEST
Individual alerts, sweeps and block detection have no history — the raw
/option-trades feed silently ignores `date` (returns 200 with today's rows).
This measures AGGREGATE directional flow only. The whale watchlist and the
per-alert pipeline still need forward collection.

GUARDS AGAINST FOOLING OURSELVES
  1. Every historical response is checked to confirm the date returned is the
     date requested. The flow endpoint's silent-ignore behaviour would
     otherwise produce a backtest over one day repeated N times, which would
     look perfectly plausible and mean nothing.
  2. Forward returns use bars strictly AFTER the signal timestamp.
  3. Results are reported against the UNCONDITIONAL return for the same bars.
     A strategy that returns +0.3% in a market that drifted +0.3% has no edge,
     and a raw mean would hide that.
  4. Sample counts are printed for every cell. Small n is not a finding.
"""

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

# Signal strength buckets (absolute value of the directional score)
BUCKETS = [
    ("weak    |s|<0.2", 0.0, 0.2),
    ("mild  0.2-0.4",   0.2, 0.4),
    ("strong 0.4-0.7",  0.4, 0.7),
    ("extreme  >0.7",   0.7, 1.01),
]

DEFAULT_TICKERS = ["NVDA", "AAPL", "TSLA", "SPY", "QQQ", "AMD", "META", "MSFT"]


def _f(v, d=0.0) -> float:
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


class FlowBacktest:
    def __init__(self, api_key: Optional[str] = None, verbose: bool = False):
        import requests
        self.session = requests.Session()
        key = api_key or os.getenv("UW_API_KEY")
        if key:
            self.session.headers.update({
                "Authorization": f"Bearer {key}", "Accept": "application/json"})
        self.base = "https://api.unusualwhales.com/api"
        self.verbose = verbose
        self.stats = {"requested": 0, "date_mismatch": 0, "empty": 0, "ok": 0, "no_bars": 0}

    # ------------------------------------------------------------------ data

    def flow_for_day(self, ticker: str, day: str) -> List[Dict]:
        """
        Per-minute flow for one ticker on one date.

        Verifies the API honoured `date`. /option-trades silently ignores it and
        returns today's rows; if this endpoint ever behaves the same way, a
        backtest would be measuring one day repeated N times.
        """
        self.stats["requested"] += 1
        try:
            r = self.session.get(f"{self.base}/stock/{ticker}/net-prem-ticks",
                                 params={"date": day}, timeout=15)
            if r.status_code != 200:
                return []
            rows = r.json().get("data", []) or []
        except Exception:
            return []

        if not rows:
            self.stats["empty"] += 1
            return []

        returned = str(rows[0].get("date"))[:10]
        if returned != day:
            self.stats["date_mismatch"] += 1
            if self.verbose:
                print(f"    ⚠️  {ticker} {day}: API returned {returned} — discarding")
            return []

        self.stats["ok"] += 1
        return rows

    def bars_for(self, ticker: str, interval: str = "5m") -> List[Dict]:
        """Regular-hours OHLC bars, oldest-first."""
        try:
            r = self.session.get(f"{self.base}/stock/{ticker}/ohlc/{interval}",
                                 params={"limit": 2500}, timeout=20)
            rows = r.json().get("data", []) if r.status_code == 200 else []
        except Exception:
            return []
        out = []
        for b in rows or []:
            if b.get("market_time") not in (None, "r"):
                continue
            try:
                out.append({"t": str(b.get("start_time") or b.get("date")),
                            "close": float(b["close"])})
            except (KeyError, TypeError, ValueError):
                continue
        out.sort(key=lambda x: x["t"])
        return out

    # ---------------------------------------------------------------- signal

    @staticmethod
    def signal_from(window: List[Dict]) -> Tuple[float, float]:
        """
        Directional score in [-1,+1] and total size, from a window of ticks.

        PREMIUM-weighted, not volume-weighted. Contract counts treat a 1-lot and
        a 5,000-lot alike, so summing volume over a 30-minute window averages to
        roughly neutral — an early version produced 43 of 48 points in the
        "weak" bucket and left the strong buckets empty, i.e. nothing to test.
        net_call_premium / net_put_premium are already signed by aggressor side,
        so large trades dominate the way they should.

        Falls back to the volume split when premium is unavailable.
        """
        ncp = sum(_f(x.get("net_call_premium")) for x in window)
        npp = sum(_f(x.get("net_put_premium")) for x in window)
        if abs(ncp) + abs(npp) > 0:
            # positive net call premium = calls bought; positive net put
            # premium = puts bought (bearish)
            bull, bear = max(ncp, 0.0) + max(-npp, 0.0), max(npp, 0.0) + max(-ncp, 0.0)
            total = bull + bear
            if total > 0:
                return (bull - bear) / total, total

        ca = sum(_f(x.get("call_volume_ask_side")) for x in window)
        cb = sum(_f(x.get("call_volume_bid_side")) for x in window)
        pa = sum(_f(x.get("put_volume_ask_side")) for x in window)
        pb = sum(_f(x.get("put_volume_bid_side")) for x in window)
        bull, bear = ca + pb, pa + cb
        total = bull + bear
        return ((bull - bear) / total, total) if total > 0 else (0.0, 0.0)

    # -------------------------------------------------------------- backtest

    def run(self, tickers: List[str], days_back: int, window_min: int,
            horizons_min: List[int]) -> Dict:
        results = defaultdict(list)     # (bucket, horizon) -> [signed returns]
        baseline = defaultdict(list)    # horizon -> [raw returns] (unconditional)
        samples = 0

        today = date.today()
        # weekdays only — weekend requests return empty and waste quota
        day_list = []
        i = 1
        while len(day_list) < days_back and i < days_back * 2 + 10:
            d = today - timedelta(days=i)
            if d.weekday() < 5:
                day_list.append(d.isoformat())
            i += 1

        for ticker in tickers:
            bars = self.bars_for(ticker, "5m")
            if not bars:
                continue
            bar_t = [b["t"] for b in bars]
            bar_c = [b["close"] for b in bars]

            first_bar_day, last_bar_day = bar_t[0][:10], bar_t[-1][:10]

            def price_at_or_after(ts: str) -> Optional[Tuple[int, float]]:
                """
                First bar at or after `ts`, or None.

                CRITICAL GUARDS. Without them the binary search returns index 0
                for any timestamp older than the bar history, so every
                out-of-range signal is paired with the SAME earliest bar. That
                produced thousands of samples measuring one 30-minute window,
                and a baseline of -0.305% where the true mean 30m return is
                -0.002% — a fake edge that looked monotonic and convincing.

                5m bars cover only ~14 trading days while flow goes back 60+,
                so this is the normal case, not an edge case.
                """
                day = ts[:10]
                if day < first_bar_day or day > last_bar_day:
                    return None

                lo, hi = 0, len(bar_t)
                while lo < hi:
                    mid = (lo + hi) // 2
                    if bar_t[mid] < ts:
                        lo = mid + 1
                    else:
                        hi = mid
                if lo >= len(bar_t):
                    return None
                # the matched bar must be the same session as the signal,
                # otherwise a 15:59 signal pairs with the next morning's open
                if bar_t[lo][:10] != day:
                    return None
                return (lo, bar_c[lo])

            for day in day_list:
                ticks = self.flow_for_day(ticker, day)
                if len(ticks) < window_min * 2:
                    continue
                ticks.sort(key=lambda x: str(x.get("tape_time") or ""))

                # step through the session in non-overlapping windows
                for i in range(window_min, len(ticks) - 1, window_min):
                    window = ticks[i - window_min:i]
                    sig, vol = self.signal_from(window)
                    if vol <= 0:
                        continue

                    ts = str(ticks[i].get("tape_time") or "")
                    if not ts:
                        continue
                    entry = price_at_or_after(ts)
                    if entry is None:
                        self.stats["no_bars"] += 1
                        continue
                    idx, p0 = entry
                    if p0 <= 0:
                        continue

                    for h in horizons_min:
                        j = idx + h // 5              # 5-minute bars
                        if j >= len(bar_c):
                            continue
                        # same-session only: skip if the bar is on a later date
                        if bar_t[j][:10] != bar_t[idx][:10]:
                            continue
                        raw = (bar_c[j] - p0) / p0 * 100
                        # signed by the flow's direction
                        signed = raw if sig >= 0 else -raw
                        for name, lo_b, hi_b in BUCKETS:
                            if lo_b <= abs(sig) < hi_b:
                                results[(name, h)].append(signed)
                                break
                        baseline[h].append(raw)
                    samples += 1

        return {"results": results, "baseline": baseline,
                "samples": samples, "stats": self.stats}


def render(out: Dict, horizons: List[int]) -> None:
    results, baseline, stats = out["results"], out["baseline"], out["stats"]

    print("=" * 78)
    print("FLOW-PREDICTION BACKTEST")
    print("=" * 78)
    print(f"  day-requests ok      : {stats['ok']}")
    print(f"  empty                : {stats['empty']}")
    print(f"  DATE MISMATCH        : {stats['date_mismatch']}  "
          f"{'(discarded — good)' if stats['date_mismatch'] else ''}")
    print(f"  dropped: no bars     : {stats.get('no_bars', 0)}  (flow older than the bar window)")
    print(f"  signal points        : {out['samples']}")

    if out["samples"] == 0:
        print("\n  No usable data — nothing can be concluded.")
        return

    print(f"\n  Returns are SIGNED by the flow's direction: positive means the")
    print(f"  flow pointed the right way. Compare each row against BASELINE,")
    print(f"  which is the unconditional move over the same bars.\n")

    hdr = f"  {'SIGNAL STRENGTH':<20}" + "".join(f"{str(h)+'m':>15}" for h in horizons)
    print(hdr)
    print("  " + "-" * (20 + 15 * len(horizons)))

    for name, _, _ in BUCKETS:
        line = f"  {name:<20}"
        for h in horizons:
            v = results.get((name, h), [])
            if len(v) < 20:
                line += f"{'n=' + str(len(v)):>15}"
            else:
                line += f"{statistics.mean(v):>+9.3f}% n{len(v):<4}"
        print(line)

    line = f"  {'BASELINE (uncond.)':<20}"
    for h in horizons:
        v = baseline.get(h, [])
        line += f"{statistics.mean(v):>+9.3f}% n{len(v):<4}" if v else f"{'-':>15}"
    print("  " + "-" * (20 + 15 * len(horizons)))
    print(line)

    print("\n" + "=" * 78)
    print("  READING THIS")
    print("  An edge means the STRONG/EXTREME rows beat BASELINE by a margin")
    print("  bigger than trading costs (~0.02-0.05% round trip on equities).")
    print("  If every row sits near baseline, aggregate flow does not predict")
    print("  at these horizons — which is a genuine and useful finding.")
    print("  Treat any cell with n<100 as indicative only.")
    print("=" * 78)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--window", type=int, default=30, help="signal window, minutes")
    ap.add_argument("--horizons", default="30,60,120")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
    horizons = [int(h) for h in a.horizons.split(",")]

    print(f"tickers  : {', '.join(tickers)}")
    print(f"lookback : {a.days} days | signal window {a.window}m | horizons {horizons}\n")

    bt = FlowBacktest(verbose=a.verbose)
    render(bt.run(tickers, a.days, a.window, horizons), horizons)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
