#!/usr/bin/env python3
"""
Volatility Forecast Backtest — can a model beat IV at predicting realised move?

WHY THIS, AND NOT A DIRECTION MODEL
Nine hypotheses tested on this data returned null, all of them directional.
Two things did survive every control, and both are volatility statements:
dealer gamma predicts next-day move MAGNITUDE (SPY 0.53% at high gamma vs
0.87% at low, t+2.9, surviving a trailing-vol control), and index VRP is real
(SPY +2.34 vol points, t+3.1).

Direction is unforecastable here; magnitude is not. Realised volatility
clusters and mean-reverts, which is why vol forecasting has worked for decades
where return forecasting has not. So the target is |return|, not return.

A model is only trained after this backtest says the target is learnable. The
last RL model on this project reported Sharpe 2.94, was auto-deployed, and was
then disabled in bot.py as "broken" — trained first, validated never.

THE BENCHMARK IS IMPLIED VOL, NOT TRAILING VOL
Beating "tomorrow looks like today" is easy: volatility is autocorrelated, so a
trailing estimate is already decent. It is also worthless as an edge, because
the OPTION MARKET already publishes a forecast — implied vol — and that is the
number you trade against. A model that beats trailing RV but not IV tells you
nothing you can act on.

So three forecasts are compared on identical out-of-sample data:

    trailing RV    20-day realised vol, scaled to the horizon
    IMPLIED        the market's own forecast (implied_move_perc_7)
    model          ridge regression on vol + options + flow features

The model has to beat IMPLIED to matter. Beating only trailing RV is a null
result dressed up.

NO LOOK-AHEAD
Features are day D's end-of-day values; the target is the move from D's close
to D+h's close. Everything used is known when D closes. iv30d for day D is
that day's CLOSING implied vol, which is exactly what is available at that
moment — this is why the target starts at D's close rather than D's open.

METHOD NOTES
  target is log|move| — vol is roughly lognormal, and a raw target lets a few
    crisis days dominate the fit
  features standardised on TRAIN statistics only, then applied to test; using
    full-sample statistics leaks test information into training
  ridge, not OLS — the features are heavily collinear (iv30d, volatility,
    volatility_7 and volatility_30 all measure the same thing)
  time-split, never shuffled: shuffling a time series lets the model see the
    future through neighbouring days
  Spearman as the headline, since what matters for sizing is the RANKING of
    expected moves, not the absolute level
"""

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

BASE = "https://api.unusualwhales.com/api"
CACHE = "vol_forecast_panel.json"
HORIZON = 3          # trading days ahead
TRAIN_FRAC = 0.6     # first 60% of sessions train, last 40% test

FEATURES = [
    "iv30d", "iv_rank", "realized_volatility", "volatility_7", "volatility_30",
    "implied_move_perc_7", "gex_ratio", "relative_volume",
    "trail_rv", "today_move", "hl_range", "pc_ratio", "logoi",
]


def _f(v, d=None):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


