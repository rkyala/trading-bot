#!/usr/bin/env python3
"""
Volatility-Normalised Condor — out-of-sample by construction.

WHY THIS EXISTS
The fixed-percentage weekly condor showed SPY at +$35.64 (t+2.08) and then
failed out-of-sample: QQQ +$0.77 (t+0.04), IWM +$7.48 (t+0.93). The diagnosis
was in the credit ratios — SPY 28.4%, QQQ 41.2%, IWM 43.7%. A fixed 1% OTM is
NOT the same trade on instruments with different volatility: on SPY 1% sat
further out in vol-adjusted terms, so it breached less and looked profitable.
A strike-selection accident, not an edge.

This removes that confound. Strikes are placed a fixed number of EXPECTED-MOVE
SIGMAS from spot, and wings are scaled in sigma too, so the structure is
genuinely identical across instruments.

    sigma = prev_iv * sqrt(hold_days / 365) * spot
    short strikes  spot +/- K_SIGMA * sigma
    wings          K_WIDTH * sigma beyond each short

prev_iv is the PREVIOUS session's implied vol, so it is knowable at entry.
prev_iv + iv_change would be the end-of-day value and is look-ahead.

THE PARAMETER SET IS DECLARED HERE, BEFORE ANY RESULT IS SEEN
Every previous candidate died partly from multiple comparisons: roughly ten
configurations were tried before one crossed t=2, which is about what chance
produces. So the parameters below are fixed in advance, applied identically to
all three instruments, and NOT tuned per instrument. If the effect is real it
shows up on all three; if it only shows up where it was developed, it is
selection again.

    K_SIGMA  = 1.0    shorts one expected move out (~32% breach if lognormal)
    K_WIDTH  = 0.5    wings half a sigma beyond each short
    DTE      = 3-7    weekly, where measured friction is ~2% round-trip
    FRICTION = 0.005  measured, not assumed (uw_friction_matrix.py)

THE BAR, ALSO SET IN ADVANCE
All three instruments positive, and the majority clearing |t| = 2. Anything
less is not a strategy — it is one instrument's noise. Pooling the three is
NOT evidence: they are highly correlated index ETFs trading the same weeks, so
a pooled t is inflated for the same reason it was in the vol backtest.
"""

import json
import math
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uw_condor_backtest import CondorBacktest

# --- declared in advance; do not tune per instrument -----------------------
K_SIGMA = 1.0
K_WIDTH = 0.5
MIN_DTE, MAX_DTE = 3, 7
FRICTION = 0.005
DAYS = 500
TICKERS = ["SPY", "QQQ", "IWM"]


def enrich(bt, ticker: str, panel: dict) -> dict:
    """
    Attach the PREVIOUS session's iv30d to each entry day.

    Done as a patch over the cached panel so the chains do not have to be
    re-fetched. iv30d for day D is that day's CLOSING implied vol, so day D-1's
    value is the one knowable when strikes are chosen at D's open.
    """
    import requests
    from datetime import date as _d, timedelta as _td
    need = [k for k, v in panel.items() if "prev_iv30" not in v]
    if not need:
        return panel
    print(f"  enriching {ticker}: {len(need)} days need prev-session IV")
    for day in need:
        d = _d.fromisoformat(day) - _td(days=1)
        iv = None
        for _ in range(4):                       # walk back over weekends
            try:
                r = bt.s.get("https://api.unusualwhales.com/api/screener/stocks",
                             params={"date": d.isoformat(), "ticker": ticker,
                                     "limit": 5}, timeout=25)
                rows = r.json().get("data", []) if r.status_code == 200 else []
                row = next((x for x in rows if str(x.get("ticker")).upper() == ticker), None)
                if row and row.get("iv30d"):
                    iv = float(row["iv30d"])
                    break
            except Exception:
                pass
            d -= _td(days=1)
        panel[day]["prev_iv30"] = iv
    return panel


