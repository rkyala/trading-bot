#!/usr/bin/env python3
"""
Does ANY combination of technical + option features rank forward returns?

THE OBJECTION THIS ANSWERS
The live bot gates on three indicators (MA20, RSI14, VWAP) and they measured
WORSE than useless: over 104,924 observations the score ladder was flat and the
TRADED set returned -0.03% against +0.01% for the SKIPPED set. The fair
objection is "you only tried three indicators" - maybe the inputs were fine and
the choice was poor.

So this widens the panel to ~25 features spanning BOTH data sources and asks
one question: does anything here rank forward returns cross-sectionally?

WHY A FLAT LADDER IS THE REAL DIAGNOSTIC
MA, RSI, VWAP, MACD, Bollinger and Ichimoku are all transformations of one
OHLCV series. Adding the fourth view of the same input adds correlated opinions,
not information. If price-derived features carried signal and we had merely
picked weak ones, a wide panel should show SOME monotonicity. If a 25-feature
panel over price AND options is also flat, the problem is the input, not the
indicator choice - and that is a far more useful answer than another null.

METHOD - CROSS-SECTIONAL INFORMATION COEFFICIENT
For each session, rank every ticker by a feature and correlate those ranks with
ranks of the forward return (Spearman). That per-day number is the IC. The mean
IC across sessions, and its t-stat, is the standard way to ask "does this
feature rank outcomes".

Cross-sectional ranking IS the market adjustment: de-meaning within a day
removes the market move, which is what contaminated the early flow tests.

GUARDS, all bought with earlier false positives on this project
  non-overlapping   the horizon is HORIZON days, so sessions are sampled every
                    HORIZON-th day. Daily sampling of a 3-day horizon inflates
                    t by ~sqrt(3) - exactly how the VRP cross-section reached
                    t+7.06 before collapsing to t+0.20.
  multiple testing  ~25 features means roughly one crosses |t|=2 by chance, so
                    the bar is |t| >= 3, declared below.
  time split        the combined model is fit on the first 60% of sessions and
                    scored on the last 40%. In-sample fit is not evidence.
  sign stability    a feature must keep its IC sign across both halves.

THE BAR, DECLARED BEFORE THE RUN
  1. at least one single feature with |mean IC| >= 0.03 and |t| >= 3
  2. that feature keeps its sign in BOTH halves of the sample
  3. the combined ridge model has positive IC on the HELD-OUT split
Anything less is a flat panel, and the answer to "we only tried three
indicators" is then settled.
"""

import argparse
import math
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

BASE = "https://api.unusualwhales.com/api"
HORIZON = 3          # trading days held; matches the bot's actual hold
TRAIN_FRAC = 0.6
MIN_NAMES = 25       # a cross-section needs width to rank
IC_BAR = 0.03
T_BAR = 3.0


def _f(v, d=None):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


class PanelBT:
    def __init__(self):
        import requests
        self.s = requests.Session()
        key = os.getenv("UW_API_KEY")
        if key:
            self.s.headers.update({"Authorization": f"Bearer {key}",
                                   "Accept": "application/json"})
        self.stats = {"days": 0, "empty": 0, "rows": 0}

    def screener(self, day: str, limit: int) -> List[Dict]:
        import time as _t
        for a in range(3):
            try:
                r = self.s.get(f"{BASE}/screener/stocks",
                               params={"date": day, "limit": limit}, timeout=30)
                if r.status_code == 200:
                    rows = r.json().get("data") or []
                    # The date must be echoed back. Several endpoints on this
                    # API accept `date` and silently return today's rows.
                    if rows and str(rows[0].get("date") or "")[:10] == day:
                        self.stats["days"] += 1
                        self.stats["rows"] += len(rows)
                        return rows
                    self.stats["empty"] += 1
                    return []
                if r.status_code == 429:
                    _t.sleep(2 * (a + 1)); continue
                return []
            except Exception:
                _t.sleep(1)
        return []

    def collect(self, days_back: int, limit: int) -> Dict[str, Dict[str, Dict]]:
        today = date.today()
        days, i = [], 1
        while len(days) < days_back and i < days_back * 2 + 40:
            d = today - timedelta(days=i)
            if d.weekday() < 5:
                days.append(d.isoformat())
            i += 1
        days.sort()

        panel = {}
        for n, day in enumerate(days, 1):
            rows = self.screener(day, limit)
            if not rows:
                continue
            rec = {}
            for r in rows:
                t = str(r.get("ticker") or "").upper()
                c = _f(r.get("close"))
                if not t or r.get("is_index") or not c or c <= 0:
                    continue
                rec[t] = r
            if rec:
                panel[day] = rec
            if n % 40 == 0:
                print(f"    {n}/{len(days)} days ... {len(panel)} usable")
        return panel


