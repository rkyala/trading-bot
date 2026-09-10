#!/usr/bin/env python3
"""
Per-ticker variance risk premium: is it PERSISTENT enough to sort on?

WHY VRP AND NOT ANOTHER FLOW IDEA
Fourteen hypotheses on this project returned null, and all but one were
directional flow or gamma. VRP is different: it is one of only two things that
has ever survived a control here - index VRP measured +2.34 vol points at
t+3.1 - and it is a MAGNITUDE statement, which is the only class of statement
that has ever measured real on this data.

What has never been tested is the per-ticker cross-section.

THE LOOK-AHEAD TRAP IN THIS ENDPOINT, AND HOW IT IS AVOIDED
/stock/{t}/volatility/variance-risk-premium/windows returns rows shaped:

    date 2026-09-08 | iv_days 5 | rv_days 3 | realized_date 2026-09-10
    risk_premium = IV at `date` MINUS realised vol over the window ENDING at
                   `realized_date`

The realised leg runs FORWARD from `date`. So risk_premium on a row dated D is
not knowable until realized_date - it is the ANSWER, not an input. Sorting
tickers on it at D would be reading the future.

So the signal is TRAILING VRP: the most recent row whose realized_date is on or
before D, i.e. a premium that has already resolved. The outcome is the row
dated D, which resolves later. Signal and outcome therefore never share a day.

THE TEST
Cross-sectional. On each date, rank tickers by trailing VRP, then measure the
forward VRP they actually delivered. If VRP is persistent, the top group should
out-deliver the bottom, and the spread is what a long/short vol book would
harvest.

    signal_t(ticker)  = last resolved risk_premium as of D
    outcome_t(ticker) = risk_premium of the row dated D
    spread            = mean outcome(top quintile) - mean outcome(bottom)

Level alone is not enough: EVERY ticker tends to carry positive VRP, so a test
that only shows "VRP > 0" is re-measuring a known risk premium, not an edge.
The tradeable claim is the SPREAD - that high-VRP names deliver more than
low-VRP names - because that is what a relative position can capture.

THE BAR, DECLARED BEFORE THE RUN
  1. top-minus-bottom spread > 0 with |t| >= 2
  2. monotone-ish across quintiles (Q5 > Q3 > Q1), not one spiking bucket
  3. the spread must exceed measured option friction, which killed the condor
     at ~2% round-trip on weeklies. A statistically real spread smaller than
     the cost of trading it is not an edge.

RESULT - FAILS, and the way it fails is the lesson.

Overlapping daily sampling gave the strongest number of the whole project:

    top-minus-bottom  +3.99 vol pts   t +7.06   (211 "days")
    quintiles         -1.60 / +0.24 / +1.17 / +0.96 / +2.38   monotone

Non-overlapping sampling (every RV_DAYS-th session, disjoint outcome windows):

    top-minus-bottom  +0.59 vol pts   t +0.20   (11 periods)
    quintiles         -1.57 / +2.21 / -1.03 / +1.86 / -0.98   scrambled

t collapsed from +7.06 to +0.20 and the monotone ladder - the very thing that
made it look mechanistically real - dissolved. Consecutive days share 20 of
their 21 outcome days, so 211 observations were really about 11, and t was
inflated by roughly sqrt(21).

CAVEAT, stated rather than buried: n=11 is thin. The endpoint carries one year
of history, so non-overlapping sampling leaves few periods. This is closer to
UNDERPOWERED than to definitively null. Widening the universe does NOT fix it -
the binding constraint is TIME, not breadth; more tickers tighten each day's
quintiles but leave the same 11 independent periods.

WHAT DOES SURVIVE
The LEVEL: mean forward VRP +0.47 vol pts, t +2.86. VRP is real per-ticker, as
it was on indices (+2.34 vol pts, t+3.1). What fails is the CROSS-SECTION -
that high-VRP names out-deliver low-VRP names. And the level alone is not
tradeable: capturing it means selling options into the ~2% round-trip friction
that already killed the condor.
"""

import argparse
import math
import os
import statistics as st
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

BASE = "https://api.unusualwhales.com/api"

IV_DAYS = 30       # the classic monthly VRP window
RV_DAYS = 21
NQ = 5             # quintiles

