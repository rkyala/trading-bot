#!/usr/bin/env python3
"""
Empirical Friction Matrix — the hurdle rate every options strategy must clear.

WHY THIS EXISTS
Seven strategy backtests have now returned null, and in two of them the
conclusion turned on transaction cost. In the 0DTE condor I assumed $0.05/leg,
concluded "friction is the moat", and was wrong by 10x: measured friction is
$0.005/leg, at which the same trade returns -$0.60 (t-0.11) — fairly priced
rather than crushed by costs. An assumption carried into a conclusion.

Friction is therefore not a footnote, it is the parameter that decides whether
any short-vol variant can work. This measures it instead of assuming it:

    Strategy Net Yield = Gross Edge - (Legs x Relative Spread at that time)

If a structure's gross alpha is 15% of premium and two-way friction on that
instrument is 18%, it is dead before a line of execution logic is written.

METHOD, AND THE MISTAKE THAT FORCED IT
Effective spread = ask-side VWAP minus bid-side VWAP, computed WITHIN a single
1-minute bar. /option-contract/{id}/intraday?date= carries premium_ask_side,
premium_bid_side and the matching volumes per bar.

Measuring across DAY-LONG aggregates does not work. Tried first, it returned
NEGATIVE spreads on three of eight SPY contracts, because intraday drift moves
the underlying far more than a penny-wide spread — bid-side trades late in a
rising session print above ask-side trades from the morning. Within one bar
drift is negligible and the comparison is valid.

Medians throughout, never means: a spread distribution has a long right tail
from stressed bars, and ~12% of bars come back slightly negative as noise
around a penny market. A mean would be dragged by both.

WHAT IS MEASURED PER INSTRUMENT
  absolute spread    $ per contract, one-way is half this
  relative spread    % of mid — the number that sets the hurdle rate
  time-of-day curve  medians by session interval, to find when it is cheapest
  dual-sided rate    % of bars with volume on BOTH sides; a low rate means the
                     estimate rests on thin evidence and the contract is
                     genuinely hard to trade, which is itself the finding
  moneyness buckets  ATM vs OTM wings — relative spread explodes on cheap wings
                     even when the absolute spread stays a penny
"""

import argparse
import json
import math
import os
import statistics as st
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

BASE = "https://api.unusualwhales.com/api"

# Session intervals in UTC. US equity options trade 09:30-16:00 ET; September
# is EDT (UTC-4), so 13:30-20:00 UTC.
SESSION = [
    ("09:30-10:00 open", 13.50, 14.00),
    ("10:00-11:30", 14.00, 15.50),
    ("11:30-14:00 midday", 15.50, 18.00),
    ("14:00-15:30", 18.00, 19.50),
    ("15:30-16:00 close", 19.50, 20.00),
]

MONEYNESS = [
    ("ATM (<0.15%)", 0.0, 0.0015),
    ("near (0.15-0.5%)", 0.0015, 0.005),
    ("wing (0.5-1.5%)", 0.005, 0.015),
]


def _f(v, d=None):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


