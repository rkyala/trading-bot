#!/usr/bin/env python3
"""
Fundamentals card — real financial statements, from UW.

WHY THIS EXISTS SEPARATELY FROM fundamental_alerts.py
That file is named "fundamental" but reads ONLY a price history DataFrame:
"valuation" is distance from the 52-week high and the SMAs, "growth" is 1y/6m
price return, "quality" is a 50/200 SMA cross plus volume, "momentum" is
RSI(14). It is a technical pullback screener. Nothing in it has ever touched a
financial statement.

This one does: /stock/{t}/financials returns 103 quarterly periods of income
statements, balance sheets and cash flows, plus 156 earnings with the actual
surprise attached.

WHAT IT IS FOR
Context a human reads before deciding. NOT trade logic, and deliberately not
scored into a single number — a composite score invites being traded, and
nothing here has been shown to predict returns at this bot's horizon.
Fundamentals update four times a year; the bot holds three days. Those two
facts do not meet.

The honest use is as a VETO or a sanity check: is this a business that is
losing money, drowning in debt, or burning cash? That question needs no edge
to be worth asking.

SOURCES (all verified historical on this plan)
  /stock/{t}/financials              income, balance sheet, cash flow, earnings
  /stock/{t}/ohlc/1d                 drawdown from the 52-week high
  /insider/{t}/ticker-flow           discretionary insider flow (10b5-1 split)
  /institution/{t}/ownership         13F holders
  /screener/stocks                   IV, IV rank, options volume context
"""

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

BASE = "https://api.unusualwhales.com/api"


def _f(v, d=None):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


def _money(v: Optional[float]) -> str:
    if v is None:
        return "—"
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{'-' if v < 0 else ''}${a/div:,.2f}{suf}"
    return f"{'-' if v < 0 else ''}${a:,.0f}"