UNIVERSE = ("AAPL,MSFT,NVDA,AMZN,GOOGL,META,TSLA,AMD,AVGO,NFLX,INTC,MU,CRM,ORCL,"
            "ADBE,QCOM,TXN,CSCO,PFE,JNJ,XOM,CVX,JPM,BAC,WFC,GS,WMT,HD,COST,NKE,"
            "DIS,BA,CAT,GE,F,GM,UBER,ABNB,COIN,HOOD,PLTR,SNOW,SHOP,PYPL,RBLX,"
            "SPY,QQQ,IWM,SMH,XLE,XLF,XLK,GLD,SLV,TLT,HYG,EEM,FXI,ARKK,SOFI,"
            "DKNG,RIVN,LCID,CHPT,SNAP,PINS,U,ROKU,ZM,DOCU,TWLO,NET,DDOG,CRWD,"
            "PANW,ANET,MRVL,ON,SWKS,WDC,STX,DELL,HPQ,IBM,T,VZ,KO,PEP,MCD,SBUX")


def _f(v, d=None):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


class VrpBT:
    def __init__(self):
        import requests
        self.s = requests.Session()
        key = os.getenv("UW_API_KEY")
        if key:
            self.s.headers.update({"Authorization": f"Bearer {key}",
                                   "Accept": "application/json"})
        self.stats = {"ok": 0, "empty": 0, "rows": 0}

    def windows(self, ticker: str) -> List[Dict]:
        import time as _t
        for a in range(3):
            try:
                r = self.s.get(f"{BASE}/stock/{ticker}/volatility/"
                               f"variance-risk-premium/windows", timeout=30)
                if r.status_code == 200:
                    rows = r.json().get("data") or []
                    if rows:
                        self.stats["ok"] += 1
                        self.stats["rows"] += len(rows)
                    else:
                        self.stats["empty"] += 1
                    return rows
                if r.status_code == 429:
                    _t.sleep(2 * (a + 1)); continue
                return []
            except Exception:
                _t.sleep(1)
        return []

    def series(self, ticker: str) -> List[Tuple[str, str, float]]:
        """
        (date, realized_date, risk_premium) for the chosen window, sorted.

        Filtered to one IV/RV window so every ticker is measured on the same
        horizon - mixing 1-day and 180-day rows would compare different trades.
        """
        out = []
        for r in self.windows(ticker):
            if int(_f(r.get("implied_volatility_days"), -1) or -1) != IV_DAYS:
                continue
            if int(_f(r.get("realized_volatility_days"), -1) or -1) != RV_DAYS:
                continue
            d = str(r.get("date") or "")[:10]
            rd = str(r.get("realized_date") or "")[:10]
            rp = _f(r.get("risk_premium"))
            if d and rd and rp is not None:
                out.append((d, rd, rp))
        out.sort()
        return out


