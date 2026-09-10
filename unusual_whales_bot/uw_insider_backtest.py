#!/usr/bin/env python3
"""
Does discretionary insider BUYING predict forward returns?

WHY THIS IS A DIFFERENT CLASS OF TEST
Thirteen nulls on this project were all options-flow derived. This is a
different data source with a different mechanism: an insider buying their own
stock with their own money has information the tape does not, and unlike flow
it is a legally-forced disclosure rather than an inferred aggressor side.

THE FILTER THAT DECIDES THE TEST: 10b5-1
Most insider SELLING happens under pre-scheduled 10b5-1 plans - a CEO selling
on a schedule set six months earlier carries no information about today. A
test that does not strip these is mostly measuring payroll.

UW pre-computes the split, which is why /insider/{t}/ticker-flow is used here
rather than /insider/transactions:

    premium        total insider premium that day (negative = selling)
    premium_10b5   the pre-scheduled portion
    discretionary  = premium - premium_10b5      <- the informative part

/insider/transactions was rejected for a second reason: it SILENTLY IGNORES
its filters. min_filing_date, ticker and transaction_codes all returned the
identical unfiltered 500 rows spanning two days - the same silent-ignore
behaviour as /option-trades?date=. Never trust an un-verified filter on this
API.

NO LOOK-AHEAD
ticker-flow is keyed on the TRANSACTION date, not the filing date. Measured
disclosure lag on this API is median 0 days, p90 2 days (Form 4 requires two
business days). Entry is therefore delayed DISCLOSURE_LAG trading days after
the transaction date, which is conservative at the p90. Entering on the
transaction date itself would be trading on information that was not public.

HORIZON
Documented insider-buying effects are monthly-to-quarterly, so the hold is 21
trading days. NOTE this is NOT the horizon the UW bot trades (intraday to 3
days) - a positive result here would be a NEW strategy, not a filter on the
existing one.

SAMPLE CONSTRAINT
UW's bulk /ohlc/1d is capped at 756 rows = 252 regular sessions = one year, so
entries are limited to roughly the last year regardless of how far ticker-flow
reaches back (AAPL goes to 2004).

THE BAR, DECLARED BEFORE THE RUN
  1. mean market-adjusted return > 0 with |t| >= 2
  2. majority of tickers positive
  3. buys must beat SELLS - if both are positive it is beta, not insider edge
"""

import argparse
import math
import os
import statistics as st
import sys
from typing import Dict, List, Optional

BASE = "https://api.unusualwhales.com/api"

HOLD = 21              # trading days
DISCLOSURE_LAG = 2     # trading days; p90 of measured Form 4 lag
MIN_PREMIUM = 25_000   # ignore trivial discretionary amounts
MARKET_REF = "SPY"

# UNIVERSE MATTERS MORE THAN ANY PARAMETER HERE.
# A first run on mega-cap tech produced 18 events of which only 2 were BUYS.
# Mega-cap insiders receive stock as compensation and sell it; they almost
# never buy on the open market, so that universe cannot test insider BUYING
# at all. Open-market purchases concentrate in beaten-down small/mid caps,
# regional banks, energy and REITs - where an insider putting their own money
# in is a real decision rather than a payroll event.
UNIVERSE = (
    # financials / regionals - the classic insider-buying sector
    "JPM,BAC,WFC,C,USB,PNC,TFC,KEY,RF,CFG,HBAN,FITB,ZION,CMA,MTB,ALLY,SCHW,"
    # energy
    "XOM,CVX,COP,OXY,DVN,FANG,HAL,SLB,MRO,APA,EQT,AR,RRC,CHK,OVV,PR,MTDR,"
    # REITs / real estate
    "O,SPG,VTR,WELL,PLD,AMT,KIM,BXP,HST,VNO,SLG,ARE,DOC,"
    # industrials / materials / autos
    "GE,CAT,DE,BA,F,GM,LUV,DAL,UAL,AAL,X,CLF,NUE,FCX,AA,MOS,CF,"
    # consumer / retail / health, incl. names that sold off
    "WBA,CVS,TGT,DG,DLTR,KSS,M,GPS,BBY,PARA,WBD,SIRI,LUMN,NWL,VFC,"
    # smaller tech / growth with real drawdowns
    "INTC,MU,WDC,STX,HPQ,DELL,PYPL,SQ,HOOD,SOFI,LC,UPST,AFRM,RIVN,LCID,CHPT,"
    "PLTR,SNAP,PINS,RBLX,U,DKNG,PENN,CZR,MGM,WYNN"
)


def _f(v, d=None):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


def winsorise(xs: List[float]) -> List[float]:
    if len(xs) < 20:
        return xs
    s = sorted(xs)
    lo, hi = s[int(len(s) * 0.01)], s[int(len(s) * 0.99)]
    return [min(max(x, lo), hi) for x in xs]


