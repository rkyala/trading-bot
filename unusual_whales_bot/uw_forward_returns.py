#!/usr/bin/env python3
"""
Forward-Return Analysis — does whale option flow predict the underlying, and
over what horizon?

THE QUESTION THIS EXISTS TO ANSWER
The bot filters signals to 2-60 DTE. That cutoff was a judgement call, and it
discards ~53% of all premium — disproportionately the LARGEST trades (mean
premium at >120 DTE is 4.4x the 0-1d bucket). The GOOGL Nov-20 $370 call
($27.9M, 12x OI, 100% ask-side) was rejected on exactly this rule.

Whether that is correct depends entirely on something we have never measured:
does long-dated whale positioning predict short-horizon returns, or only the
multi-month move it is actually betting on?

METHOD
`screened_alerts.jsonl` records every Phase-1 survivor at observation time with
its symbol, timestamp, spot price, and the filter's verdict. This script pairs
each observation with what the underlying subsequently did, at several
horizons, and groups the results by the dimensions the filter screens on.

SIGNAL RETURN, NOT RAW RETURN
Returns are signed by the flow's own direction: a bearish signal followed by a
price fall is a WIN. Raw returns would make a falling market look like a
failure of every signal, bullish or bearish.

LOOK-AHEAD
Only bars strictly AFTER the observation timestamp are used. Nothing computed
here feeds a live decision — this is offline analysis over already-recorded
observations, so there is no path for future data to reach the bot.

USAGE
    python3 uw_forward_returns.py                  # all horizons
    python3 uw_forward_returns.py --horizon 1d     # one horizon
    python3 uw_forward_returns.py --min-premium 1000000
"""

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

# Horizons in trading-ish calendar days. A whale buying 73-DTE contracts is
# expressing a multi-week view, so the horizon grid has to extend past a day.
HORIZONS = {
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
    "3d": timedelta(days=3),
    "1w": timedelta(days=7),
    "2w": timedelta(days=14),
    "1m": timedelta(days=30),
}

DTE_BUCKETS = [
    ("0-1d", 0, 1), ("2-7d", 2, 7), ("8-30d", 8, 30),
    ("31-60d", 31, 60), ("61-120d", 61, 120), (">120d", 121, 10_000),
]

PREMIUM_BUCKETS = [
    ("100-250k", 100_000, 250_000), ("250-500k", 250_000, 500_000),
    ("500k-1M", 500_000, 1_000_000), ("1M-5M", 1_000_000, 5_000_000),
    (">5M", 5_000_000, 10**12),
]


def load_observations(path: str) -> List[Dict]:
    if not os.path.exists(path):
        return []
    rows = []
    for line in open(path):
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


class PriceHistory:
    """Cached daily+intraday bars, fetched once per symbol."""

    def __init__(self):
        self._daily: Dict[str, object] = {}
        self._intraday: Dict[str, object] = {}

    def _fetch(self, symbol: str, intraday: bool):
        cache = self._intraday if intraday else self._daily
        if symbol in cache:
            return cache[symbol]
        try:
            import yfinance as yf
            from uw_market_data import SYMBOL_MAP
            ticker = SYMBOL_MAP.get(symbol.upper(), symbol.upper())
            if intraday:
                df = yf.Ticker(ticker).history(period="1mo", interval="60m")
            else:
                df = yf.Ticker(ticker).history(period="6mo", interval="1d")
            cache[symbol] = df if df is not None and not df.empty else None
        except Exception:
            cache[symbol] = None
        return cache[symbol]

    def price_at_or_after(self, symbol: str, when: datetime, intraday: bool) -> Optional[float]:
        """
        First close at or after `when`. Returns None when the moment has not
        happened yet, or no bar covers it.
        """
        df = self._fetch(symbol, intraday)
        if df is None or df.empty:
            return None
        try:
            import pandas as pd
            idx = df.index
            if idx.tz is None:
                target = when.replace(tzinfo=None)
            else:
                target = when.astimezone(idx.tz)
            after = df[idx >= target]
            if after.empty:
                return None
            return float(after["Close"].iloc[0])
        except Exception:
            return None


def signed_return(raw_pct: float, bias: str) -> float:
    """Return signed by the flow's own direction (bearish + fall = win)."""
    return -raw_pct if bias == "bearish" else raw_pct