def build(bt: VrpBT, tickers: List[str]):
    """signal[(day,ticker)] = last RESOLVED vrp; outcome[(day,ticker)] = vrp dated day."""
    signal, outcome = {}, {}
    per_ticker = {}
    for t in tickers:
        s = bt.series(t)
        if len(s) < 60:
            continue
        per_ticker[t] = s
        for i, (d, rd, rp) in enumerate(s):
            outcome[(d, t)] = rp
            # Most recent row that had already RESOLVED by d.
            prev = None
            for j in range(i - 1, -1, -1):
                if s[j][1] <= d:            # realized_date on or before d
                    prev = s[j][2]
                    break
            if prev is not None:
                signal[(d, t)] = prev
    return signal, outcome, per_ticker


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default=UNIVERSE)
    a = ap.parse_args()
    tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
    bt = VrpBT()

    print("=" * 92)
    print(f"PER-TICKER VRP CROSS-SECTION  (IV {IV_DAYS}d vs forward RV {RV_DAYS}d)")
    print("=" * 92)
    print("  signal  = last RESOLVED risk_premium as of D (no look-ahead)")
    print("  outcome = risk_premium of the row dated D (resolves later)")
    print()

    signal, outcome, per_ticker = build(bt, tickers)
    print(f"  tickers with data: {len(per_ticker)}/{len(tickers)} | "
          f"raw rows {bt.stats['rows']} | signal points {len(signal)}")
    if len(signal) < 200:
        print("  insufficient")
        return 1

    # Level first - is VRP positive at all on this universe?
    outs = [v for v in outcome.values()]
    n = len(outs); sd = st.pstdev(outs)
    print()
    print(f"  LEVEL: mean forward VRP {st.mean(outs)*100:+.2f} vol pts  "
          f"t {st.mean(outs)/(sd/math.sqrt(n)):+.2f}  n={n}")
    print("  ^ a known risk premium; positive here is expected and is NOT the edge")

    # Cross-sectional quintiles, formed per day.
    byday = defaultdict(list)
    for (d, t), sig in signal.items():
        if (d, t) in outcome:
            byday[d].append((sig, outcome[(d, t)]))

    # NON-OVERLAPPING. The outcome window is RV_DAYS long, so consecutive days
    # share RV_DAYS-1 of it and their spreads are not independent. Pooling them
    # inflates t by roughly sqrt(RV_DAYS) - the same trap that made the first
    # flow t-stats look significant. Sampling every RV_DAYS-th session gives
    # genuinely disjoint outcome windows.
    qout = defaultdict(list)
    spreads = []
    all_days = sorted(byday)
    keep = set(all_days[::RV_DAYS])
    print(f"  non-overlapping: {len(keep)} of {len(all_days)} sessions "
          f"(every {RV_DAYS}th; outcome windows are disjoint)")
    for d, rows in byday.items():
        if d not in keep:
            continue
        if len(rows) < NQ * 3:
            continue
        rows.sort(key=lambda x: x[0])
        k = len(rows) // NQ
        for q in range(NQ):
            lo = q * k
            hi = (q + 1) * k if q < NQ - 1 else len(rows)
            for _, o in rows[lo:hi]:
                qout[q].append(o)
        top = [o for _, o in rows[-k:]]
        bot = [o for _, o in rows[:k]]
        if top and bot:
            spreads.append(st.mean(top) - st.mean(bot))

    print()
    print(f"  {'quintile':<12}{'n':>7}{'mean fwd VRP (vol pts)':>26}")
    print("  " + "-" * 46)
    for q in range(NQ):
        v = qout[q]
        if v:
            print(f"  Q{q+1} {'(low)' if q==0 else ('(high)' if q==NQ-1 else '     '):<8}"
                  f"{len(v):>7}{st.mean(v)*100:>+26.2f}")
    print("  " + "-" * 46)

    ts = 0.0
    if len(spreads) > 10:
        ns = len(spreads); sds = st.pstdev(spreads)
        ts = st.mean(spreads) / (sds / math.sqrt(ns)) if sds else 0.0
        print()
        print(f"  TOP-MINUS-BOTTOM spread: {st.mean(spreads)*100:+.2f} vol pts  "
              f"t {ts:+.2f}  ({ns} days)")

    q1 = st.mean(qout[0]) if qout[0] else 0.0
    q3 = st.mean(qout[NQ // 2]) if qout[NQ // 2] else 0.0
    q5 = st.mean(qout[NQ - 1]) if qout[NQ - 1] else 0.0
    mono = q5 > q3 > q1
    sp = st.mean(spreads) if spreads else 0.0

    print()
    print("  BAR DECLARED BEFORE THE RUN:")
    print(f"    (1) spread > 0 and |t| >= 2:      {'PASS' if (sp > 0 and abs(ts) >= 2) else 'FAIL'}  (t={ts:+.2f})")
    print(f"    (2) monotone Q5 > Q3 > Q1:        {'PASS' if mono else 'FAIL'}"
          f"  ({q1*100:+.2f} / {q3*100:+.2f} / {q5*100:+.2f})")
    print(f"    (3) spread exceeds friction:      see note")
    print()
    print("  NOTE ON (3): harvesting VRP means SELLING options. Measured friction")
    print("  on this API was ~2% round-trip on weeklies and 49.3% on SPY 0DTE wings,")
    print("  which is what killed the condor. A spread that is statistically real")
    print("  but smaller than the cost of trading it is not an edge.")
    verdict = "PASSES statistically - then check it against friction" \
        if (sp > 0 and abs(ts) >= 2 and mono) else "FAILS"
    print()
    print(f"  VERDICT: {verdict}")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