class VolForecast:
    def __init__(self):
        import requests
        self.s = requests.Session()
        key = os.getenv("UW_API_KEY")
        if key:
            self.s.headers.update({"Authorization": f"Bearer {key}",
                                   "Accept": "application/json"})
        self.stats = defaultdict(int)

    def screener(self, day: str, limit: int) -> List[Dict]:
        try:
            r = self.s.get(f"{BASE}/screener/stocks",
                           params={"date": day, "limit": limit}, timeout=30)
            rows = r.json().get("data", []) if r.status_code == 200 else []
        except Exception:
            return []
        if not rows:
            return []
        if str(rows[0].get("date") or "")[:10] != day:
            self.stats["date_mismatch"] += 1
            return []
        self.stats["days_ok"] += 1
        return rows

    def collect(self, days_back: int, limit: int) -> Dict:
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
                cv, pv = _f(r.get("call_volume"), 0.0), _f(r.get("put_volume"), 0.0)
                oi = _f(r.get("total_open_interest"), 0.0) or 0.0
                hi, lo = _f(r.get("high"), c), _f(r.get("low"), c)
                pc = _f(r.get("prev_close"), c) or c
                rec[t] = {
                    "close": c,
                    "iv30d": _f(r.get("iv30d")),
                    "iv_rank": _f(r.get("iv_rank")),
                    "realized_volatility": _f(r.get("realized_volatility")),
                    "volatility_7": _f(r.get("volatility_7")),
                    "volatility_30": _f(r.get("volatility_30")),
                    "implied_move_perc_7": _f(r.get("implied_move_perc_7")),
                    "gex_ratio": _f(r.get("gex_ratio")),
                    "relative_volume": _f(r.get("relative_volume")),
                    "today_move": abs(c / pc - 1.0) * 100 if pc else None,
                    "hl_range": (hi - lo) / c * 100 if c else None,
                    "pc_ratio": (pv / (cv + pv)) if (cv + pv) > 0 else None,
                    "logoi": math.log1p(oi),
                }
            if rec:
                panel[day] = rec
            if n % 30 == 0:
                print(f"  {n}/{len(days)} days ... {len(panel)} usable")
        return panel

    # ------------------------------------------------------------- assembly

    @staticmethod
    def build_matrix(panel: Dict) -> Tuple[np.ndarray, np.ndarray, List[str], np.ndarray]:
        """
        Rows are (day, ticker). Returns X, y, day-labels and the IMPLIED
        benchmark forecast aligned to the same rows.
        """
        days = sorted(panel)
        idx = {d: i for i, d in enumerate(days)}
        hist: Dict[str, List[float]] = defaultdict(list)

        X, y, lab, imp = [], [], [], []
        for i, d in enumerate(days):
            for t, r in panel[d].items():
                hist[t].append(r["close"])

            if i + HORIZON >= len(days):
                continue
            fwd = days[i + HORIZON]
            for t, r in panel[d].items():
                nxt = panel.get(fwd, {}).get(t)
                if not nxt:
                    continue
                c0, c1 = r["close"], nxt["close"]
                move = abs(c1 / c0 - 1.0) * 100
                if move <= 0 or move > 50:          # split / corporate action
                    continue

                closes = hist[t]
                if len(closes) < 21:
                    continue
                rets = np.diff(np.log(closes[-21:]))
                trail = float(np.std(rets)) * 100 * math.sqrt(HORIZON)
                if not np.isfinite(trail) or trail <= 0:
                    continue

                row, ok = [], True
                for f in FEATURES:
                    v = trail if f == "trail_rv" else r.get(f)
                    if v is None or not np.isfinite(float(v)):
                        ok = False
                        break
                    row.append(float(v))
                if not ok:
                    continue

                # IMPLIED benchmark: the market's 7-day expected move, scaled
                # to this horizon. This is the number the model must beat.
                iv7 = r.get("implied_move_perc_7")
                if iv7 is None or iv7 <= 0:
                    continue
                implied = float(iv7) * 100 * math.sqrt(HORIZON / 5.0)

                X.append(row)
                y.append(move)
                lab.append(d)
                imp.append(implied)
        return (np.array(X, dtype=float), np.array(y, dtype=float),
                lab, np.array(imp, dtype=float))


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3:
        return 0.0
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    den = math.sqrt(float((ra ** 2).sum()) * float((rb ** 2).sum()))
    return float((ra * rb).sum() / den) if den else 0.0