# ------------------------------------------------------------------ features

def build_features(panel: Dict, hist: Dict[str, List[float]], day: str,
                   ticker: str, r: Dict) -> Optional[Dict[str, float]]:
    """
    ~25 features: TECHNICAL from the price history assembled out of the panel
    itself, OPTION from the screener row. All computable at day's close.
    """
    closes = hist.get(ticker, [])
    if len(closes) < 55:
        return None
    c = closes[-1]
    if c <= 0:
        return None

    arr = np.array(closes[-60:], dtype=float)
    rets = np.diff(np.log(arr))

    def sma(n):
        return float(arr[-n:].mean()) if len(arr) >= n else None

    ma20, ma50 = sma(20), sma(50)
    if not ma20 or not ma50:
        return None

    # RSI(14)
    d = np.diff(arr[-15:])
    gain = float(d[d > 0].sum()) / 14 if len(d) else 0.0
    loss = -float(d[d < 0].sum()) / 14 if len(d) else 0.0
    rsi = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)

    hi, lo = _f(r.get("high"), c), _f(r.get("low"), c)
    pc = _f(r.get("prev_close"), c) or c
    cv, pv = _f(r.get("call_volume"), 0.0) or 0.0, _f(r.get("put_volume"), 0.0) or 0.0
    cab, cbb = _f(r.get("call_volume_ask_side"), 0.0) or 0.0, _f(r.get("call_volume_bid_side"), 0.0) or 0.0
    pab, pbb = _f(r.get("put_volume_ask_side"), 0.0) or 0.0, _f(r.get("put_volume_bid_side"), 0.0) or 0.0
    coi = _f(r.get("call_open_interest"), 0.0) or 0.0
    mcap = _f(r.get("marketcap"), 0.0) or 0.0
    iv30 = _f(r.get("iv30d"))
    iv1w = _f(r.get("iv30d_1w"))
    iv1m = _f(r.get("iv30d_1m"))
    rv = _f(r.get("realized_volatility"))

    f = {
        # ---- technical: transformations of one price series ----
        "ret_1d":       float(arr[-1] / arr[-2] - 1) if len(arr) > 1 else 0.0,
        "ret_5d":       float(arr[-1] / arr[-6] - 1) if len(arr) > 5 else 0.0,
        "ret_21d":      float(arr[-1] / arr[-22] - 1) if len(arr) > 21 else 0.0,
        "rsi_14":       rsi,
        "dist_ma20":    c / ma20 - 1.0,
        "dist_ma50":    c / ma50 - 1.0,
        "ma20_ma50":    ma20 / ma50 - 1.0,
        "hl_range":     (hi - lo) / c if c else 0.0,
        "gap":          c / pc - 1.0 if pc else 0.0,
        "vol_21":       float(rets[-21:].std()) if len(rets) >= 21 else 0.0,
        "dist_hi60":    c / float(arr.max()) - 1.0,
        "dist_lo60":    c / float(arr.min()) - 1.0,
        # ---- option / vol: genuinely different inputs ----
        "pc_ratio":     pv / (cv + pv) if (cv + pv) > 0 else 0.5,
        "call_aggr":    (cab - cbb) / (cab + cbb) if (cab + cbb) > 0 else 0.0,
        "put_aggr":     (pab - pbb) / (pab + pbb) if (pab + pbb) > 0 else 0.0,
        "net_call_prem": (_f(r.get("net_call_premium"), 0.0) or 0.0) / mcap if mcap else 0.0,
        "net_put_prem": (_f(r.get("net_put_premium"), 0.0) or 0.0) / mcap if mcap else 0.0,
        "iv30d":        iv30 if iv30 is not None else 0.0,
        "iv_rank":      _f(r.get("iv_rank"), 0.0) or 0.0,
        "iv_term":      (iv1m - iv1w) if (iv1m is not None and iv1w is not None) else 0.0,
        "vrp":          (iv30 - rv) if (iv30 is not None and rv is not None) else 0.0,
        "gex_ratio":    _f(r.get("gex_ratio"), 0.0) or 0.0,
        "gex_chg":      _f(r.get("gex_perc_change"), 0.0) or 0.0,
        "dir_gamma":    (_f(r.get("cum_dir_gamma"), 0.0) or 0.0) / mcap if mcap else 0.0,
        "rel_volume":   _f(r.get("relative_volume"), 0.0) or 0.0,
        "vol_oi":       cv / coi if coi > 0 else 0.0,
        "imp_move_7":   _f(r.get("implied_move_perc_7"), 0.0) or 0.0,
    }
    return {k: (v if v == v and abs(v) < 1e9 else 0.0) for k, v in f.items()}