class Card:
    def __init__(self):
        import requests
        self.s = requests.Session()
        key = os.getenv("UW_API_KEY")
        if key:
            self.s.headers.update({"Authorization": f"Bearer {key}",
                                   "Accept": "application/json"})

    # PER-TICKER CACHE.
    #
    # qualifies() calls annual_trend, then valuation — and valuation calls
    # annual_trend AGAIN and re-fetches /financials on top. So the same 431KB
    # payload was pulled THREE times per ticker. Across a 200-name universe
    # that is 400 wasted calls and the scan took minutes, which matters when it
    # runs three times a session.
    _cache: Dict[str, object] = {}

    def get(self, path: str, params: Optional[Dict] = None):
        try:
            r = self.s.get(f"{BASE}{path}", params=params or {}, timeout=25)
            return r.json().get("data") if r.status_code == 200 else None
        except Exception:
            return None

    # ------------------------------------------------------------ sections

    def _financials_raw(self, t: str) -> Dict:
        """Cached /financials — the payload is large and wanted three times."""
        k = f"fin:{t}"
        if k not in self._cache:
            d = self.get(f"/stock/{t}/financials") or {}
            if isinstance(d, list):
                d = d[0] if d else {}
            self._cache[k] = d
        return self._cache[k] or {}

    def financials(self, t: str) -> Dict:
        d = self._financials_raw(t)
        if isinstance(d, list):
            d = d[0] if d else {}

        def newest(rows, n=1):
            # Statements arrive with the most recent period first on this API.
            rows = [r for r in (rows or []) if r.get("fiscal_date_ending")]
            rows.sort(key=lambda r: str(r["fiscal_date_ending"]), reverse=True)
            return rows[:n]

        inc = newest(d.get("income_statements"), 8)
        bal = newest(d.get("balance_sheets"), 1)
        cfs = newest(d.get("cash_flows"), 8)
        ern = [r for r in (d.get("earnings") or []) if r.get("reported_eps")]
        ern.sort(key=lambda r: str(r.get("report_date") or ""), reverse=True)
        return {"income": inc, "balance": bal[0] if bal else {},
                "cash": cfs, "earnings": ern[:4]}

    def drawdown(self, t: str) -> Dict:
        k = f"dd:{t}"
        if k in self._cache:
            return self._cache[k]
        rows = self.get(f"/stock/{t}/ohlc/1d", {"limit": 750}) or []
        # ORDER MATTERS. The bulk OHLC fetch returns OLDEST-FIRST — verified:
        # first row 2025-09-11, last row 2026-09-11. Reading closes[0] as the
        # current price made INTC print "$24.61, drawdown -82.5%" when it was
        # actually $103.43 and near its highs. Sort explicitly rather than
        # trusting payload order.
        pairs = [(str(r.get("date") or "")[:10], _f(r.get("close")))
                 for r in rows
                 if str(r.get("market_time") or "") == "r" and _f(r.get("close"))]
        pairs = [p for p in pairs if p[0]]
        if not pairs:
            self._cache[k] = {}
            return {}
        pairs.sort()                      # ascending by date
        pairs = pairs[-252:]              # trailing year of regular sessions
        closes = [c for _, c in pairs]
        cur, hi, lo = closes[-1], max(closes), min(closes)
        out = {"price": cur, "hi52": hi, "lo52": lo,
               "dd": (cur / hi - 1.0) * 100 if hi else None}
        self._cache[k] = out
        return out

    def insider(self, t: str, window_days: int = 365) -> Dict:
        """
        Discretionary insider flow over a DATE window, outliers excluded.

        TWO BUGS THIS FIXES, both found on MSFT:

        1. FILTERED BY RECORD COUNT, NOT DATE. `limit=90` returns 90 ROWS,
           which for MSFT spanned 2020-08-17 to 2026-09-01 — SIX YEARS
           reported as "last 90 days". Insider activity is sparse, so a row
           count is not a time window.

        2. ONE CORRUPT ROW IN UW'S DATA. 2020-09-01 carries a premium of
           -$189,002,518,402 — $189 BILLION, against a next-largest row of
           -$144M. That single row produced "net -$189.89B" for Microsoft.
           Rows more than OUTLIER_MULT x the median magnitude are dropped and
           counted, so bad source data cannot silently dominate a total.
        """
        import datetime as _dt
        OUTLIER_MULT = 100.0
        rows = self.get(f"/insider/{t}/ticker-flow", {"limit": 500}) or []
        cutoff = (_dt.date.today() - _dt.timedelta(days=window_days)).isoformat()

        recs = []
        for r in rows:
            d = str(r.get("date") or "")[:10]
            if not d or d < cutoff:
                continue
            prem = _f(r.get("premium"), 0.0) or 0.0
            p10 = _f(r.get("premium_10b5"), 0.0) or 0.0
            disc = prem - p10          # strip pre-scheduled 10b5-1 plans
            if abs(disc) >= 1:
                recs.append((d, disc))

        dropped = 0
        if len(recs) >= 5:
            mags = sorted(abs(x) for _, x in recs)
            med = mags[len(mags) // 2]
            if med > 0:
                keep = [(d, x) for d, x in recs if abs(x) <= med * OUTLIER_MULT]
                dropped = len(recs) - len(keep)
                recs = keep

        buy = sum(x for _, x in recs if x > 0)
        sell = -sum(x for _, x in recs if x < 0)
        return {"buy": buy, "sell": sell, "days": len(recs),
                "dropped": dropped, "window": window_days}

    def holders(self, t: str) -> List[Dict]:
        rows = self.get(f"/institution/{t}/ownership", {"limit": 8}) or []
        # FIELD TRAP: `inst_value` / `inst_share_value` is the institution's
        # ENTIRE portfolio (BlackRock $6.48T), not its position in this ticker.
        # `value` is the position. Using the wrong one displayed BlackRock's
        # whole book as if it were their Intel stake.
        out = []
        for r in rows[:5]:
            out.append({"name": str(r.get("name") or "")[:26],
                        "value": _f(r.get("value")),
                        "units": _f(r.get("units")),
                        "avg": _f(r.get("avg_price")),
                        "chg": _f(r.get("units_changed")),
                        "first": str(r.get("first_buy") or "")[:10]})
        return out

    # ---------------------------------------------------------------- long
    #
    # LONG HORIZON. Everything measured on this project was 1-3 DAY horizons —
    # fifteen nulls on flow, gamma, technicals, VRP. None of it transfers here.
    # Market-efficiency arguments are strongest at short horizons and weakest
    # at long ones, so those conclusions say nothing about holding for years.
    #
    # The inputs invert too. Fundamentals are useless for a 3-day trade (they
    # update four times a year, so they are nearly constant across the hold)
    # and are most of what matters over years. This is the one section of this
    # project where the input and the holding period actually meet.
    # ----------------------------------------------------------------------

    QUALITY_MIN_MARKETCAP = 10_000_000_000      # $10B floor

    def annual_trend(self, t: str, years: int = 5) -> List[Dict]:
        """Annual revenue / margins / FCF, oldest to newest."""
        d = self._financials_raw(t)
        inc = [r for r in (d.get("income_statements") or [])
               if str(r.get("report_type")) == "annual"]
        cfs = {str(r.get("fiscal_date_ending")): r
               for r in (d.get("cash_flows") or [])
               if str(r.get("report_type")) == "annual"}
        bal = {str(r.get("fiscal_date_ending")): r
               for r in (d.get("balance_sheets") or [])
               if str(r.get("report_type")) == "annual"}
        inc.sort(key=lambda r: str(r.get("fiscal_date_ending")), reverse=True)

        out = []
        for r in inc[:years]:
            fd = str(r.get("fiscal_date_ending"))
            rev = _f(r.get("total_revenue"))
            op = _f(r.get("operating_income"))
            ni = _f(r.get("net_income"))
            c = cfs.get(fd, {})
            ocf, capex = _f(c.get("operating_cashflow")), _f(c.get("capital_expenditures"))
            fcf = (ocf - abs(capex)) if (ocf is not None and capex is not None) else None
            sh = _f((bal.get(fd) or {}).get("common_stock_shares_outstanding"))
            out.append({"year": fd[:4], "rev": rev, "op": op, "ni": ni,
                        "fcf": fcf, "shares": sh,
                        "op_margin": (op / rev * 100) if (op is not None and rev) else None})
        return list(reversed(out))      # oldest -> newest reads as a trend

    def valuation(self, t: str, price: Optional[float]) -> Dict:
        """Multiples from the most recent ANNUAL statements."""
        tr = self.annual_trend(t, 2)
        if not tr or price is None:
            return {}
        cur = tr[-1]
        sh = cur.get("shares")
        mcap = (price * sh) if (sh and price) else None
        d = self._financials_raw(t)
        bal = [r for r in (d.get("balance_sheets") or [])
               if str(r.get("report_type")) == "annual"]
        bal.sort(key=lambda r: str(r.get("fiscal_date_ending")), reverse=True)
        b = bal[0] if bal else {}
        cash = _f(b.get("cash_and_short_term_investments")) or _f(b.get("cash_and_cash_equivalents")) or 0.0
        debt = (_f(b.get("long_term_debt")) or 0.0) + (_f(b.get("current_debt")) or 0.0)
        ev = (mcap + debt - cash) if mcap is not None else None
        inc = [r for r in (d.get("income_statements") or [])
               if str(r.get("report_type")) == "annual"]
        inc.sort(key=lambda r: str(r.get("fiscal_date_ending")), reverse=True)
        ebitda = _f(inc[0].get("ebitda")) if inc else None
        ni, fcf = cur.get("ni"), cur.get("fcf")
        return {
            "mcap": mcap, "ev": ev, "cash": cash, "debt": debt,
            "pe": (mcap / ni) if (mcap and ni and ni > 0) else None,
            "ev_ebitda": (ev / ebitda) if (ev and ebitda and ebitda > 0) else None,
            "fcf_yield": (fcf / mcap * 100) if (fcf and mcap) else None,
            "quality": (mcap is not None and mcap >= self.QUALITY_MIN_MARKETCAP),
        }

    def holder_trend(self, t: str) -> List[Dict]:
        """13F direction over the reported quarters, not a snapshot."""
        rows = self.get(f"/institution/{t}/ownership", {"limit": 8}) or []
        out = []
        for r in rows[:5]:
            h = r.get("historical_units") or []
            h = [x for x in h if isinstance(x, (int, float))]
            if len(h) >= 2:
                # API returns newest-first; oldest -> newest for a trend read.
                first, last = h[-1], h[0]
                pct = ((last / first - 1) * 100) if first else None
            else:
                pct = None
            out.append({"name": str(r.get("name") or "")[:24],
                        "value": _f(r.get("value")),
                        "avg": _f(r.get("avg_price")),
                        "trend_pct": pct, "quarters": len(h)})
        return out

    def options(self, t: str) -> Dict:
        rows = self.get("/screener/stocks", {"ticker": t, "limit": 200}) or []
        for r in rows:
            if str(r.get("ticker") or "").upper() == t.upper():
                return {"iv30": _f(r.get("iv30d")), "iv_rank": _f(r.get("iv_rank")),
                        "cv": _f(r.get("call_volume")), "pv": _f(r.get("put_volume")),
                        "next_er": r.get("next_earnings_date")}
        return {}


# ---------------------------------------------------------------------------
# WHAT QUALIFIES AS A LONG-HORIZON ALERT
#
# Each condition is a CHECKABLE FACT about the business, not a prediction and
# not a score. Deliberately no weighting and no composite number: a score
# invites being traded, and nothing here has been backtested at a multi-year
# horizon. The output is "these conditions are met" — the judgment stays with
# whoever reads it.
#
# The shape is quality-at-a-discount: a business that makes money, is growing,
# is not drowning in debt, is not diluting — that the market has marked down.
# Every clause is a reason a long-horizon buyer would want to LOOK, never a
# reason to act.
#
# DRAWDOWN IS A GATE, NOT A VOTE.
#
# It was one of seven optional conditions, and the quality conditions outvoted
# it every time: MSFT (-8.3%), NVDA (-6.8%) and AAPL (-1.4%) all qualified at
# 6/7 with drawdown as their ONLY failure, ranking above INTC at -26.5%. The
# screen was finding "great businesses at any price" when the whole point of
# quality-at-a-discount is the discount.
#
# A name must now clear the drawdown band AND meet MIN_CONDITIONS of the rest.
# ---------------------------------------------------------------------------
MIN_CONDITIONS = 5          # of the eight non-gate conditions

# VALUATION AND TREND — added after the screen was caught checking neither.
#
# The card COMPUTED P/E, EV/EBITDA and FCF yield and the screen used none of
# them, so "quality at a discount" was measuring the discount purely as
# drawdown from a stock's own 52-week high. A name can be 20% off its high and
# still expensive; another can sit at highs and be cheap. Drawdown is a price
# fact, not a valuation.
#
# And every check was a LEVEL, never a TREND. MSFT's free cash flow peaked in
# 2024 at $74.07B and fell to $66.99B while net income rose to $133.75B — the
# card displays that divergence and the screen ignored it. A business whose
# cash generation is rolling over is a different proposition from one whose is
# compounding, and "FCF positive" cannot tell them apart.
# The stop is CLAMPED AT BOTH ENDS.
#
# Capping only the far side fixed SNDK (-95% -> -30%) and left the near side
# broken: AS came out at -3%, HD -4%, PDD -6%, giving R:R of 1:19.5, 1:9.8 and
# 1:12.9. Those look like exceptional setups and are nothing of the kind — the
# 52-week low simply happened to sit near spot. A 3% stop on a multi-year
# thesis is noise; it is hit in a week by ordinary movement.
#
# So: never nearer than MIN, never further than MAX. Risk is then always
# 10-30% of entry, which is the range where "thesis broken" is a fair reading
# and where R:R can be compared across names.
MIN_STOP_PCT = 10.0          # never a noise-width stop on a multi-year hold
MAX_STOP_PCT = 30.0          # never an unbounded one either
MAX_EV_EBITDA = 25.0
MIN_FCF_YIELD = 2.0          # %

# The band is the GATE. The floor excludes genuine distress — below it the
# question stops being "is this cheap" and becomes "is this solvent", which
# trailing financials answer too slowly to be useful.
DRAWDOWN_BAND = (-50.0, -12.0)   # marked down, but not in freefall
MAX_NET_DEBT_EBITDA = 3.0
MIN_REV_CAGR = 3.0               # %/yr
MAX_DILUTION = 2.0               # % share growth tolerated over the window


def qualifies(t: str, c: Card) -> Dict:
    """Return each condition and whether it is met. No score."""
    dd = c.drawdown(t)
    price = dd.get("price")
    tr = c.annual_trend(t, 5)
    val = c.valuation(t, price)
    ins = c.insider(t)
    hold = c.holder_trend(t)

    cur = tr[-1] if tr else {}
    rev_cagr = None
    if len(tr) >= 2 and tr[0].get("rev") and tr[-1].get("rev"):
        n = len(tr) - 1
        rev_cagr = ((tr[-1]["rev"] / tr[0]["rev"]) ** (1 / n) - 1) * 100 if n else None
    dilution = None
    if len(tr) >= 2 and tr[0].get("shares") and tr[-1].get("shares"):
        dilution = (tr[-1]["shares"] / tr[0]["shares"] - 1) * 100

    # Trend measures: first vs last year of the window.
    fcf_trend = margin_trend = None
    if len(tr) >= 2:
        f0, f1 = tr[0].get("fcf"), tr[-1].get("fcf")
        if f0 and f1 and f0 > 0:
            fcf_trend = (f1 / f0 - 1) * 100
        m0, m1 = tr[0].get("op_margin"), tr[-1].get("op_margin")
        if m0 is not None and m1 is not None:
            margin_trend = m1 - m0

    net_debt = (val.get("debt") or 0) - (val.get("cash") or 0)
    ebitda = None
    if val.get("ev") and val.get("ev_ebitda"):
        ebitda = val["ev"] / val["ev_ebitda"]
    nd_ebitda = (net_debt / ebitda) if (ebitda and ebitda > 0) else None

    accumulating = sum(1 for h in hold
                       if h.get("trend_pct") is not None and h["trend_pct"] > 0)

    conds = [
        ("market cap >= $10B",
         bool(val.get("quality")), _money(val.get("mcap"))),
        ("free cash flow positive",
         bool(cur.get("fcf") and cur["fcf"] > 0), _money(cur.get("fcf"))),
        (f"revenue CAGR >= {MIN_REV_CAGR}%",
         bool(rev_cagr is not None and rev_cagr >= MIN_REV_CAGR),
         f"{rev_cagr:+.1f}%" if rev_cagr is not None else "—"),
        (f"net debt/EBITDA <= {MAX_NET_DEBT_EBITDA}",
         bool(nd_ebitda is not None and nd_ebitda <= MAX_NET_DEBT_EBITDA),
         f"{nd_ebitda:.1f}x" if nd_ebitda is not None else "—"),
        (f"dilution <= {MAX_DILUTION}%",
         bool(dilution is not None and dilution <= MAX_DILUTION),
         f"{dilution:+.1f}%" if dilution is not None else "—"),
        # --- valuation: the half "at a discount" was missing ---
        (f"EV/EBITDA <= {MAX_EV_EBITDA:.0f}",
         bool(val.get("ev_ebitda") is not None and val["ev_ebitda"] <= MAX_EV_EBITDA),
         f"{val['ev_ebitda']:.1f}x" if val.get("ev_ebitda") is not None else "—"),
        (f"FCF yield >= {MIN_FCF_YIELD:.0f}%",
         bool(val.get("fcf_yield") is not None and val["fcf_yield"] >= MIN_FCF_YIELD),
         f"{val['fcf_yield']:.2f}%" if val.get("fcf_yield") is not None else "—"),
        # --- trend: levels alone cannot see a business rolling over ---
        ("FCF trend not declining",
         bool(fcf_trend is not None and fcf_trend >= -10.0),
         f"{fcf_trend:+.0f}% over window" if fcf_trend is not None else "—"),
        ("operating margin not compressing",
         bool(margin_trend is not None and margin_trend >= -1.0),
         f"{margin_trend:+.1f}pp" if margin_trend is not None else "—"),
        # The OR used to be "insiders net buyers OR 3+ institutions adding",
        # and EVERY mega-cap passed on the second clause while insiders were
        # net SELLERS — NVDA by $1.45B. Index funds accumulate mechanically as
        # inflows arrive, so that clause measures fund flows, not conviction.
        # Discretionary insider BUYING is rare and is the one worth requiring.
        ("insiders net buyers (discretionary)",
         bool((ins["buy"] - ins["sell"]) > 0),
         f"net {_money(ins['buy'] - ins['sell'])} ({accumulating} inst adding)"),
    ]
    met = sum(1 for _, ok, _ in conds if ok)

    # THE GATE. Evaluated separately and reported separately.
    dd_val = dd.get("dd")
    gate = bool(dd_val is not None
                and DRAWDOWN_BAND[0] <= dd_val <= DRAWDOWN_BAND[1])
    return {"conds": conds, "met": met, "total": len(conds),
            "gate": gate, "gate_detail": f"{dd_val:+.1f}%" if dd_val is not None else "—",
            "alert": gate and met >= MIN_CONDITIONS}


def long_levels(dd: Dict, val: Dict) -> Dict:
    """
    Entry / stop / target for a MULTI-YEAR hold.

    NOT ATR. The trading side uses 0.75-1.5 ATR, which is right for a 3-day
    hold and absurd for a 3-year one — a 1.5 ATR stop on a multi-year thesis is
    hit by ordinary noise inside a fortnight. Levels for a long hold have to be
    wide enough that only a broken thesis reaches them.

    STOP   the CLOSER of the 52-week low and MAX_STOP_PCT below entry.

           The 52-week low alone was the first attempt and it failed: for a
           name that has travelled a long way in a year the low is ancient
           history, not support. SNDK priced $1,643 with a 52w low of $84 gave
           a stop 95% below entry; AS gave one 3% below. Risk ranged from 3% to
           95% across the same list, so the R:R column was meaningless —
           AS showed 1:18.7 purely because its low happened to sit near spot,
           which a reader would misread as a great setup.

           Bounding it keeps the "market already tested this" logic where the
           low is recent and relevant, and falls back to a fixed review trigger
           where it is not. Risk is then comparable across names, which is what
           makes R:R mean anything at all.

           Still a REVIEW TRIGGER, not a tight stop.
    TARGET the 52-week high: the drawdown simply closing. Deliberately the most
           conservative marker available — no multiple expansion assumed, no
           growth extrapolated, nothing that requires the future to cooperate.

    Both are markers for judgment, not orders. Nothing here is backtested at
    this horizon.
    """
    price, hi, lo = dd.get("price"), dd.get("hi52"), dd.get("lo52")
    if not price or not hi or not lo:
        return {}
    far = price * (1 - MAX_STOP_PCT / 100.0)
    near = price * (1 - MIN_STOP_PCT / 100.0)
    stop = min(max(lo, far), near)        # clamp the 52w low into [far, near]
    bounded = abs(stop - lo) > 0.005 * price
    risk = price - stop
    reward = hi - price
    return {
        "entry": price, "stop": stop, "target": hi, "bounded": bounded,
        "risk_pct": (stop / price - 1) * 100,
        "reward_pct": (hi / price - 1) * 100,
        "rr": (reward / risk) if risk > 0 else None,
    }


# ── DCA LADDER ───────────────────────────────────────────────────────────────
# For a long-term account: instead of one entry, a set of GTC limit orders
# stepping down from spot, so a name that keeps falling is accumulated rather
# than avoided.
#
# THE STOP HAS TO BE REINTERPRETED, not reused. long_levels() returns a stop —
# a level at which you SELL. A ladder that BUYS on the way down to it is the
# opposite instruction, and shipping both in one card would be incoherent. So
# in this mode that level is the ACCUMULATION FLOOR: the point at which you
# stop adding and re-read the thesis. You do not sell into it. The clamp that
# made it comparable across names ([10%, 30%] below spot) is exactly what makes
# it usable as a floor — it bounds how far the ladder can run.
#
# Rungs stop at 3/4 of the way down, never at the floor itself. Buying AT the
# level that says "thesis needs re-reading" spends the last of the allocation
# at the worst moment; leaving that quarter unbought is what keeps the decision
# open.
#
# Weights lean down-ladder. That is the whole point of the ladder — if the
# tranches were equal, the average cost would sit near the middle and the
# structure would add nothing over one order at spot.
DCA_WEIGHTS = (0.15, 0.20, 0.30, 0.35)
DCA_STEPS = (0.00, 0.25, 0.50, 0.75)   # fraction of the way from spot to floor
DEFAULT_DCA_BUDGET = 2000.0            # per name

# The stop's near bound CANNOT be reused as the accumulation floor, and the
# first version of this that did was broken for half the list: NFLX came out
# with a ladder spanning 8.9%, HD 7.5%, AS 7.5%, rungs 2.5% apart. Every rung
# in those fills inside one ordinary week, so the "ladder" was one order at
# spot wearing four labels, and the average cost sat 4.6% below spot — nothing.
#
# The two numbers answer different questions. A STOP asks "how far down before
# the thesis is wrong", and 10% can honestly be that. A DCA FLOOR asks "how far
# down am I still willing to add", which is a property of the PLAN, not of
# where the 52-week low happened to land. Below ~20% the structure stops doing
# anything.
#
# So the floor is the DEEPER of the clamped stop and a fixed minimum span. The
# 30% cap still binds at the far end, and the 52-week low still shows up — as a
# marker on the ladder rather than as the thing that sets its length.
DCA_MIN_DEPTH_PCT = 20.0


def dca_ladder(lv: Dict, lo52: Optional[float] = None,
               budget: float = DEFAULT_DCA_BUDGET) -> Dict:
    """
    Turn entry/stop/target into a descending ladder of limit orders.

    Rung 1 sits at spot — a marketable limit, filling roughly now. Without it
    you own nothing in any name that simply goes up from here, which over a
    20-name list is most of the ones that worked.

    The number worth reading is AVERAGE COST, not spot: it is what the R:R is
    actually measured from, and it is the only thing the ladder buys you.
    """
    if not lv:
        return {}
    entry, target = lv["entry"], lv["target"]
    floor_ = min(lv["stop"], entry * (1 - DCA_MIN_DEPTH_PCT / 100.0))
    widened = floor_ < lv["stop"] - 1e-9
    depth = entry - floor_
    if depth <= 0:
        return {}
    rungs = []
    for i, (w, s) in enumerate(zip(DCA_WEIGHTS, DCA_STEPS), 1):
        p = entry - depth * s
        cash = budget * w
        sh = int(cash // p)
        rungs.append({"n": i, "limit": p, "off_pct": (p / entry - 1) * 100,
                      "w": w, "cash": cash, "shares": sh, "spent": sh * p})
    avg = sum(r["w"] * r["limit"] for r in rungs) / sum(DCA_WEIGHTS)
    risk = avg - floor_
    return {
        "rungs": rungs, "avg": avg, "avg_off_pct": (avg / entry - 1) * 100,
        "floor": floor_, "floor_pct": (floor_ / entry - 1) * 100,
        "target": target, "full_at": rungs[-1]["limit"],
        "full_at_pct": rungs[-1]["off_pct"], "widened": widened,
        "lo52": lo52,
        # Where the 52-week low sits relative to the ladder. Inside it means
        # the market has already traded through rungs you are about to place.
        "lo52_inside": (lo52 is not None and floor_ < lo52 < entry),
        "lo52_pct": ((lo52 / entry - 1) * 100) if lo52 else None,
        "reward_pct": (target / avg - 1) * 100,
        "rr": ((target - avg) / risk) if risk > 0 else None,
        "underfunded": [r["n"] for r in rungs if r["shares"] == 0],
        "min_budget": entry / min(DCA_WEIGHTS),
    }


def render_dca(tickers: List[str], c: Card, budget: float = DEFAULT_DCA_BUDGET) -> str:
    L = [f"═══ DCA LADDER — GTC limit orders · ${budget:,.0f} per name ═══", ""]
    shown = 0
    for t in tickers:
        t = t.upper()
        try:
            dd = c.drawdown(t)
            lv = long_levels(dd, c.valuation(t, dd.get("price")))
            lad = dca_ladder(lv, dd.get("lo52"), budget)
            if not lad:
                continue
            q = qualifies(t, c)
        except Exception as e:
            L.append(f"{t}  — error: {e}")
            continue
        shown += 1
        mark = "✅" if q["alert"] else "  "
        L.append(f"{t:<6} {mark} spot ${dd['price']:,.2f}   drawdown {dd['dd']:+.1f}%"
                 f"   {q['met']}/{q['total']} conditions")
        for r in lad["rungs"]:
            off = "at spot" if r["n"] == 1 else f"{r['off_pct']:+.1f}%"
            sh = f"{r['shares']:>3} sh" if r["shares"] else "  0 sh ⚠️"
            L.append(f"     #{r['n']}  limit ${r['limit']:>10,.2f}  {off:>9}"
                     f"   {r['w']:>4.0%}  ${r['cash']:>7,.0f}   {sh}")
        rr = f"1:{lad['rr']:.1f}" if lad["rr"] else "—"
        L.append(f"     avg cost if all fill ${lad['avg']:,.2f} ({lad['avg_off_pct']:+.1f}%)"
                 f"   target ${lad['target']:,.2f} (+{lad['reward_pct']:.0f}%)   R:R {rr}")
        L.append(f"     fully allocated only at ${lad['full_at']:,.2f} "
                 f"({lad['full_at_pct']:+.1f}%)   ·   floor ${lad['floor']:,.2f} "
                 f"({lad['floor_pct']:+.1f}%) — stop ADDING, not a sell")
        if lad.get("lo52"):
            where = ("inside the ladder — already traded through"
                     if lad["lo52_inside"] else
                     "below the floor — ladder stays above it"
                     if lad["lo52"] <= lad["floor"] else
                     "above spot — the low is not recent support")
            L.append(f"     52w low ${lad['lo52']:,.2f} "
                     f"({lad['lo52_pct']:+.1f}%) · {where}")
        if lad.get("widened"):
            L.append(f"     ladder widened to the {DCA_MIN_DEPTH_PCT:.0f}% minimum span — "
                     f"the chart-based floor was too shallow to accumulate into")
        if lad["underfunded"]:
            L.append(f"     ⚠️ rung(s) {lad['underfunded']} round to 0 shares — "
                     f"needs ~${lad['min_budget']:,.0f}/name at this price")
        L.append("")

    L += [f"{shown} name(s).", "",
          "HOW TO READ THIS",
          "  · The floor is where you STOP ADDING and re-read the thesis. It is not",
          "    a sell level — a ladder that buys down cannot also stop out.",
          "  · Rungs end a quarter of the way above the floor on purpose, so the",
          "    last of the allocation is not spent at the worst moment.",
          "  · R:R is measured from AVERAGE COST, which is the only thing the",
          "    ladder actually buys you.",
          "",
          "WHAT THIS STRUCTURE DOES TO YOU, stated plainly",
          "  · Adverse selection is built in. You end up FULLY allocated only in the",
          "    names that kept falling, and holding one small tranche of the ones",
          "    that recovered. That is the arithmetic of the ladder, not a flaw in",
          "    it — but the resulting book is tilted toward the worst performers.",
          "  · Deep rungs may sit unfilled for a year. That is the intended",
          "    behaviour and it means the capital is committed but idle.",
          "  · The screen is BACKWARD-looking (last reported quarter); the drawdown",
          "    is the market's view TODAY. Sorting quality names by deepest",
          "    drawdown selects for disagreement between the two. Sometimes that is",
          "    the opportunity; sometimes the market is simply early.",
          "",
          "Nothing here is backtested at a multi-year horizon. These are limit",
          "prices for you to place — no order is placed by this tool."]
    return "\n".join(L)


def render_qualify(t: str, c: Card) -> str:
    q = qualifies(t, c)
    head = "✅ QUALIFIES" if q["alert"] else "— does not qualify"
    L = [f"═══ {t} — LONG-HORIZON SCREEN ═══",
         f"{head}   gate {'PASS' if q['gate'] else 'FAIL'} · "
         f"{q['met']}/{q['total']} conditions (need {MIN_CONDITIONS})", "",
         f"  {'GATE' if q['gate'] else 'GATE'} {'✓' if q['gate'] else '✗'} "
         f"drawdown in {DRAWDOWN_BAND[0]:.0f}%..{DRAWDOWN_BAND[1]:.0f}%"
         f"{'':<10}{q['gate_detail']}", ""]
    for name, ok, detail in q["conds"]:
        L.append(f"  {'✓' if ok else '✗'} {name:<38} {detail}")
    lv = long_levels(c.drawdown(t), c.valuation(t, c.drawdown(t).get("price")))
    if lv:
        L += ["",
              "LEVELS  (multi-year markers, NOT day-trade stops)",
              f"  entry   ${lv['entry']:,.2f}",
              f"  stop    ${lv['stop']:,.2f}  ({lv['risk_pct']:+.1f}%)  "
              f"{'clamped' if lv.get('bounded') else '52w low'} — review trigger",
              f"  target  ${lv['target']:,.2f}  ({lv['reward_pct']:+.1f}%)  "
              f"52w high — the drawdown simply closing"]
        if lv.get("rr"):
            L.append(f"  R:R     1 : {lv['rr']:.2f}")
    L += ["",
          "Conditions are FACTS about the business, not predictions. No score,",
          "no weighting, deliberately. Qualifying means 'worth a look' — the",
          "judgment belongs to whoever reads it. Nothing here has been",
          "backtested at a multi-year horizon."]
    return "\n".join(L)


def render_ranked(tickers: List[str], c: Card) -> str:
    """
    Rank a universe by conditions met, highest first.

    RANKING vs SCORING — the distinction that matters here.
    Ordering names for a human to READ is harmless: it is an attention queue,
    not a claim about returns. Feeding a score into SIZING or a trigger is
    what does damage, because the number then moves money on a relationship
    that has never been measured. The gym PPO score fed position sizing; this
    one feeds a list.

    The conditions stay visible alongside the rank. A rank with no reasons is
    the black box this project keeps getting burned by — "Tier 2: ACTIVE",
    a confidence value nothing consumed, a gate score that ranked nothing.
    You should be able to see WHY a name is third and disagree with it.

    Ties break on drawdown depth: among names meeting the same conditions,
    the one the market has marked down further is the more interesting look.
    """
    rows = []
    for t in tickers:
        t = t.upper()
        try:
            q = qualifies(t, c)
            dd = c.drawdown(t)
            names = [n for n, ok, _ in q["conds"] if not ok]
            if not q["gate"]:
                names = ["GATE: drawdown"] + names
            rows.append({"t": t, "met": q["met"], "total": q["total"],
                         "alert": q["alert"], "dd": dd.get("dd"),
                         "gate": q["gate"], "fails": names})
        except Exception as e:
            rows.append({"t": t, "met": -1, "total": 0, "alert": False,
                         "dd": None, "fails": [f"error: {e}"]})

    # Gate first, then conditions met, then depth of drawdown. A name that
    # fails the gate cannot outrank one that passes it, however clean it looks.
    rows.sort(key=lambda r: (not r.get("gate"), -r["met"],
                             r["dd"] if r["dd"] is not None else 0))

    L = [f"═══ LONG-HORIZON RANKING — {len(rows)} names ═══", "",
         f"  {'#':<3}{'ticker':<8}{'met':>6}{'drawdown':>11}   failing"]
    L.append("  " + "-" * 72)
    for i, r in enumerate(rows, 1):
        mark = "✅" if r["alert"] else "  "
        dd = f"{r['dd']:+.1f}%" if r["dd"] is not None else "—"
        fails = ", ".join(r["fails"])[:52] or "none"
        L.append(f"  {i:<3}{r['t']:<8}{mark} {r['met']}/{r['total']}{dd:>10}   {fails}")
    L += ["",
          "Ranked for ATTENTION, not for sizing. The conditions are facts about",
          "each business; the order is just which meets more of them, ties broken",
          "by how far the market has marked it down. Nothing here has been",
          "backtested at a multi-year horizon — the judgment is yours."]
    return "\n".join(L)


def render_long(t: str, c: Card) -> str:
    """Long-horizon view: 5-year trend, valuation, 13F trajectory."""
    dd = c.drawdown(t)
    price = dd.get("price")
    tr = c.annual_trend(t, 5)
    val = c.valuation(t, price)
    hold = c.holder_trend(t)
    ins = c.insider(t)

    L = [f"═══ {t} — LONG HORIZON ═══", ""]

    if not val.get("quality"):
        mc = val.get("mcap")
        L.append(f"⚠️  BELOW QUALITY FLOOR — market cap {_money(mc)} "
                 f"< {_money(c.QUALITY_MIN_MARKETCAP)}")
        L.append("    Smaller names carry survivorship and liquidity risk that")
        L.append("    none of this data captures. Shown anyway; weigh accordingly.")
        L.append("")

    if tr:
        L.append("5-YEAR TREND  (annual, oldest → newest)")
        L.append(f"  {'year':<6}{'revenue':>12}{'op margin':>11}{'net income':>13}{'free CF':>12}{'shares':>12}")
        for r in tr:
            om = f"{r['op_margin']:.1f}%" if r["op_margin"] is not None else "—"
            sh = f"{r['shares']/1e6:,.0f}M" if r["shares"] else "—"
            L.append(f"  {r['year']:<6}{_money(r['rev']):>12}{om:>11}"
                     f"{_money(r['ni']):>13}{_money(r['fcf']):>12}{sh:>12}")
        if len(tr) >= 2 and tr[0]["rev"] and tr[-1]["rev"]:
            n = len(tr) - 1
            cagr = ((tr[-1]["rev"] / tr[0]["rev"]) ** (1 / n) - 1) * 100 if n else 0
            L.append(f"  revenue CAGR over {n}y: {cagr:+.1f}%")
        if len(tr) >= 2 and tr[0]["shares"] and tr[-1]["shares"]:
            d = (tr[-1]["shares"] / tr[0]["shares"] - 1) * 100
            L.append(f"  share count {d:+.1f}%  "
                     f"({'buybacks' if d < -1 else 'dilution' if d > 1 else 'flat'})")
        L.append("")

    if val:
        L.append("VALUATION  (latest annual)")
        L.append(f"  market cap   {_money(val.get('mcap'))}")
        L.append(f"  net debt     {_money((val.get('debt') or 0) - (val.get('cash') or 0))}")
        L.append(f"  P/E          {val['pe']:.1f}" if val.get("pe") else "  P/E          — (no positive earnings)")
        L.append(f"  EV/EBITDA    {val['ev_ebitda']:.1f}" if val.get("ev_ebitda") else "  EV/EBITDA    —")
        L.append(f"  FCF yield    {val['fcf_yield']:.2f}%" if val.get("fcf_yield") else "  FCF yield    —")
        L.append("")

    if dd:
        L.append("PRICE")
        L.append(f"  ${dd['price']:.2f}   52w high ${dd['hi52']:.2f}   low ${dd['lo52']:.2f}")
        L.append(f"  {dd['dd']:+.1f}% from the high")
        L.append("")

    L.append("13F TRAJECTORY  (share count across reported quarters)")
    if hold:
        for h in hold:
            tp = f"{h['trend_pct']:+.0f}% over {h['quarters']}q" if h.get("trend_pct") is not None else "—"
            avg = f"avg ${h['avg']:,.2f}" if h.get("avg") else ""
            L.append(f"  {h['name']:<24} {_money(h['value']):>10}  {tp:<18} {avg}")
    else:
        L.append("  none reported")
    L.append("")

    L.append(f"INSIDER  (discretionary, 10b5-1 stripped, last {ins['window']}d)")
    L.append(f"  bought {_money(ins['buy'])}  sold {_money(ins['sell'])}  "
             f"net {_money(ins['buy'] - ins['sell'])} over {ins['days']} active days"
             if ins["days"] else "  no discretionary activity in the window")
    if ins.get("dropped"):
        L.append(f"  ⚠️ {ins['dropped']} implausible row(s) excluded (bad source data)")
    L.append("")
    L.append("Context for a multi-year decision, NOT a recommendation. Note that")
    L.append("the 15 nulls measured on this project were all 1-3 DAY horizons and")
    L.append("say nothing about holding for years — but equally, nothing here has")
    L.append("been backtested at a long horizon either.")
    return "\n".join(L)


def render(t: str, c: Card) -> str:
    fin = c.financials(t)
    dd = c.drawdown(t)
    ins = c.insider(t)
    hold = c.holders(t)
    opt = c.options(t)

    L = [f"═══ {t} — FUNDAMENTALS ═══", ""]

    inc, cash, bal = fin["income"], fin["cash"], fin["balance"]
    if inc:
        q = inc[0]
        rev = _f(q.get("total_revenue")) or _f(q.get("revenue"))
        gp, ni = _f(q.get("gross_profit")), _f(q.get("net_income"))
        eb = _f(q.get("ebitda"))
        L.append(f"INCOME  (quarter ending {q.get('fiscal_date_ending')})")
        L.append(f"  revenue      {_money(rev)}")
        L.append(f"  gross profit {_money(gp)}" +
                 (f"   margin {gp/rev*100:.1f}%" if gp and rev else ""))
        L.append(f"  EBITDA       {_money(eb)}")
        L.append(f"  net income   {_money(ni)}" +
                 (f"   margin {ni/rev*100:.1f}%" if ni and rev else ""))
        if len(inc) >= 5:
            prev = _f(inc[4].get("total_revenue")) or _f(inc[4].get("revenue"))
            if rev and prev:
                L.append(f"  revenue YoY  {(rev/prev-1)*100:+.1f}%  (vs same quarter last year)")
        L.append("")

    if cash:
        q = cash[0]
        ocf, capex = _f(q.get("operating_cashflow")), _f(q.get("capital_expenditures"))
        fcf = (ocf - abs(capex)) if (ocf is not None and capex is not None) else None
        L.append("CASH FLOW")
        L.append(f"  operating    {_money(ocf)}")
        L.append(f"  capex        {_money(capex)}")
        L.append(f"  free CF      {_money(fcf)}" +
                 ("   ⚠️ NEGATIVE" if fcf is not None and fcf < 0 else ""))
        L.append("")

    if bal:
        csh = _f(bal.get("cash_and_short_term_investments")) or _f(bal.get("cash_and_cash_equivalents"))
        ltd = _f(bal.get("long_term_debt")) or _f(bal.get("current_long_term_debt"))
        L.append(f"BALANCE (ending {bal.get('fiscal_date_ending')})")
        L.append(f"  cash + ST    {_money(csh)}")
        L.append(f"  long-term debt {_money(ltd)}")
        if csh is not None and ltd:
            L.append(f"  net cash     {_money(csh - ltd)}")
        L.append("")

    if fin["earnings"]:
        L.append("EARNINGS — last 4 reported")
        for e in fin["earnings"]:
            sp = _f(e.get("surprise_percentage"))
            L.append(f"  {str(e.get('report_date'))[:10]}  EPS {e.get('reported_eps')}"
                     f"  vs est {e.get('estimated_eps')}"
                     + (f"   surprise {sp:+.1f}%" if sp is not None else ""))
        L.append("")

    if dd:
        L.append("PRICE / DRAWDOWN (52w)")
        L.append(f"  price ${dd['price']:.2f}   high ${dd['hi52']:.2f}   low ${dd['lo52']:.2f}")
        L.append(f"  drawdown from high  {dd['dd']:+.1f}%")
        L.append("")

    L.append(f"INSIDER — discretionary only, 10b5-1 stripped (last {ins['window']}d)")
    if ins["days"]:
        L.append(f"  bought {_money(ins['buy'])}   sold {_money(ins['sell'])}"
                 f"   net {_money(ins['buy'] - ins['sell'])}   over {ins['days']} active days")
        if ins.get("dropped"):
            L.append(f"  ⚠️ {ins['dropped']} implausible row(s) excluded (bad source data)")
    else:
        L.append("  no discretionary activity")
    L.append("")

    L.append("13F — largest institutional holders")
    if hold:
        for h in hold:
            chg = h.get("chg")
            arrow = ""
            if chg:
                arrow = f"  {'+' if chg > 0 else ''}{chg/1e6:,.1f}M sh QoQ"
            avg = f"  avg ${h['avg']:,.2f}" if h.get("avg") else ""
            L.append(f"  {h['name']:<26} {_money(h['value']):>10}{avg}{arrow}")
    else:
        L.append("  none reported")
    L.append("")

    if opt:
        L.append("OPTIONS CONTEXT")
        pc = (opt['pv'] / (opt['cv'] + opt['pv'])) if (opt.get('cv') and opt.get('pv')) else None
        L.append(f"  IV30 {opt['iv30']:.1%}" if opt.get("iv30") else "  IV30 —")
        L.append(f"  IV rank {opt['iv_rank']:.0f}" if opt.get("iv_rank") is not None else "")
        if pc is not None:
            L.append(f"  put share of volume {pc:.0%}")
        if opt.get("next_er"):
            L.append(f"  next earnings {opt['next_er']}")
        L.append("")

    L.append("Context only — NOT trade logic. Fundamentals update quarterly;")
    L.append("this bot holds days. Deliberately not scored into one number.")
    return "\n".join(x for x in L if x is not None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--rank", action="store_true",
                    help="rank several tickers by conditions met, highest first")
    ap.add_argument("--screen", action="store_true",
                    help="show which long-horizon alert conditions are met")
    ap.add_argument("--long", action="store_true",
                    help="long-horizon view: 5y trend, valuation, 13F trajectory")
    ap.add_argument("--dca", action="store_true",
                    help="descending GTC limit ladder for a long-term account")
    ap.add_argument("--budget", type=float, default=DEFAULT_DCA_BUDGET,
                    help=f"total allocation per name for --dca (default ${DEFAULT_DCA_BUDGET:,.0f})")
    a = ap.parse_args()
    c = Card()
    if a.dca:
        print(render_dca(a.tickers, c, a.budget))
        return 0
    if a.rank:
        print(render_ranked(a.tickers, c))
        return 0
    for t in a.tickers:
        if a.screen:
            print(render_qualify(t.upper(), c))
        elif a.long:
            print(render_long(t.upper(), c))
        else:
            print(render(t.upper(), c))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