def analyse(rows: List[Dict], horizons: List[str], min_premium: float) -> Dict:
    hist = PriceHistory()
    now = datetime.now(timezone.utc)
    results = defaultdict(list)   # (group_kind, group, horizon) -> [signed returns]
    stats = {"rows": 0, "priced": 0, "too_recent": 0, "no_data": 0}

    for r in rows:
        prem = r.get("premium") or 0
        if prem < min_premium:
            continue
        sym = r.get("symbol")
        spot0 = r.get("spot_at_observation")
        bias = (r.get("uw_bias") or "neutral").lower()
        if not sym or not spot0 or bias == "neutral":
            continue
        try:
            t0 = datetime.fromisoformat(str(r["observed_at"]))
            if t0.tzinfo is None:
                t0 = t0.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        stats["rows"] += 1
        dte = r.get("dte")
        passed = bool(r.get("filter_passed"))

        for hname in horizons:
            delta = HORIZONS[hname]
            when = t0 + delta
            if when > now:
                stats["too_recent"] += 1
                continue
            px = hist.price_at_or_after(sym, when, intraday=(delta <= timedelta(hours=8)))
            if px is None:
                stats["no_data"] += 1
                continue
            stats["priced"] += 1
            sr = signed_return((px - spot0) / spot0 * 100, bias)

            results[("verdict", "PASSED" if passed else "REJECTED", hname)].append(sr)
            if dte is not None:
                for name, lo, hi in DTE_BUCKETS:
                    if lo <= dte <= hi:
                        results[("dte", name, hname)].append(sr); break
            for name, lo, hi in PREMIUM_BUCKETS:
                if lo <= prem < hi:
                    results[("premium", name, hname)].append(sr); break
            results[("side", r.get("side") or "other", hname)].append(sr)

    return {"results": results, "stats": stats}


def render(bundle: Dict, horizons: List[str]) -> None:
    results, stats = bundle["results"], bundle["stats"]

    print("=" * 78)
    print("FORWARD-RETURN ANALYSIS — signed by the flow's own direction")
    print("=" * 78)
    print(f"  observations usable : {stats['rows']}")
    print(f"  price points found  : {stats['priced']}")
    print(f"  horizon not yet due : {stats['too_recent']}")
    print(f"  no price data       : {stats['no_data']}")

    if stats["priced"] == 0:
        print("\n  ⚠️  Nothing to report yet — no horizon has elapsed for any observation.")
        print("      This is expected on day one. Re-run once a day has passed;")
        print("      the 1w/1m buckets need a week and a month respectively.")
        print("\n      NOTE: an empty result here is NOT evidence either way about")
        print("      the DTE cutoff. It means the question is still open.")
        return

    for kind, title in (("verdict", "OUR FILTER'S VERDICT"),
                        ("dte", "BY DTE BUCKET  (does long-dated flow predict?)"),
                        ("premium", "BY PREMIUM  (does size predict?)"),
                        ("side", "BY SIDE  (ask=bought, bid=sold)")):
        groups = sorted({g for (k, g, h) in results if k == kind})
        if not groups:
            continue
        print(f"\n--- {title} ---")
        header = f"  {'GROUP':<12}" + "".join(f"{h:>14}" for h in horizons)
        print(header)
        print("  " + "-" * (12 + 14 * len(horizons)))
        for g in groups:
            line = f"  {g:<12}"
            for h in horizons:
                vals = results.get((kind, g, h), [])
                if len(vals) < 3:
                    line += f"{'n=' + str(len(vals)):>14}"
                else:
                    line += f"{statistics.mean(vals):>+9.2f}% n{len(vals):<3}"
            print(line)

    print("\n" + "=" * 78)
    print("  Reading this: a POSITIVE mean means the flow's implied direction was")
    print("  correct on average over that horizon. Compare REJECTED against PASSED —")
    print("  if REJECTED scores better at longer horizons, the DTE cutoff is")
    print("  discarding signal rather than noise.")
    print("  Treat any cell with n<30 as indicative only.")
    print("=" * 78)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="screened_alerts.jsonl")
    ap.add_argument("--horizon", action="append", choices=list(HORIZONS),
                    help="restrict to specific horizons (repeatable)")
    ap.add_argument("--min-premium", type=float, default=0.0)
    args = ap.parse_args()

    rows = load_observations(args.file)
    if not rows:
        print(f"No observations in {args.file}.")
        print("The bot writes this file as it screens alerts; run a session first.")
        return 1

    horizons = args.horizon or list(HORIZONS)
    print(f"Loaded {len(rows)} observations from {args.file}\n")
    render(analyse(rows, horizons, args.min_premium), horizons)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