class FrictionMatrix:
    def __init__(self):
        import requests
        self.s = requests.Session()
        key = os.getenv("UW_API_KEY")
        if key:
            self.s.headers.update({"Authorization": f"Bearer {key}",
                                   "Accept": "application/json"})
        self.stats = defaultdict(int)

    # ------------------------------------------------------------------ data

    def chain(self, ticker: str, day: str) -> List[Dict]:
        try:
            r = self.s.get(f"{BASE}/screener/option-contracts",
                           params={"date": day, "ticker_symbol": ticker,
                                   "limit": 500}, timeout=30)
            rows = r.json().get("data", []) if r.status_code == 200 else []
        except Exception:
            return []
        out = []
        for x in rows or []:
            k, spot = _f(x.get("strike")), _f(x.get("stock_price"))
            typ = str(x.get("option_type") or "").lower()
            if not k or not spot or typ not in ("call", "put"):
                continue
            out.append({"sym": x.get("option_symbol"), "strike": k,
                        "type": typ, "spot": spot,
                        "expiry": str(x.get("expiry"))[:10],
                        "volume": _f(x.get("volume"), 0.0) or 0.0})
        return out

    def bars(self, sym: str, day: str) -> List[Dict]:
        try:
            r = self.s.get(f"{BASE}/option-contract/{sym}/intraday",
                           params={"date": day}, timeout=25)
            return r.json().get("data", []) if r.status_code == 200 else []
        except Exception:
            self.stats["bar_fetch_error"] += 1
            return []

    # ------------------------------------------------------------- measure

    @staticmethod
    def _hour_utc(ts: str) -> Optional[float]:
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            return t.astimezone(timezone.utc).hour + t.astimezone(timezone.utc).minute / 60.0
        except Exception:
            return None

    def measure(self, sym: str, day: str) -> Optional[Dict]:
        """Within-bar effective spread for one contract on one day."""
        rows = self.bars(sym, day)
        if not rows:
            return None
        spreads, rels, by_time = [], [], defaultdict(list)
        dual = total = 0
        for r in rows:
            total += 1
            av = _f(r.get("volume_ask_side"), 0.0) or 0.0
            bv = _f(r.get("volume_bid_side"), 0.0) or 0.0
            if av <= 0 or bv <= 0:
                continue
            a = (_f(r.get("premium_ask_side"), 0.0) or 0.0) / (av * 100.0)
            b = (_f(r.get("premium_bid_side"), 0.0) or 0.0) / (bv * 100.0)
            mid = (a + b) / 2.0
            if mid <= 0:
                continue
            dual += 1
            sp = a - b
            spreads.append(sp)
            rels.append(sp / mid * 100.0)
            h = self._hour_utc(r.get("start_time"))
            if h is not None:
                for name, lo, hi in SESSION:
                    if lo <= h < hi:
                        by_time[name].append(sp / mid * 100.0)
                        break
        if len(spreads) < 15:
            return None
        return {"abs": st.median(spreads), "rel": st.median(rels),
                "dual_rate": dual / max(total, 1) * 100.0,
                "bars": len(spreads), "neg": sum(1 for x in spreads if x < 0) / len(spreads) * 100.0,
                "by_time": {k: st.median(v) for k, v in by_time.items() if len(v) >= 5}}

    # ------------------------------------------------------------- sampling

    def sample_index(self, ticker: str, days: List[str], dte: str,
                     per_bucket: int = 2) -> List[Dict]:
        """
        Sample contracts across moneyness buckets.

        Deliberately NOT just the highest-volume contracts: those are ATM and
        would understate friction badly. Relative spread is worst on cheap OTM
        wings, which is exactly where a condor's short strikes sit.
        """
        out = []
        for day in days:
            ch = self.chain(ticker, day)
            if not ch:
                continue
            if dte == "0dte":
                pool = [c for c in ch if c["expiry"] == day]
            else:
                pool = []
                for c in ch:
                    try:
                        d = (date.fromisoformat(c["expiry"]) - date.fromisoformat(day)).days
                    except Exception:
                        continue
                    if 3 <= d <= 7:
                        pool.append(c)
            if not pool:
                continue
            spot = pool[0]["spot"]
            for label, lo, hi in MONEYNESS:
                cands = [c for c in pool
                         if lo <= abs(c["strike"] - spot) / spot < hi and c["volume"] > 0]
                cands.sort(key=lambda c: -c["volume"])
                for c in cands[:per_bucket]:
                    m = self.measure(c["sym"], day)
                    if not m:
                        continue
                    m.update({"ticker": ticker, "day": day, "bucket": label,
                              "dte": dte, "strike": c["strike"], "type": c["type"]})
                    out.append(m)
                    time.sleep(0.03)
        return out

    def sample_earnings(self, tickers: List[str], per_bucket: int = 2) -> List[Dict]:
        """
        Contracts on the session BEFORE an earnings report — the exact moment
        an IV-crush trade would be entered, and where the spread moat lives.
        """
        out = []
        for t in tickers:
            try:
                ev = self.s.get(f"{BASE}/earnings/{t}", timeout=25).json().get("data", [])
            except Exception:
                continue
            dates = sorted({str(x.get("report_date"))[:10] for x in ev
                            if x.get("report_date") and x.get("short_straddle_1d") is not None},
                           reverse=True)[:2]
            for rd in dates:
                try:
                    d = date.fromisoformat(rd) - timedelta(days=1)
                except Exception:
                    continue
                while d.weekday() > 4:
                    d -= timedelta(days=1)
                day = d.isoformat()
                ch = self.chain(t, day)
                if not ch:
                    continue
                spot = ch[0]["spot"]
                # nearest expiry after the report
                exps = sorted({c["expiry"] for c in ch if c["expiry"] >= rd})
                if not exps:
                    continue
                pool = [c for c in ch if c["expiry"] == exps[0] and c["volume"] > 0]
                for label, lo, hi in MONEYNESS:
                    cands = [c for c in pool
                             if lo <= abs(c["strike"] - spot) / spot < hi]
                    cands.sort(key=lambda c: -c["volume"])
                    for c in cands[:per_bucket]:
                        m = self.measure(c["sym"], day)
                        if not m:
                            continue
                        m.update({"ticker": t, "day": day, "bucket": label,
                                  "dte": "earnings", "strike": c["strike"],
                                  "type": c["type"]})
                        out.append(m)
                        time.sleep(0.03)
        return out


# ------------------------------------------------------------------ report

def _agg(rows: List[Dict], key) -> List[Tuple]:
    g = defaultdict(list)
    for r in rows:
        g[key(r)].append(r)
    return sorted(g.items())