def spearman(a: List[float], b: List[float]) -> float:
    n = len(a)
    if n < 8:
        return 0.0

    def rank(x):
        order = sorted(range(len(x)), key=lambda i: x[i])
        rr = [0.0] * len(x)
        for pos, i in enumerate(order):
            rr[i] = float(pos)
        return rr

    ra, rb = rank(a), rank(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((x - mb) ** 2 for x in rb))
    return num / (da * db) if da and db else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=250)
    ap.add_argument("--limit", type=int, default=300)
    a = ap.parse_args()

    bt = PanelBT()
    print("=" * 96)
    print("TECHNICAL + OPTION PANEL — does ANYTHING rank forward returns?")
    print("=" * 96)
    print(f"  horizon {HORIZON}d | cross-sectional Spearman IC | non-overlapping "
          f"(every {HORIZON}th session)")
    print(f"  bar: |IC| >= {IC_BAR} AND |t| >= {T_BAR} (raised for ~25 comparisons)")
    print()
    print("  collecting ...")
    panel = bt.collect(a.days, a.limit)
    days = sorted(panel)
    print(f"  {len(days)} sessions, {bt.stats['rows']} ticker-days")
    if len(days) < HORIZON * 12:
        print("  insufficient")
        return 1

    # Price history per ticker, assembled from the panel itself.
    hist: Dict[str, List[float]] = defaultdict(list)
    rows_by_day: Dict[str, List[Tuple[str, Dict[str, float], float]]] = {}

    for i, day in enumerate(days):
        for t, r in panel[day].items():
            hist[t].append(_f(r.get("close"), 0.0) or 0.0)
        if i + HORIZON >= len(days):
            continue
        fwd_day = days[i + HORIZON]
        out = []
        for t, r in panel[day].items():
            nxt = panel.get(fwd_day, {}).get(t)
            if not nxt:
                continue
            c0, c1 = _f(r.get("close")), _f(nxt.get("close"))
            if not c0 or not c1 or c0 <= 0:
                continue
            ret = c1 / c0 - 1.0
            if abs(ret) > 0.5:           # split / corporate action
                continue
            feats = build_features(panel, hist, day, t, r)
            if feats:
                out.append((t, feats, ret))
        if len(out) >= MIN_NAMES:
            rows_by_day[day] = out

    # NON-OVERLAPPING: the horizon is HORIZON days.
    sampled = sorted(rows_by_day)[::HORIZON]
    print(f"  usable sessions {len(rows_by_day)} -> {len(sampled)} non-overlapping")
    if len(sampled) < 20:
        print("  insufficient after non-overlap sampling")
        return 1

    names = sorted(next(iter(rows_by_day.values()))[0][1].keys())
    half = len(sampled) // 2

    ics: Dict[str, List[float]] = defaultdict(list)
    ics_h1: Dict[str, List[float]] = defaultdict(list)
    ics_h2: Dict[str, List[float]] = defaultdict(list)
    for n, day in enumerate(sampled):
        rows = rows_by_day[day]
        rets = [r for _, _, r in rows]
        for fn in names:
            v = [f[fn] for _, f, _ in rows]
            ic = spearman(v, rets)
            ics[fn].append(ic)
            (ics_h1 if n < half else ics_h2)[fn].append(ic)

    print()
    print(f"  {'feature':<16}{'mean IC':>10}{'t':>8}{'IC h1':>9}{'IC h2':>9}{'stable':>8}")
    print("  " + "-" * 62)
    res = []
    for fn in names:
        v = ics[fn]
        m = st.mean(v)
        sd = st.pstdev(v)
        t = m / (sd / math.sqrt(len(v))) if sd else 0.0
        h1 = st.mean(ics_h1[fn]) if ics_h1[fn] else 0.0
        h2 = st.mean(ics_h2[fn]) if ics_h2[fn] else 0.0
        stable = (h1 > 0) == (h2 > 0)
        res.append((abs(t), fn, m, t, h1, h2, stable))
    res.sort(reverse=True)
    for _, fn, m, t, h1, h2, stable in res:
        print(f"  {fn:<16}{m:>+10.4f}{t:>+8.2f}{h1:>+9.4f}{h2:>+9.4f}"
              f"{'  yes' if stable else '   no':>8}")
    print("  " + "-" * 62)

    passers = [r for r in res if abs(r[2]) >= IC_BAR and abs(r[3]) >= T_BAR]
    stable_passers = [r for r in passers if r[6]]

    # ---- combined ridge, fit on train sessions only ----
    def matrix(sess):
        X, y = [], []
        for day in sess:
            rows = rows_by_day[day]
            rets = [r for _, _, r in rows]
            mu = st.mean(rets)
            for _, f, r in rows:
                X.append([f[n] for n in names])
                y.append(r - mu)          # de-meaned = market-adjusted
        return np.array(X), np.array(y)

    tr, te = sampled[:int(len(sampled) * TRAIN_FRAC)], sampled[int(len(sampled) * TRAIN_FRAC):]
    combined_ic = 0.0
    if len(te) >= 8:
        Xtr, ytr = matrix(tr)
        Xte, yte = matrix(te)
        mu, sg = Xtr.mean(0), Xtr.std(0)
        sg[sg == 0] = 1.0
        Xtr = (Xtr - mu) / sg
        Xte = (Xte - mu) / sg            # TRAIN statistics only
        lam = 10.0
        w = np.linalg.solve(Xtr.T @ Xtr + lam * np.eye(Xtr.shape[1]), Xtr.T @ ytr)
        pred = Xte @ w
        combined_ic = spearman(list(pred), list(yte))
        print()
        print(f"  COMBINED ridge — train {len(tr)} sessions, HELD-OUT {len(te)}: "
              f"test IC {combined_ic:+.4f}")

    print()
    print("  BAR DECLARED BEFORE THE RUN:")
    print(f"    (1) a feature with |IC|>={IC_BAR} and |t|>={T_BAR}: "
          f"{'PASS' if passers else 'FAIL'}  ({len(passers)} of {len(names)})")
    print(f"    (2) that feature sign-stable across halves:  "
          f"{'PASS' if stable_passers else 'FAIL'}")
    print(f"    (3) combined model positive on held-out:     "
          f"{'PASS' if combined_ic > 0 else 'FAIL'}  ({combined_ic:+.4f})")
    print()
    ok = bool(stable_passers) and combined_ic > 0
    print(f"  VERDICT: {'PASSES - worth pursuing' if ok else 'FAILS — the panel is flat'}")
    if not ok:
        print()
        print("  A flat 25-feature panel spanning BOTH price and options settles the")
        print("  'we only tried three indicators' objection: the limit is the input,")
        print("  not the indicator choice.")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    sys.exit(main())
