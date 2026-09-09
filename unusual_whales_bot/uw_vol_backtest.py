#!/usr/bin/env python3
"""
Index Volatility Backtest — is selling index vol profitable, and does dealer
gamma time it?

WHY THIS EXISTS
Two things survived testing when the whale-flow thesis did not:

    index VRP   SPY IV exceeded subsequent RV by +2.34 vol pts (t+3.1,
                non-overlapping), IWM by +3.15 (t+3.0). ~73% hit rate.
    dealer GEX  SPY's next-day move averaged 0.53% when dealer gamma was most
                positive vs 0.87% when most negative — and the effect SURVIVED
                controlling for trailing realised vol (t+2.9), so it is not
                merely a proxy for the current volatility regime.

Both are volatility statements, not direction statements. This tests them as
one system: sell index variance, use dealer gamma to time it.

THE SAMPLE-SIZE PROBLEM, AND THE FIX
The natural test — 30-day IV vs 30-day forward RV — has a fatal flaw here.
One year of history gives ELEVEN independent 30-day windows per ticker. You
cannot split eleven observations into five buckets and learn anything; the
earlier VRP table's t+12.5 collapsed to t+3.1 the moment overlapping windows
were removed.

So this measures the same economics at a ONE-DAY horizon, where every
observation is independent by construction and one year yields ~230 of them:

    implied daily move  =  IV / sqrt(252) * sqrt(2/pi)      E|Z| for a normal
    actual daily move   =  |close(t+1) / close(t) - 1|
    daily premium       =  implied - actual

Positive means options were priced above what the day delivered — i.e. selling
was profitable that day.

CRITICAL: THE LEVEL IS NOT INTERPRETABLE, THE SPREAD IS
UW's IV series is ~30-day at-the-money. Term structure is normally upward
sloping, so 30-day IV overstates the true one-day implied move, which biases
the ABSOLUTE daily premium positive for reasons that have nothing to do with
any edge. UW exposes no historical short-dated IV to correct this.

That bias is common to every gamma bucket, so it CANCELS in the difference
between buckets. Therefore:

    the absolute 'daily premium' column is NOT a P&L estimate  -- ignore it
    the SPREAD across gamma buckets is the finding

This is the same discipline that killed the block result: there, the raw
signed return looked like edge until it was compared against the right
control and turned out to be beta.

WHAT THIS IS NOT
Not an option P&L backtest. There is no bid-ask, no skew, no commission, no
gamma path, and no early stop-out. A short straddle that ends a period
profitable can still breach a risk limit mid-way, so realisable P&L is
strictly worse than a signal test implies. Treat any positive result as an
upper bound on a real strategy, never as its return.
"""

import argparse
import math
import os
import statistics as st
import sys
from typing import Dict, List, Optional, Tuple

BASE = "https://api.unusualwhales.com/api"
INDEX = ["SPY", "QQQ", "IWM", "DIA"]

# E|Z| for a standard normal: converts a vol into an expected absolute move.
E_ABS_Z = math.sqrt(2.0 / math.pi)
TRADING_DAYS = 252.0


def _f(v, d=None):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