def ridge_fit(X: np.ndarray, y: np.ndarray, lam: float = 10.0) -> np.ndarray:
    Xb = np.hstack([X, np.ones((len(X), 1))])
    A = Xb.T @ Xb + lam * np.eye(Xb.shape[1])
    A[-1, -1] -= lam                      # do not penalise the intercept
    return np.linalg.solve(A, Xb.T @ y)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=200)
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()

    vf = VolForecast()
    if a.reuse and os.path.exists(CACHE):
        panel = json.load(open(CACHE))
        print(f"cached panel: {len(panel)} sessions\n")
    else:
        print(f"collecting {a.days} sessions x top {a.limit} ...\n")
        panel = vf.collect(a.days, a.limit)
        json.dump(panel, open(CACHE, "w"))
    if len(panel) < 40:
        print("insufficient data")
        return 1

    X, y, lab, imp = vf.build_matrix(panel)
    if len(y) < 500:
        print(f"insufficient rows ({len(y)})")
        return 1

    days = sorted(set(lab))
    cut = days[int(len(days) * TRAIN_FRAC)]
    tr = np.array([d < cut for d in lab])
    te = ~tr

    # Standardise on TRAIN statistics only — using full-sample statistics would
    # leak test information into the fit.
    mu, sd = X[tr].mean(axis=0), X[tr].std(axis=0)
    sd[sd == 0] = 1.0
    Xs = (X - mu) / sd

    # log target: vol is roughly lognormal, and a raw target lets a handful of
    # crisis days dominate the least-squares fit.
    w = ridge_fit(Xs[tr], np.log(y[tr]))
    raw = np.hstack([Xs, np.ones((len(Xs), 1))]) @ w
    # exp() of an unclipped linear score explodes on test outliers: the first
    # run produced a test MAE of 2,491 against 3.27 for implied, while its RANK
    # correlation was fine. The ordering is usable, the level is not — clip so
    # the level is at least reportable, and say so rather than hiding it.
    pred = np.exp(np.clip(raw, np.log(0.05), np.log(60.0)))

    trail = X[:, FEATURES.index("trail_rv")]

    print("=" * 88)
    print("VOLATILITY FORECAST — can a model beat IMPLIED at predicting realised move?")
    print("=" * 88)
    print(f"  {len(y):,} observations | {len(days)} sessions | horizon {HORIZON}d")
    print(f"  train {days[0]} .. {cut}   |   test {cut} .. {days[-1]}")
    print(f"  train rows {int(tr.sum()):,}  test rows {int(te.sum()):,}")
    print()
    print("  Spearman = rank correlation with the realised move. That is what")
    print("  matters for sizing: getting the ORDER right, not the level.")
    print()
    print(f"  {'forecast':<22}{'train rho':>12}{'TEST rho':>12}{'test MAE':>12}")
    print("  " + "-" * 58)
    for name, f in (("trailing RV", trail), ("IMPLIED (benchmark)", imp),
                    ("model (ridge)", pred)):
        mae = float(np.mean(np.abs(f[te] - y[te])))
        print(f"  {name:<22}{spearman(f[tr], y[tr]):>12.3f}"
              f"{spearman(f[te], y[te]):>12.3f}{mae:>14.2f}")
    print("  " + "-" * 58)

    m_rho = spearman(pred[te], y[te])
    i_rho = spearman(imp[te], y[te])
    t_rho = spearman(trail[te], y[te])
    print()
    print("  VERDICT")
    print(f"    model vs IMPLIED  : {m_rho:+.3f} vs {i_rho:+.3f}  "
          f"({'model wins' if m_rho > i_rho else 'IMPLIED wins'})")
    print(f"    model vs trailing : {m_rho:+.3f} vs {t_rho:+.3f}  "
          f"({'model wins' if m_rho > t_rho else 'trailing wins'})")
    print()
    if m_rho > i_rho + 0.02:
        print("    -> Model beats the market's own forecast out-of-sample.")
        print("       Worth wiring into sizing and barrier placement.")
    elif m_rho > t_rho:
        print("    -> Beats trailing RV but NOT implied. That is a null dressed up:")
        print("       the option market already prices what the model knows, so")
        print("       there is nothing here to trade against.")
    else:
        print("    -> Beats neither benchmark. Do not build on this.")

    # Which features carry the fit — collinearity means read these as a group.
    order = np.argsort(-np.abs(w[:-1]))
    print()
    print("  strongest standardised coefficients (collinear — read as a group):")
    for i in order[:6]:
        print(f"    {FEATURES[i]:<24}{w[i]:>+8.3f}")
    print()
    print("=" * 88)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