def render(rows: List[Dict]) -> None:
    print("=" * 96)
    print("EMPIRICAL FRICTION MATRIX — measured from real executions, within 1-minute bars")
    print("=" * 96)
    if not rows:
        print("  no measurements")
        return
    print(f"  {len(rows)} contract-days | "
          f"{sum(r['bars'] for r in rows):,} dual-sided bars")
    print()
    print("  Relative spread is the hurdle: a structure must earn more than")
    print("  legs x relative spread, twice (in and out), before it earns anything.")
    print()
    print(f"  {'instrument':<26}{'abs $':>9}{'one-way':>9}{'rel %':>9}"
          f"{'dual-sided':>12}{'neg bars':>10}{'n':>6}")
    print("  " + "-" * 82)
    for k, g in _agg(rows, lambda r: (r["dte"], r["ticker"], r["bucket"])):
        dte, tick, bucket = k
        label = f"{tick} {dte} {bucket}"
        print(f"  {label:<26}{st.median([x['abs'] for x in g]):>9.3f}"
              f"{st.median([x['abs'] for x in g]) / 2:>9.3f}"
              f"{st.median([x['rel'] for x in g]):>8.1f}%"
              f"{st.median([x['dual_rate'] for x in g]):>11.0f}%"
              f"{st.median([x['neg'] for x in g]):>9.0f}%{len(g):>6}")

    # -------- hurdle rate, the number that actually decides things --------
    print()
    print("  HURDLE RATE — 4-leg structure cost as % of premium collected")
    print("  entry-only = held to expiry (shorts expire, no exit spread paid)")
    print("  round-trip = closed early, spread paid twice")
    print(f"  {'instrument':<32}{'entry-only':>10}{'round-trip':>13}{'verdict':>18}")
    print("  " + "-" * 74)
    # Hurdle is reported PER MONEYNESS BUCKET, not pooled. Pooling hides the
    # only thing that matters: a penny is trivial on a $2 ATM option and
    # ruinous on an $0.08 wing, and a condor's short strikes sit in the wing.
    for k, g in _agg(rows, lambda r: (r["dte"], r["ticker"], r["bucket"])):
        dte, tick, bucket = k
        rel = st.median([x["rel"] for x in g])
        entry_only = rel * 4.0 / 2.0     # held to expiry: pay the spread once
        round_trip = rel * 4.0           # closed early: pay it twice
        verdict = ("workable" if round_trip < 15 else
                   "very demanding" if round_trip < 40 else
                   "untradeable")
        print(f"  {tick + ' ' + dte + ' ' + bucket:<32}{entry_only:>10.1f}%"
              f"{round_trip:>13.1f}%{verdict:>18}")

    # -------- time of day --------
    tod = defaultdict(list)
    for r in rows:
        for k, v in (r.get("by_time") or {}).items():
            tod[k].append(v)
    if tod:
        print()
        print("  TIME-OF-DAY — median relative spread by session interval")
        print(f"  {'interval':<26}{'rel %':>9}{'obs':>8}")
        print("  " + "-" * 45)
        for name, _, _ in SESSION:
            if name in tod and len(tod[name]) >= 3:
                print(f"  {name:<26}{st.median(tod[name]):>8.1f}%{len(tod[name]):>8}")

    print()
    print("=" * 96)
    print("  Medians throughout: spread distributions have a long right tail from")
    print("  stressed bars, and ~10-15% of bars come back slightly negative as noise")
    print("  around a penny-wide market. A mean would be dragged by both.")
    print("=" * 96)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="SPY,QQQ,IWM")
    ap.add_argument("--days", type=int, default=6)
    ap.add_argument("--earnings", default="", help="comma tickers, e.g. NVDA,AAPL,TSLA")
    ap.add_argument("--cache", default="friction_matrix.json")
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()

    fm = FrictionMatrix()
    if a.reuse and os.path.exists(a.cache):
        rows = json.load(open(a.cache))
        print(f"cached: {len(rows)} contract-days\n")
    else:
        rows = []
        today = date.today()
        days, i = [], 2
        while len(days) < a.days and i < a.days * 3 + 20:
            d = today - timedelta(days=i)
            if d.weekday() < 5:
                days.append(d.isoformat())
            i += 1
        days.sort()
        for t in [x.strip().upper() for x in a.index.split(",") if x.strip()]:
            for dte in ("0dte", "weekly"):
                print(f"  sampling {t} {dte} ...")
                rows += fm.sample_index(t, days, dte)
        if a.earnings:
            ts = [x.strip().upper() for x in a.earnings.split(",") if x.strip()]
            print(f"  sampling earnings: {', '.join(ts)} ...")
            rows += fm.sample_earnings(ts)
        json.dump(rows, open(a.cache, "w"))
        print()
    render(rows)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