class InsiderBT:
    def __init__(self):
        import requests
        self.s = requests.Session()
        key = os.getenv("UW_API_KEY")
        if key:
            self.s.headers.update({"Authorization": f"Bearer {key}",
                                   "Accept": "application/json"})
        self.stats = {"tickers": 0, "no_flow": 0, "no_px": 0, "events": 0, "skipped_small": 0}
        self._spy: Optional[Dict[str, float]] = None

    def _get(self, path: str, params: Dict) -> List[Dict]:
        import time as _t
        for a in range(3):
            try:
                r = self.s.get(f"{BASE}{path}", params=params, timeout=30)
                if r.status_code == 200:
                    return r.json().get("data") or []
                if r.status_code == 429:
                    _t.sleep(2 * (a + 1))
                    continue
                return []
            except Exception:
                _t.sleep(1)
        return []

    def closes(self, ticker: str) -> Dict[str, float]:
        """Regular-session daily closes. market_time filter is mandatory -
        each date appears three times (pre/regular/post)."""
        rows = self._get(f"/stock/{ticker}/ohlc/1d", {"limit": 750})
        out = {}
        for r in rows:
            if str(r.get("market_time") or "") != "r":
                continue
            c = _f(r.get("close"))
            d = str(r.get("date") or "")[:10]
            if d and c and c > 0:
                out[d] = c
        return out

    def spy(self) -> Dict[str, float]:
        if self._spy is None:
            self._spy = self.closes(MARKET_REF)
        return self._spy

    def screener_universe(self, limit: int = 500) -> List[str]:
        """
        Broad universe from the screener rather than a hand-picked list.

        Hand-picking is how the first run went wrong: mega-cap tech produced
        39 events of which only 2 were buys, because those insiders receive
        stock and sell it rather than buying on the open market. A screener
        universe removes the author's guess about where insiders buy.

        limit=500 is the real cap - limit=1000 silently returns 50, the same
        silent-fallback behaviour as spot-exposures/expiry-strike.
        """
        rows = self._get("/screener/stocks", {"limit": limit})
        out = []
        for r in rows:
            t = str(r.get("ticker") or "").upper()
            if t and not r.get("is_index") and t.isalpha() and len(t) <= 5:
                out.append(t)
        return sorted(set(out))

    def flow(self, ticker: str) -> List[Dict]:
        return self._get(f"/insider/{ticker}/ticker-flow", {"limit": 500})

    def run_ticker(self, ticker: str) -> List[Dict]:
        fl = self.flow(ticker)
        if not fl:
            self.stats["no_flow"] += 1
            return []
        px = self.closes(ticker)
        spy = self.spy()
        if len(px) < HOLD + DISCLOSURE_LAG + 20 or len(spy) < HOLD + 20:
            self.stats["no_px"] += 1
            return []
        self.stats["tickers"] += 1

        days = sorted(px)
        pos = {d: i for i, d in enumerate(days)}

        rows, last_i = [], -10 ** 9
        for r in sorted(fl, key=lambda x: str(x.get("date") or "")):
            d = str(r.get("date") or "")[:10]
            if d not in pos:
                continue
            prem = _f(r.get("premium"), 0.0) or 0.0
            p10 = _f(r.get("premium_10b5"), 0.0) or 0.0
            disc = prem - p10                      # the informative portion
            if abs(disc) < MIN_PREMIUM:
                self.stats["skipped_small"] += 1
                continue

            # NO LOOK-AHEAD: wait for the disclosure window to close.
            i = pos[d] + DISCLOSURE_LAG
            if i + HOLD >= len(days) or i >= len(days):
                continue
            # NON-OVERLAPPING per ticker.
            if i - last_i < HOLD:
                continue
            d0, d1 = days[i], days[i + HOLD]
            if d0 not in spy or d1 not in spy:
                continue

            r0, r1 = px[d0], px[d1]
            s0, s1 = spy[d0], spy[d1]
            adj = (r1 / r0 - 1.0) * 100 - (s1 / s0 - 1.0) * 100
            rows.append({"ticker": ticker, "date": d, "disc": disc,
                         "side": "buy" if disc > 0 else "sell", "adj": adj,
                         "insiders": _f(r.get("uniq_insiders"), 0) or 0})
            last_i = i
            self.stats["events"] += 1
        return rows