def run(ticker: str) -> dict:
    bt = CondorBacktest(ticker, max_skew=3.0, min_dte=MIN_DTE, max_dte=MAX_DTE)
    bt._sigma_width = K_WIDTH
    cache = f"{ticker.lower()}_{MIN_DTE}_{MAX_DTE}_condor_panel.json"
    if os.path.exists(cache):
        panel = json.load(open(cache))
    else:
        print(f"  collecting {ticker} ...")
        panel = bt.collect(DAYS)
        json.dump(panel, open(cache, "w"))
    if not panel:
        return {}
    panel = enrich(bt, ticker, panel)
    json.dump(panel, open(cache, "w"))

    rows = []
    for day in sorted(panel):
        rec = panel[day]
        legs = bt.build(day, rec, "sigma", 0.0, K_SIGMA)
        if not legs:
            continue
        r = bt.settle(legs, rec["expiry_bar"]["close"], FRICTION)
        if r["credit"] <= 0 or r["credit"] >= r["max_width"] * 0.90:
            continue
        rows.append({"pnl": r["pnl"] * 100.0,
                     "cr": r["credit"] / r["max_width"],
                     "breached": r["breached"],
                     "up": rec["expiry_bar"]["close"] > rec["bar"]["open"]})
    if len(rows) < 20:
        return {"ticker": ticker, "n": len(rows)}

    p = [x["pnl"] for x in rows]
    n = len(p)
    sd = st.pstdev(p)
    up = [x["pnl"] for x in rows if x["up"]]
    dn = [x["pnl"] for x in rows if not x["up"]]
    return {"ticker": ticker, "n": n, "mean": st.mean(p),
            "t": st.mean(p) / (sd / math.sqrt(n)) if sd else 0.0,
            "win": sum(1 for x in p if x > 0) / n * 100,
            "breach": sum(1 for x in rows if x["breached"]) / n * 100,
            "cr": st.median([x["cr"] for x in rows]) * 100,
            "up": st.mean(up) if up else 0.0, "dn": st.mean(dn) if dn else 0.0,
            "worst": min(p), "total": sum(p)}


def main():
    print("=" * 92)
    print("VOLATILITY-NORMALISED WEEKLY CONDOR — out-of-sample by construction")
    print("=" * 92)
    print(f"  shorts {K_SIGMA:.1f} sigma out | wings {K_WIDTH:.1f} sigma | "
          f"DTE {MIN_DTE}-{MAX_DTE} | friction ${FRICTION:.3f}/leg")
    print("  parameters fixed in advance, identical on all three instruments, "
          "no per-instrument tuning")
    print()
    res = [run(t) for t in TICKERS]
    res = [r for r in res if r and r.get("n", 0) >= 20]
    if not res:
        print("  insufficient data")
        return 1

    print(f"  {'ticker':<8}{'n':>5}{'mean $':>10}{'t':>7}{'win%':>7}"
          f"{'breach%':>9}{'cr/wid':>8}{'up mean':>9}{'dn mean':>9}{'worst':>8}")
    print("  " + "-" * 82)
    for r in res:
        print(f"  {r['ticker']:<8}{r['n']:>5}{r['mean']:>+10.2f}{r['t']:>+7.2f}"
              f"{r['win']:>6.1f}%{r['breach']:>8.1f}%{r['cr']:>7.1f}%"
              f"{r['up']:>+9.2f}{r['dn']:>+9.2f}{r['worst']:>8.0f}")
    print("  " + "-" * 82)

    # The credit ratios are the diagnostic: if normalisation worked they should
    # now be close together, where the fixed-% version had 28.4 / 41.2 / 43.7.
    crs = [r["cr"] for r in res]
    print()
    print(f"  credit/width spread across instruments: "
          f"{min(crs):.1f}% - {max(crs):.1f}%  (fixed-% version was 28.4-43.7%)")
    print("  ^ if these are now close, the structures are genuinely comparable")

    pos = sum(1 for r in res if r["mean"] > 0)
    sig = sum(1 for r in res if abs(r["t"]) >= 2.0 and r["mean"] > 0)
    print()
    print("  BAR SET IN ADVANCE: all three positive AND majority at |t| >= 2")
    print(f"    positive:    {pos}/3")
    print(f"    |t| >= 2:    {sig}/3")
    verdict = ("PASSES — worth pursuing" if pos == 3 and sig >= 2 else
               "FAILS — does not clear the bar set before the run")
    print(f"    verdict:     {verdict}")
    print()
    print("=" * 92)
    print("  Pooling the three is NOT evidence: they are correlated index ETFs")
    print("  trading the same weeks, so a pooled t is inflated — the same trap")
    print("  the vol backtest hit with four ETFs at t+4.4.")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