class VolBacktest:
    def __init__(self):
        import requests
        self.s = requests.Session()
        key = os.getenv("UW_API_KEY")
        if key:
            self.s.headers.update({"Authorization": f"Bearer {key}",
                                   "Accept": "application/json"})
        self.warn: List[str] = []

    # ------------------------------------------------------------------ data

    def bars(self, t: str) -> List[Tuple[str, float]]:
        try:
            d = self.s.get(f"{BASE}/stock/{t}/ohlc/1d",
                           params={"limit": 800}, timeout=25).json().get("data", [])
        except Exception:
            return []
        out = []
        for b in d or []:
            if b.get("market_time") not in (None, "r"):
                continue
            c = _f(b.get("close"))
            day = str(b.get("date") or b.get("start_time"))[:10]
            if c and c > 0:
                out.append((day, c))
        out.sort()
        # Split guard — UW OHLC is not split-adjusted (LAZR's 1:30 reverse
        # split read as +12,915% in the block backtest). Index ETFs rarely
        # split, but an unnoticed one would wreck the |move| series.
        for i in range(1, len(out)):
            if abs(out[i][1] / out[i - 1][1] - 1.0) > 0.50:
                self.warn.append(f"{t}: >50% bar move at {out[i][0]} — split?")
        return out

    def iv_series(self, t: str) -> Dict[str, float]:
        try:
            d = self.s.get(f"{BASE}/stock/{t}/volatility/realized",
                           timeout=25).json().get("data", [])
        except Exception:
            return {}
        out = {}
        for r in d or []:
            iv = _f(r.get("implied_volatility"))
            if iv and iv > 0:
                out[str(r.get("date"))[:10]] = iv
        return out

    def gex_series(self, t: str) -> Dict[str, float]:
        try:
            d = self.s.get(f"{BASE}/stock/{t}/greek-exposure",
                           timeout=25).json().get("data", [])
        except Exception:
            return {}
        out = {}
        for g in d or []:
            cg, pg = _f(g.get("call_gamma")), _f(g.get("put_gamma"))
            if cg is None or pg is None:
                continue
            out[str(g.get("date"))[:10]] = cg + pg
        return out

    def fwd_rv(self, t: str) -> List[Tuple[str, float, float]]:
        """(date, iv, forward-realised vol) for the 30d check. Thin sample."""
        try:
            d = self.s.get(f"{BASE}/stock/{t}/volatility/realized",
                           timeout=25).json().get("data", [])
        except Exception:
            return []
        out = []
        for r in d or []:
            iv, rv = _f(r.get("implied_volatility")), _f(r.get("realized_volatility"))
            if iv and rv:
                out.append((str(r.get("date"))[:10], iv, rv))
        out.sort()
        return out

    # -------------------------------------------------------------- assembly

    def daily(self, t: str) -> List[Dict]:
        """One record per trading day: implied vs actual next-day move + gamma."""
        bl = self.bars(t)
        if not bl:
            return []
        iv, gx = self.iv_series(t), self.gex_series(t)
        days = [d for d, _ in bl]
        px = dict(bl)
        rets = [0.0] + [(bl[i][1] - bl[i - 1][1]) / bl[i - 1][1] * 100
                        for i in range(1, len(bl))]
        recs = []
        for i, d in enumerate(days):
            if i < 21 or i + 1 >= len(days):
                continue
            if d not in iv or d not in gx:
                continue
            actual = abs((px[days[i + 1]] - px[d]) / px[d]) * 100
            implied = iv[d] / math.sqrt(TRADING_DAYS) * E_ABS_Z * 100
            trail = st.pstdev(rets[i - 20:i + 1])      # no look-ahead
            if trail <= 0:
                continue
            recs.append({"date": d, "ticker": t, "gamma": gx[d],
                         "implied": implied, "actual": actual,
                         "prem": implied - actual, "trail": trail,
                         "norm": actual / trail})
        return recs


# ------------------------------------------------------------------ reporting

def _stat(v: List[float]) -> Tuple[float, float, float, int]:
    n = len(v)
    if n < 2:
        return (0.0, 0.0, 0.0, n)
    m = st.mean(v)
    se = st.pstdev(v) / math.sqrt(n)
    hit = sum(1 for x in v if x > 0) / n * 100
    return (m, (m / se if se > 0 else 0.0), hit, n)


def buckets(recs: List[Dict], k: int = 5) -> List[Tuple[str, List[Dict]]]:
    r = sorted(recs, key=lambda x: x["gamma"])
    n, q = len(r), len(r) // k
    labels = ["1 most NEG", "2", "3", "4", "5 most POS"]
    return [(labels[i], r[i * q:(i + 1) * q] if i < k - 1 else r[(k - 1) * q:])
            for i in range(k)]