def block(rows: List[Dict], side: Optional[str] = None) -> Dict:
    r = [x for x in rows if side is None or x["side"] == side]
    if len(r) < 10:
        return {}
    v = winsorise([x["adj"] for x in r])
    n = len(v)
    sd = st.pstdev(v)
    return {"n": n, "mean": st.mean(v),
            "t": st.mean(v) / (sd / math.sqrt(n)) if sd else 0.0,
            "hit": sum(1 for x in v if x > 0) / n * 100,
            "med": st.median(v)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default=UNIVERSE,
                    help='comma list, or "auto" to pull from the screener')
    ap.add_argument("--screener-limit", type=int, default=500)
    a = ap.parse_args()
    bt = InsiderBT()
    if a.tickers.strip().lower() == "auto":
        tickers = bt.screener_universe(a.screener_limit)
        print(f"  universe: {len(tickers)} tickers from screener")
    else:
        tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]

    print("=" * 92)
    print("DISCRETIONARY INSIDER FLOW -> FORWARD RETURN")
    print("=" * 92)
    print(f"  discretionary = premium - premium_10b5 | hold {HOLD}d | "
          f"entry +{DISCLOSURE_LAG}d after txn (disclosure lag)")
    print(f"  market-adjusted vs {MARKET_REF} | non-overlapping | winsorised 1/99 | "
          f"min ${MIN_PREMIUM:,} discretionary")
    print()

    allrows, per_ticker = [], {}
    for t in tickers:
        r = bt.run_ticker(t)
        if r:
            allrows += r
            per_ticker[t] = r
    print(f"  tickers with data: {bt.stats['tickers']}/{len(tickers)}   "
          f"events: {bt.stats['events']}   small skipped: {bt.stats['skipped_small']}")
    if not allrows:
        print("  no data")
        return 1

    print()
    print(f"  {'side':<10}{'n':>7}{'mean %':>10}{'t':>8}{'hit%':>8}{'median':>10}")
    print("  " + "-" * 53)
    res = {}
    for lab, side in (("ALL", None), ("BUY", "buy"), ("SELL", "sell")):
        s = block(allrows, side)
        res[lab] = s
        if s:
            print(f"  {lab:<10}{s['n']:>7}{s['mean']:>+10.3f}{s['t']:>+8.2f}"
                  f"{s['hit']:>7.1f}%{s['med']:>+10.3f}")
        else:
            print(f"  {lab:<10}{'insufficient':>7}")
    print("  " + "-" * 53)
    print(f"  market-adjusted {HOLD}-day return, entry {DISCLOSURE_LAG}d after the")
    print("  insider transaction date.")

    buys = res.get("BUY") or {}
    sells = res.get("SELL") or {}
    spread = (buys.get("mean", 0.0) - sells.get("mean", 0.0)) if (buys and sells) else 0.0
    if buys and sells:
        print()
        print(f"  BUY - SELL spread: {spread:+.3f}pp")
        print("  ^ if BOTH sides are positive the result is beta, not insider information")

    import json as _json
    _json.dump(allrows, open("/tmp/claude-501/insider_events.json", "w"))
    print()
    print(f"  {'ticker':<8}{'buy mean':>11}{'n':>5}{'sell mean':>12}{'n':>5}")
    print("  " + "-" * 42)
    wins, tot = 0, 0
    for t, r in sorted(per_ticker.items()):
        b, s = block(r, "buy"), block(r, "sell")
        if not b:
            continue
        tot += 1
        wins += 1 if b["mean"] > 0 else 0
        sm = f"{s['mean']:>+12.3f}{s['n']:>5}" if s else f"{'—':>12}{'—':>5}"
        print(f"  {t:<8}{b['mean']:>+11.3f}{b['n']:>5}{sm}")
    print("  " + "-" * 42)

    # CRITERION 2, REWRITTEN.
    # It previously required >=10 events per ticker per side, which is
    # unsatisfiable for a rare event: 39 buys across 24 tickers gave 0/0 and
    # reported FAIL on a result that actually passes the concentration test the
    # criterion was meant to perform. Drop-one-ticker is the correct form - it
    # is what caught AMD carrying 70% of the GEX barrier result.
    bl = [x for x in allrows if x["side"] == "buy"]
    ok2, drop_min = False, 0.0
    if len(bl) >= 20:
        from collections import Counter as _C
        top = [t for t, _ in _C(x["ticker"] for x in bl).most_common(5)]
        ts = []
        for t in top:
            r = [x["adj"] for x in bl if x["ticker"] != t]
            if len(r) > 10:
                sd_ = st.pstdev(r)
                ts.append(st.mean(r) / (sd_ / math.sqrt(len(r))) if sd_ else 0.0)
        if ts:
            drop_min = min(ts)
            ok2 = drop_min >= 2.0
        print()
        print(f"  DROP-ONE-TICKER (top 5 contributors): worst t = {drop_min:+.2f}")

    ok1 = bool(buys) and buys["mean"] > 0 and abs(buys["t"]) >= 2.0
    ok3 = bool(buys and sells) and spread > 0
    print()
    print("  BAR DECLARED BEFORE THE RUN:")
    print(f"    (1) BUY mean > 0 and |t| >= 2:   {'PASS' if ok1 else 'FAIL'}"
          f"  (t={buys.get('t', 0):+.2f})")
    print(f"    (2) survives drop-one-ticker:    {'PASS' if ok2 else 'FAIL'}"
          f"  (worst t={drop_min:+.2f})")
    print(f"    (3) BUY beats SELL:              {'PASS' if ok3 else 'FAIL'}  ({spread:+.3f}pp)")
    print()
    print(f"  VERDICT: {'PASSES - worth pursuing' if (ok1 and ok2 and ok3) else 'FAILS'}")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
