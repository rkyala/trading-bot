#!/usr/bin/env python3
"""
0DTE Iron Condor Backtest — priced from REAL historical option prices.

THE HYPOTHESIS
When dealer gamma is high, market makers hedge against moves, compressing
realised volatility and pinning price near heavy open-interest strikes. Selling
a short-dated iron condor with short strikes placed beyond the gamma walls
should then harvest theta with the walls acting as structural barriers.

WHY THIS IS BUILT FROM CHAIN PRICES, NOT AN ASSUMED CREDIT
A proposed version of this backtest set

    est_credit = spread_width * 0.35

which makes the entire P&L a deterministic function of that constant: 0.35
prints a profit, 0.20 prints a loss, and nothing about the market enters the
calculation. That is a simulation of an assumption.

Here every leg is priced from its actual historical option `open`, and the
position settles against the underlying's actual close. The only assumption
left is per-leg friction, which is a PARAMETER reported across a sensitivity
table so its contribution is visible rather than hidden.

WHAT IS ALREADY KNOWN, AND WHY THIS IS STILL WORTH RUNNING
uw_vol_backtest.py already tested GEX-timed vol selling and found nothing:
the high-minus-low gamma spread was +0.077 (SPY), +0.080 (QQQ), +0.099 (IWM),
-0.077 (DIA), all |t| < 1. The reason is visible in the data — implied vol
falls in lockstep with gamma (SPY implied 0.945% -> 0.683% as actual fell
0.865% -> 0.527%), so the market already prices the effect.

What is genuinely untested is the STRUCTURAL element: placing shorts beyond
the gamma walls rather than at a fixed delta. That is the only reason to run
this, and it is why walls-based selection is compared head-to-head against a
conventional delta-based condor on the same days.

An early observation that may decide it: on 2026-06-10 SPY closed 725.43 with
call_wall 726 and put_wall 723 — a 0.4% corridor. Walls sit far closer to spot
than a conventional condor's shorts, so breaches may be frequent. Measured, not
assumed.

MECHANICS
  entry      short put + short call sold at their option `open`
             long wings bought at their `open`
  settle     intrinsic against the underlying's actual close (0DTE, so expiry
             and trade date are the same session)
  P&L        credit - put_spread_loss - call_spread_loss - 4 * friction
  contract   x100 multiplier, 1 contract per trade

GUARDS
  every returned date verified against the date requested
  all four legs must exist with a real price > 0, else the day is skipped
  spread losses capped at wing width (a spread cannot lose more than its width)
  gamma regime from a ROLLING percentile, so no forward information
  friction sensitivity table so the assumption's weight is explicit

FRICTION IS MEASURED, NOT GUESSED (corrected 2026-09-09)
The first run of this file assumed $0.05/leg and concluded the condor loses
-$18.60/trade because "friction is the moat". That assumption was 10x too
pessimistic and the conclusion was wrong in character.

Effective spread was then measured from real executions: within each 1-minute
bar, ask-side average price minus bid-side average price, using
/option-contract/{id}/intraday?date= which carries premium_ask_side and
premium_bid_side per bar. Comparing DAY-LONG aggregates does not work — three
of eight contracts showed a NEGATIVE spread because intraday drift swamps it.
Within a single bar drift is negligible.

    SPY 0DTE, 3,096 bars across 8 contracts:
      median spread     $0.010  (2.3% of mid)
      one-way per leg   $0.005
      negative bars     12%  (residual noise around a penny-wide market)

At the measured $0.005/leg the symmetric condor returns -$0.60/trade,
t-0.11 — statistically indistinguishable from ZERO, not a loss. The trade is
fairly priced; costs merely tip it just under. That is a sharper finding than
"costs destroy it", and it only appeared because the assumption was checked.

Default friction is therefore 0.005, and the sensitivity table still spans
$0.00-$0.15 so a different instrument's spread can be read off directly.
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

BASE = "https://api.unusualwhales.com/api"
CACHE = "condor_panel.json"
MULT = 100.0


def _f(v, d=None):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


class CondorBacktest:
    def __init__(self, ticker: str = "SPY", max_skew: float = 3.0,
                 min_dte: int = 0, max_dte: int = 0):
        import requests
        self.max_skew = max_skew
        self.min_dte, self.max_dte = min_dte, max_dte
        self._barcache: Dict[str, Optional[Dict]] = {}
        self.t = ticker.upper()
        self.s = requests.Session()
        key = os.getenv("UW_API_KEY")
        if key:
            self.s.headers.update({"Authorization": f"Bearer {key}",
                                   "Accept": "application/json"})
        self.stats = defaultdict(int)

    # ------------------------------------------------------------------ data

    def bar(self, day: str) -> Optional[Dict]:
        """
        One session's OHLC, fetched per-day and cached.

        The bulk /ohlc/1d fetch is capped at 756 rows = 252 REGULAR sessions =
        exactly one year, which silently limited the sample. /ohlc/1d?date=
        returns that specific session and works at least 730 days back, so the
        window is bounded by the option chain (~2 years) rather than by bars.
        """
        if day in self._barcache:
            return self._barcache[day]
        out = None
        try:
            d = self.s.get(f"{BASE}/stock/{self.t}/ohlc/1d",
                           params={"date": day, "limit": 10}, timeout=25
                           ).json().get("data", [])
        except Exception:
            d = []
        for b in d or []:
            if b.get("market_time") not in (None, "r"):
                continue
            if str(b.get("date") or b.get("start_time"))[:10] != day:
                continue          # the endpoint can return adjacent sessions
            o, c = _f(b.get("open")), _f(b.get("close"))
            if o and c and o > 0:
                out = {"open": o, "high": _f(b.get("high"), c),
                       "low": _f(b.get("low"), c), "close": c}
                break
        self._barcache[day] = out
        return out

    def walls(self, day: str) -> Optional[Dict]:
        try:
            r = self.s.get(f"{BASE}/stock/{self.t}/gex-levels",
                           params={"date": day}, timeout=25)
            d = r.json().get("data", {}) if r.status_code == 200 else {}
        except Exception:
            return None
        if not d or str(d.get("date"))[:10] != day:
            self.stats["wall_date_mismatch"] += 1
            return None
        cw, pw = _f(d.get("call_wall")), _f(d.get("put_wall"))
        if not cw or not pw:
            return None
        return {"call_wall": cw, "put_wall": pw,
                "flip": _f(d.get("gamma_flip")), "magnet": _f(d.get("gamma_magnet"))}

    def gamma(self, day: str) -> Optional[float]:
        try:
            r = self.s.get(f"{BASE}/stock/{self.t}/greek-exposure",
                           params={"date": day}, timeout=25)
            rows = r.json().get("data", []) if r.status_code == 200 else []
        except Exception:
            return None
        for g in rows or []:
            if str(g.get("date"))[:10] == day:
                cg, pg = _f(g.get("call_gamma")), _f(g.get("put_gamma"))
                if cg is not None and pg is not None:
                    return cg + pg
        return None

    def chain_dte(self, day: str, min_dte: int = 0, max_dte: int = 0) -> List[Dict]:
        """
        Priced contracts whose expiry falls in [min_dte, max_dte] days from
        `day`. min=max=0 is the 0DTE chain.

        The server has no exact-DTE filter (min_dte=0&max_dte=0 returns
        nothing, max_dte=0 alone returns mixed expiries), so the window is
        applied here against the returned expiry.
        """
        try:
            r = self.s.get(f"{BASE}/screener/option-contracts",
                           params={"date": day, "ticker_symbol": self.t,
                                   "limit": 500}, timeout=30)
            rows = r.json().get("data", []) if r.status_code == 200 else []
        except Exception:
            return []
        out = []
        for x in rows or []:
            exp = str(x.get("expiry"))[:10]
            try:
                dte = (date.fromisoformat(exp) - date.fromisoformat(day)).days
            except Exception:
                continue
            if not (min_dte <= dte <= max_dte):
                continue
            k, op = _f(x.get("strike")), _f(x.get("open"))
            typ = str(x.get("option_type") or "").lower()
            if not k or op is None or op <= 0 or typ not in ("call", "put"):
                continue
            out.append({"strike": k, "type": typ, "open": op, "expiry": exp,
                        "close": _f(x.get("close")), "delta": _f(x.get("delta"))})
        return out

    def collect(self, days_back: int) -> Dict:
        today = date.today()
        days, i = [], 1
        while len(days) < days_back and i < days_back * 2 + 60:
            d = today - timedelta(days=i)
            if d.weekday() < 5:
                days.append(d.isoformat())
            i += 1
        days.sort()

        panel = {}
        skip_until = None
        for n, day in enumerate(days, 1):
            # NON-OVERLAPPING HOLDS. A weekly entered every session would hold
            # 3-5 overlapping positions at once, so t-stats computed on them
            # would be inflated by roughly sqrt(hold). Entering only once the
            # previous position has expired makes each trade independent.
            if skip_until and day <= skip_until:
                continue
            bar = self.bar(day)
            if not bar:
                continue                      # holiday or missing session
            ch = self.chain_dte(day, self.min_dte, self.max_dte)
            if len(ch) < 8:
                self.stats["no_0dte_chain"] += 1
                continue
            w = self.walls(day)
            if not w:
                self.stats["no_walls"] += 1
                continue
            exp = min(c["expiry"] for c in ch)
            ebar = self.bar(exp)
            if not ebar:
                self.stats["no_expiry_bar"] += 1
                continue
            panel[day] = {"bar": bar, "chain": [c for c in ch if c["expiry"] == exp],
                          "walls": w, "gamma": self.gamma(day),
                          "expiry": exp, "expiry_bar": ebar}
            skip_until = exp
            self.stats["days_ok"] += 1
            if n % 20 == 0:
                print(f"  {n}/{len(days)} days ... {len(panel)} usable")
        return panel

    # ----------------------------------------------------------- strategy

    @staticmethod
    def _leg(chain: List[Dict], typ: str, strike: float) -> Optional[Dict]:
        for c in chain:
            if c["type"] == typ and abs(c["strike"] - strike) < 1e-9:
                return c
        return None

    @staticmethod
    def _nearest(chain: List[Dict], typ: str, target: float,
                 above: bool) -> Optional[Dict]:
        """Nearest listed strike at/above (or at/below) target."""
        cands = [c for c in chain if c["type"] == typ and
                 (c["strike"] >= target if above else c["strike"] <= target)]
        if not cands:
            return None
        return min(cands, key=lambda c: abs(c["strike"] - target))

    @staticmethod
    def _by_delta(chain: List[Dict], typ: str, target_abs: float) -> Optional[Dict]:
        cands = [c for c in chain if c["type"] == typ and c["delta"] is not None]
        if not cands:
            return None
        return min(cands, key=lambda c: abs(abs(c["delta"]) - target_abs))

    def build(self, day: str, rec: Dict, mode: str, width: float,
              otm_pct: float) -> Optional[Dict]:
        """
        Select four legs. mode: 'walls' or 'otm'.

        TWO CORRECTNESS RULES, both learned from a first version that printed
        Sharpe 33 and a 97% win rate:

        1. SHORTS MUST STRADDLE THE ENTRY PRICE. GEX walls are NOT symmetric
           around spot and frequently sit both above or both below it. On
           2026-09-03 SPY opened 767.90 with call_wall 773 and put_wall 772 —
           both above spot — so placing shorts at the walls sold a DEEP
           IN-THE-MONEY put. That is a leveraged directional long, not a
           condor. It collected ~$1.44 credit against $2 wings (72% of width,
           which no genuine OTM condor ever pays) and made money purely
           because the sample was a rising tape. Clamping the shorts to the
           OTM side of spot is what makes the structure an actual condor.

        2. STRIKES ARE NEVER CHOSEN BY DELTA. The chain's delta is the
           END-OF-DAY value: on that same day, calls struck 762-772 report
           delta 0.88-0.98, impossible with spot at 767.90 but correct against
           the 773.17 close. Selecting on it is look-ahead. The baseline mode
           therefore uses distance from the entry price, which is knowable at
           entry.
        """
        ch, w = rec["chain"], rec["walls"]
        spot = rec["bar"]["open"]
        if mode == "walls":
            # Clamp to the OTM side of spot so the result is a real condor.
            sc = self._nearest(ch, "call", max(w["call_wall"], spot), above=True)
            sp = self._nearest(ch, "put", min(w["put_wall"], spot), above=False)
        else:
            sc = self._nearest(ch, "call", spot * (1.0 + otm_pct), above=True)
            sp = self._nearest(ch, "put", spot * (1.0 - otm_pct), above=False)
        if not sc or not sp or sp["strike"] >= sc["strike"]:
            return None
        # Both shorts must be out of the money at entry.
        if sc["strike"] < spot or sp["strike"] > spot:
            self.stats["shorts_not_otm"] += 1
            return None
        # SYMMETRY GUARD. GEX walls are not symmetric about spot, so placing
        # shorts at them produces lopsided structures — one short worthless
        # far OTM, the other near the money. On 2026-03-27 that was SP 615
        # against SC 643 with spot 642.50: a near-ATM call credit spread with
        # a decorative put, i.e. a DIRECTIONAL bet, not a condor. Across a
        # sample where SPY rose 14.7% such a structure prints money for
        # reasons that have nothing to do with gamma pinning. Requiring the
        # two sides to be within max_skew of each other forces the position
        # to actually be the delta-neutral trade the thesis claims to test.
        up = (sc["strike"] - spot) / spot
        dn = (spot - sp["strike"]) / spot
        if max(up, dn) > self.max_skew * max(min(up, dn), 1e-9):
            self.stats["too_asymmetric"] += 1
            return None
        lc = self._nearest(ch, "call", sc["strike"] + width, above=True)
        lp = self._nearest(ch, "put", sp["strike"] - width, above=False)
        if not lc or not lp:
            return None
        if lc["strike"] <= sc["strike"] or lp["strike"] >= sp["strike"]:
            return None
        return {"sc": sc, "lc": lc, "sp": sp, "lp": lp}

    def settle(self, legs: Dict, close: float, friction: float) -> Dict:
        credit = (legs["sc"]["open"] + legs["sp"]["open"]
                  - legs["lc"]["open"] - legs["lp"]["open"])
        cw = legs["lc"]["strike"] - legs["sc"]["strike"]
        pw = legs["sp"]["strike"] - legs["lp"]["strike"]
        call_loss = min(max(0.0, close - legs["sc"]["strike"]), cw)
        put_loss = min(max(0.0, legs["sp"]["strike"] - close), pw)
        pnl = credit - call_loss - put_loss - 4.0 * friction
        return {"credit": credit, "call_loss": call_loss, "put_loss": put_loss,
                "pnl": pnl, "max_width": max(cw, pw),
                "breached": (call_loss > 0 or put_loss > 0)}

    def run(self, panel: Dict, mode: str, width: float, friction: float,
            otm_pct: float, gamma_pct: Optional[float]) -> Dict:
        days = sorted(panel)
        gam = [panel[d].get("gamma") for d in days]

        trades = []
        for i, day in enumerate(days):
            rec = panel[day]
            # Rolling gamma percentile — no forward information.
            if gamma_pct is not None:
                hist = [g for g in gam[max(0, i - 20):i] if g is not None]
                g = rec.get("gamma")
                if g is None or len(hist) < 5:
                    self.stats["no_gamma"] += 1
                    continue
                thresh = sorted(hist)[int(len(hist) * gamma_pct)]
                if g <= thresh:
                    self.stats["low_gamma_skip"] += 1
                    continue
            legs = self.build(day, rec, mode, width, otm_pct)
            if not legs:
                self.stats["no_legs"] += 1
                continue
            r = self.settle(legs, rec["expiry_bar"]["close"], friction)
            if r["credit"] <= 0:
                self.stats["no_credit"] += 1
                continue
            # A legitimate OTM condor collects a fraction of its width. Credit
            # at or above the width means a leg is mispriced or in-the-money,
            # and would show up as free money. Reject rather than bank it.
            if r["credit"] >= r["max_width"] * 0.90:
                self.stats["implausible_credit"] += 1
                continue
            r["date"] = day
            trades.append(r)
        return {"trades": trades, "stats": dict(self.stats)}


def summarise(trades: List[Dict]) -> Optional[Dict]:
    """
    Sharpe is annualised by TRADES PER YEAR, not sqrt(252).

    sqrt(252) is only correct when one trade is one trading day, which holds
    for 0DTE and not for weeklies. A 3-7 day hold produces ~50 trades a year,
    so sqrt(252) overstates Sharpe by about 2.2x — it silently made a weekly
    result look like a daily one.
    """
    if len(trades) < 10:
        return None
    p = [t["pnl"] * MULT for t in trades]
    n = len(p)
    try:
        ds = sorted(t["date"] for t in trades)
        span_yrs = max((date.fromisoformat(ds[-1]) - date.fromisoformat(ds[0])).days, 1) / 365.0
        per_year = n / max(span_yrs, 1e-9)
    except Exception:
        per_year = 252.0
    m = st.mean(p)
    sd = st.pstdev(p)
    t = m / (sd / math.sqrt(n)) if sd > 0 else 0.0
    wins = [x for x in p if x > 0]
    return {"n": n, "mean": m, "t": t, "total": sum(p),
            "win": len(wins) / n * 100,
            "breach": sum(1 for x in trades if x["breached"]) / n * 100,
            "worst": min(p), "best": max(p),
            "credit": st.mean([x["credit"] for x in trades]) * MULT,
            "sharpe": (m / sd * math.sqrt(per_year)) if sd > 0 else 0.0,
            "per_year": per_year}


def _line(label: str, s: Optional[Dict]) -> str:
    if not s:
        return f"  {label:<22}{'too few trades':>58}"
    return (f"  {label:<22}{s['n']:>6}{s['mean']:>+10.2f}{s['t']:>8.1f}"
            f"{s['win']:>8.1f}%{s['breach']:>9.1f}%{s['total']:>+11.0f}"
            f"{s['sharpe']:>8.2f}")


def render(bt: CondorBacktest, panel: Dict, args) -> None:
    print("=" * 104)
    print(f"0DTE IRON CONDOR BACKTEST — {bt.t}, priced from real option opens")
    print("=" * 104)
    ds = sorted(panel)
    print(f"  usable sessions {len(panel)}  {ds[0]} .. {ds[-1]}   "
          f"wing width ${args.width:.0f}   1 contract")
    print()
    print("  Entry: shorts sold and wings bought at each leg's actual option OPEN.")
    print("  Settle: intrinsic against the underlying's actual CLOSE. P&L in $/contract.")
    print()
    hdr = (f"  {'strategy':<22}{'n':>6}{'mean $':>10}{'t':>8}{'win%':>9}"
           f"{'breach%':>9}{'total $':>11}{'sharpe':>8}")
    print(hdr)
    print("  " + "-" * 100)

    variants = [
        ("walls, all days", "walls", None),
        ("walls, high gamma", "walls", args.gamma_pct),
        (f"{args.otm_pct*100:.2f}% OTM, all days", "otm", None),
        (f"{args.otm_pct*100:.2f}% OTM, high gamma", "otm", args.gamma_pct),
    ]
    keep = {}
    for label, mode, gp in variants:
        bt.stats = defaultdict(int)
        out = bt.run(panel, mode, args.width, args.friction, args.otm_pct, gp)
        s = summarise(out["trades"])
        keep[label] = out["trades"]
        print(_line(label, s))
    print("  " + "-" * 100)

    # ---- the assumption's weight, made explicit -------------------------
    print()
    print(f"  FRICTION SENSITIVITY — per leg, 4 legs per trade. Base = ${args.friction:.2f}")
    print(f"  {'friction/leg':<22}{'walls mean $':>16}{'otm mean $':>16}"
          f"{'walls total':>14}{'otm total':>14}")
    print("  " + "-" * 82)
    for fr in (0.000, 0.005, 0.010, 0.025, 0.050):
        row = []
        for mode in ("walls", "otm"):
            bt.stats = defaultdict(int)
            o = bt.run(panel, mode, args.width, fr, args.otm_pct, None)
            s = summarise(o["trades"])
            row.append(s)
        w, d = row
        print(f"  ${fr:<21.2f}{(w['mean'] if w else 0):>+16.2f}"
              f"{(d['mean'] if d else 0):>+16.2f}"
              f"{(w['total'] if w else 0):>+14.0f}{(d['total'] if d else 0):>+14.0f}")

    # ---- tail ----------------------------------------------------------
    # Report the tail of the SYMMETRIC variant, not walls. Hardcoding "walls"
    # printed a median of -$24 next to a 73.5% win rate, because those numbers
    # came from two different strategies.
    otm_key = next((k for k in keep if "OTM, all days" in k), None)
    wt = (keep.get(otm_key) if otm_key else None) or keep.get("walls, all days") or []
    if wt:
        print(f"  (tail below is for: {otm_key or 'walls, all days'})")
        p = sorted(t["pnl"] * MULT for t in wt)
        n = len(p)
        avg_credit = st.mean([t["credit"] for t in wt]) * MULT
        print()
        print("  TAIL — a defined-risk condor still loses many multiples of its credit")
        print(f"    worst {p[0]:+,.0f} | p5 {p[max(n//20,0)]:+,.0f} | "
              f"median {p[n//2]:+,.0f} | best {p[-1]:+,.0f}")
        print(f"    average credit collected {avg_credit:+,.0f}; "
              f"the worst day costs {abs(p[0])/avg_credit:.1f} credits")

    print()
    print("=" * 104)
    print("  A strategy only clears if mean $ stays positive at realistic friction.")
    print("  Compare walls vs delta on the SAME days: that difference is the only")
    print("  thing the gamma-wall thesis adds beyond a conventional condor, and")
    print("  GEX-timed vol selling already measured null (uw_vol_backtest.py).")
    print("=" * 104)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="SPY")
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--width", type=float, default=2.0, help="wing width $")
    ap.add_argument("--friction", type=float, default=0.005,
                    help="$ per leg; SPY 0DTE measured at $0.005 (see docstring)")
    ap.add_argument("--otm-pct", type=float, default=0.003,
                    help="baseline short strike distance from spot, e.g. 0.003 = 0.3%%")
    ap.add_argument("--gamma-pct", type=float, default=0.75)
    ap.add_argument("--min-dte", type=int, default=0)
    ap.add_argument("--max-dte", type=int, default=0)
    ap.add_argument("--max-skew", type=float, default=3.0,
                    help="max ratio between the two shorts' distance from spot")
    ap.add_argument("--cache", action="store_true")
    a = ap.parse_args()

    bt = CondorBacktest(a.ticker, a.max_skew, a.min_dte, a.max_dte)
    cache = f"{a.ticker.lower()}_{a.min_dte}_{a.max_dte}_{CACHE}"
    if a.cache and os.path.exists(cache):
        panel = json.load(open(cache))
        print(f"cached panel: {len(panel)} sessions\n")
    else:
        print(f"collecting {a.days} sessions of {a.ticker} 0DTE chains...\n")
        panel = bt.collect(a.days)
        json.dump(panel, open(cache, "w"))
    if not panel:
        print("no usable sessions")
        return 1
    render(bt, panel, a)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