def report(per_ticker: Dict[str, List[Dict]], bt: "VolBacktest") -> None:
    print("=" * 94)
    print("INDEX VOLATILITY BACKTEST — sell index vol, timed by dealer gamma")
    print("=" * 94)
    for w in bt.warn:
        print(f"  !! {w}")

    print("\n  ONE-DAY HORIZON — every observation independent (no window overlap).")
    print("  The absolute 'premium' column carries a 30d-IV term-structure bias and")
    print("  is NOT a P&L estimate. Only the SPREAD between gamma buckets is valid.\n")

    pooled: List[Dict] = []
    for t, recs in per_ticker.items():
        if len(recs) < 100:
            print(f"  {t}: only {len(recs)} usable days — skipped")
            continue
        pooled += recs
        print(f"  === {t} ===  n={len(recs)}  {recs[0]['date']} .. {recs[-1]['date']}")
        print(f"  {'gamma bucket':<14}{'implied':>10}{'actual':>10}"
              f"{'premium':>10}{'t':>7}{'win%':>7}{'trail vol':>11}{'n':>5}")
        print("  " + "-" * 76)
        for lbl, ch in buckets(recs):
            if not ch:
                continue
            m, tt, hit, n = _stat([x["prem"] for x in ch])
            print(f"  {lbl:<14}{st.mean([x['implied'] for x in ch]):>9.3f}%"
                  f"{st.mean([x['actual'] for x in ch]):>9.3f}%"
                  f"{m:>+9.3f}%{tt:>7.1f}{hit:>6.1f}%"
                  f"{st.mean([x['trail'] for x in ch]):>10.3f}%{n:>5}")
        bk = buckets(recs)
        hi = [x["prem"] for x in bk[-1][1]]
        lo = [x["prem"] for x in bk[0][1]]
        dm = st.mean(hi) - st.mean(lo)
        se = math.sqrt(st.pstdev(hi) ** 2 / len(hi) + st.pstdev(lo) ** 2 / len(lo))
        print(f"  SPREAD high-gamma minus low-gamma = {dm:+.3f}%  "
              f"t={dm / se if se else 0:+.1f}   <-- the finding")
        worst = min(recs, key=lambda x: x["prem"])
        print(f"  worst single day: {worst['date']} premium {worst['prem']:+.2f}% "
              f"(actual move {worst['actual']:.2f}%)\n")

    if pooled:
        print("  === POOLED (index products are highly correlated: treat n as")
        print("      badly overstated — this is 1 year of market, not 900 draws) ===")
        print(f"  {'gamma bucket':<14}{'premium':>10}{'t':>7}{'win%':>7}{'n':>6}")
        print("  " + "-" * 46)
        for lbl, ch in buckets(pooled):
            m, tt, hit, n = _stat([x["prem"] for x in ch])
            print(f"  {lbl:<14}{m:>+9.3f}%{tt:>7.1f}{hit:>6.1f}%{n:>6}")

        # Left tail is the entire risk of a short-vol book.
        allp = sorted(x["prem"] for x in pooled)
        n = len(allp)
        print(f"\n  LEFT TAIL (short vol dies here, not in the mean):")
        print(f"    worst  {allp[0]:+.2f}%   p1 {allp[n//100]:+.2f}%   "
              f"p5 {allp[n//20]:+.2f}%   median {allp[n//2]:+.2f}%")
        bad = [x for x in allp if x < 0]
        print(f"    losing days {len(bad)/n*100:.1f}%, mean loss {st.mean(bad):+.2f}%, "
              f"mean gain {st.mean([x for x in allp if x>=0]):+.2f}%")


def report_30d(bt: "VolBacktest", tickers: List[str], stride: int = 21) -> None:
    print("\n" + "=" * 94)
    print("  30-DAY CROSS-CHECK — the economically correct horizon, but only ~11")
    print("  INDEPENDENT windows per ticker exist in one year. Underpowered by")
    print("  construction; shown so the one-day result is not read in isolation.")
    print("=" * 94)
    print(f"  {'ticker':<8}{'mean IV-RV':>12}{'t':>8}{'win%':>8}{'n':>5}")
    print("  " + "-" * 42)
    for t in tickers:
        rows = bt.fwd_rv(t)
        v = [(iv - rv) * 100 for _, iv, rv in rows][::stride]
        if len(v) < 8:
            print(f"  {t:<8}insufficient ({len(v)})")
            continue
        m, tt, hit, n = _stat(v)
        print(f"  {t:<8}{m:>+11.2f}v{tt:>8.1f}{hit:>7.1f}%{n:>5}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default=",".join(INDEX))
    a = ap.parse_args()
    tickers = [x.strip().upper() for x in a.tickers.split(",") if x.strip()]

    bt = VolBacktest()
    per = {t: bt.daily(t) for t in tickers}
    report(per, bt)
    report_30d(bt, tickers)

    print("\n" + "=" * 94)
    print("  HOW TO READ THIS")
    print("  A positive SPREAD means dealer gamma times vol selling: options were")
    print("  richer relative to delivered movement when dealers were long gamma.")
    print("  The absolute premium level is contaminated by term structure — ignore it.")
    print("  Nothing here includes bid-ask, skew, commission or mid-period stop-outs,")
    print("  so a real strategy earns strictly less than any number above.")
    print("=" * 94)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
