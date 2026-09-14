#!/usr/bin/env python3
"""
NDX option chain viewer — what is actually quoted, and what each strike prices.

THIS TOOL DOES NOT PICK A STRIKE. It shows the chain with the numbers that
decide a strike, so the choice is made on data rather than on a hunch. The
judgement is the reader's.

THE COLUMN THAT MATTERS IS `vs implied`
Every option is a bet on MOVE SIZE. The term structure says what the market is
charging for movement to each expiry; `vs implied` shows where a strike sits
against that. A strike well outside the implied move needs an unusually large
move to pay — it is cheap per contract for exactly that reason. One inside it
is priced for something the market already considers likely.

This is the one honest link between the NDX monitor card and an actual
contract, because the single input measured on this project — dealer gamma —
predicts move MAGNITUDE (t+2.9) and not direction. Magnitude is what option
pricing is made of; direction is what sixteen nulls refuse to support.

WHAT IS NOT HERE, deliberately
No recommendation, no ranking, no "best" strike. The breakeven and vs-implied
columns are facts; whether they are attractive depends on a view this tool does
not have.

CONTRACT ID FORMAT: NDX261016P25300000
Parsed from the RIGHT — last 8 digits are strike x1000, the char before is the
type, the 6 before that are YYMMDD. Parsing from the left breaks the moment a
ticker is not 3 characters, which is what made an earlier attempt raise
ValueError on 'C29950000'.
"""

import argparse
import os
import sys
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple

import requests

BASE = "https://api.unusualwhales.com/api"
H = lambda: {"Authorization": f"Bearer {os.getenv('UW_API_KEY')}"}


def _f(x) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def parse_id(cid: str) -> Optional[Tuple[str, str, float]]:
    """(expiry YYYY-MM-DD, 'C'/'P', strike). Parsed from the right — see module docstring."""
    try:
        strike = int(cid[-8:]) / 1000.0
        typ = cid[-9].upper()
        ymd = cid[-15:-9]
        if typ not in ("C", "P") or not ymd.isdigit():
            return None
        return f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}", typ, strike
    except (ValueError, IndexError):
        return None


def spot() -> Optional[float]:
    """NDX price. /ohlc and /stock-state both 422 for indices; spot-exposures works."""
    try:
        r = requests.get(f"{BASE}/stock/NDX/spot-exposures", headers=H(), timeout=20)
        rows = r.json().get("data") or []
        if not rows:
            return None
        newest = max(rows, key=lambda x: str(x.get("time") or ""))
        return _f(newest.get("price"))
    except Exception:
        return None


def term_structure() -> Dict[str, Dict]:
    """expiry -> {iv, implied_move} — what the market charges for movement."""
    out = {}
    try:
        r = requests.get(f"{BASE}/stock/NDX/volatility/term-structure", headers=H(), timeout=20)
        for row in r.json().get("data") or []:
            e = str(row.get("expiry"))
            out[e] = {"iv": _f(row.get("volatility")), "move": _f(row.get("implied_move"))}
    except Exception:
        pass
    return out


def interpolated_move(dte: int, px: float):
    """
    (implied move in POINTS, iv) for `dte` days, from the interpolated curve.

    The term structure lists monthly expiries only, so it cannot price a 0DTE
    or weekly chain — which is precisely the chain a day trader is looking at.
    This endpoint carries implied_move_perc by DTE across the short end.

    Two readings exist per tenor (call and put side); they are averaged. The
    nearest available tenor is used and NOT extrapolated past the curve — a
    fabricated implied move is worse than an empty column.
    """
    try:
        r = requests.get(f"{BASE}/stock/NDX/interpolated-iv", headers=H(), timeout=20)
        rows = [x for x in (r.json().get("data") or []) if _f(x.get("days")) is not None]
        if not rows:
            return None, None
        target = max(dte, 1)
        nearest = min({int(_f(x["days"])) for x in rows}, key=lambda d: abs(d - target))
        at = [x for x in rows if int(_f(x["days"])) == nearest]
        mv = [_f(x.get("implied_move_perc")) for x in at]
        iv = [_f(x.get("volatility")) for x in at]
        mv = [m for m in mv if m is not None]
        iv = [v for v in iv if v is not None]
        if not mv:
            return None, None
        return (sum(mv) / len(mv)) * px, (sum(iv) / len(iv) if iv else None)
    except Exception:
        return None, None


def oi_by_strike() -> Dict[float, Dict]:
    out = {}
    try:
        r = requests.get(f"{BASE}/stock/NDX/oi-per-strike", headers=H(), timeout=20)
        for row in r.json().get("data") or []:
            k = _f(row.get("strike"))
            if k is not None:
                out[k] = {"call_oi": _f(row.get("call_oi")) or 0,
                          "put_oi": _f(row.get("put_oi")) or 0}
    except Exception:
        pass
    return out


def quote(cid: str) -> Dict:
    """Last traded price and IV for one contract."""
    try:
        r = requests.get(f"{BASE}/option-contract/{cid}/intraday",
                         params={"limit": 1}, headers=H(), timeout=20)
        rows = r.json().get("data") or []
        if not rows:
            return {}
        d = rows[-1]
        ivh, ivl = _f(d.get("iv_high")), _f(d.get("iv_low"))
        iv = (ivh + ivl) / 2 if (ivh is not None and ivl is not None) else (ivh or ivl)
        return {"last": _f(d.get("close")), "avg": _f(d.get("avg_price")), "iv": iv,
                "hi": _f(d.get("high")), "lo": _f(d.get("low"))}
    except Exception:
        return {}


def build(expiry: Optional[str], width_pct: float, kind: str) -> List[Dict]:
    px = spot()
    if not px:
        print("NDX price unavailable — cannot place strikes.", file=sys.stderr)
        return []
    ch = requests.get(f"{BASE}/stock/NDX/option-chains", headers=H(), timeout=30).json().get("data", [])
    ts, oi = term_structure(), oi_by_strike()

    parsed = [(c,) + p for c in ch if (p := parse_id(c))]
    today = date.today().isoformat()
    exps = sorted({e for _, e, _, _ in parsed if e >= today})
    if not exps:
        return []
    exp = expiry or exps[0]
    if exp not in exps:
        print(f"no such expiry. next few: {', '.join(exps[:6])}", file=sys.stderr)
        return []

    lo, hi = px * (1 - width_pct / 100), px * (1 + width_pct / 100)
    sel = [(c, t, k) for c, e, t, k in parsed if e == exp and lo <= k <= hi
           and (kind == "both" or t == kind)]
    sel.sort(key=lambda x: (-x[2], x[1]))

    dte = (datetime.strptime(exp, "%Y-%m-%d").date() - date.today()).days
    tsd = ts.get(exp) or {}
    imove = tsd.get("move")
    src = "term structure"
    if imove is None:
        # The term structure only lists MONTHLY expiries — it had no entry for
        # 0DTE, which left `vs implied` blank on exactly the chain a day trader
        # looks at. /interpolated-iv gives implied_move_perc by DTE and covers
        # the short end. Nearest tenor, not extrapolated beyond the curve.
        imove, tsd_iv = interpolated_move(dte, px)
        if imove is not None:
            tsd = {"iv": tsd_iv, "move": imove}
            src = "interpolated curve"
    tsd["src"] = src

    rows = []
    for cid, typ, strike in sel:
        q = quote(cid)
        last = q.get("last")
        # Guard the whole expression: a strike with no trade today returns
        # last=None, and the ternary bound tighter than intended so the call
        # branch ran before the None check.
        be = None
        if last is not None:
            be = (strike + last) if typ == "C" else (strike - last)
        # Distance the underlying must travel for this strike to finish ITM,
        # measured against what the market is charging for movement.
        need = (strike - px) if typ == "C" else (px - strike)
        rows.append({
            "id": cid, "type": typ, "strike": strike, "last": last, "iv": q.get("iv"),
            "hi": q.get("hi"), "lo": q.get("lo"),
            "moneyness": (strike / px - 1) * 100,
            "breakeven": be,
            "be_move_pct": ((be / px - 1) * 100) if be else None,
            "vs_implied": (need / imove) if (imove and imove > 0) else None,
            "oi": (oi.get(strike) or {}).get("call_oi" if typ == "C" else "put_oi"),
        })
    return [{"_meta": {"spot": px, "expiry": exp, "dte": dte,
                       "iv": tsd.get("iv"), "implied_move": imove, "src": tsd.get("src"),
                       "expiries": exps[:8]}}] + rows


def render(rows: List[Dict]) -> str:
    if not rows:
        return "no data"
    m = rows[0]["_meta"]
    rows = rows[1:]
    L = [f"═══ NDX OPTION CHAIN — {m['expiry']} ({m['dte']}d) ═══",
         f"  NDX {m['spot']:,.0f}" +
         (f"   ATM IV {m['iv']*100:.1f}%" if m.get("iv") else "") +
         (f"   implied move ±{m['implied_move']:,.0f} pts "
          f"(±{m['implied_move']/m['spot']*100:.2f}%, {m.get('src')})"
          if m.get("implied_move") else ""),
         "",
         f"  {'strike':>8} {'':2} {'last':>9} {'IV':>7} {'moneyness':>10} "
         f"{'breakeven':>10} {'needs':>8} {'vs impl':>8} {'OI':>8}",
         "  " + "-" * 82]
    for r in rows:
        last = f"{r['last']:,.2f}" if r["last"] else "no trade"
        iv = f"{r['iv']*100:.1f}%" if r["iv"] else "—"
        be = f"{r['breakeven']:,.0f}" if r["breakeven"] else "—"
        need = f"{r['be_move_pct']:+.2f}%" if r["be_move_pct"] is not None else "—"
        vs = f"{r['vs_implied']:.2f}x" if r["vs_implied"] is not None else "—"
        oi = f"{r['oi']:,.0f}" if r["oi"] else "0"
        mark = "◄" if abs(r["moneyness"]) < 0.15 else " "
        L.append(f"  {r['strike']:>8,.0f} {r['type']:>2} {last:>9} {iv:>7} "
                 f"{r['moneyness']:>9.2f}% {be:>10} {need:>8} {vs:>8} {oi:>8}{mark}")
    L += ["",
          "COLUMNS",
          "  breakeven  where NDX must be at expiry for the BUYER to break even",
          "  needs      how far NDX must move to reach that breakeven",
          "  vs impl    distance to the strike ÷ the implied move for this expiry.",
          "             <1.0 = inside what the market already prices as likely.",
          "             >1.0 = needs a bigger move than the market is charging for.",
          "  ◄          nearest the money",
          "",
          "NOT A RECOMMENDATION. These are quotes and arithmetic, not a view. Nothing",
          "here is backtested as a trading rule on NDX. One NDX point is $100, so a",
          "single contract carries roughly $2.9M of notional — XND is the same index",
          "at 1/100th. Last price is the last TRADE, which on an illiquid strike can",
          "sit far from where you would actually get filled; check the live bid/ask",
          "in your broker before acting on any line above.",
          "",
          f"other expiries: {', '.join(m['expiries'])}"]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="NDX option chain viewer")
    ap.add_argument("--expiry", help="YYYY-MM-DD (default: nearest)")
    ap.add_argument("--width", type=float, default=2.0, help="%% around spot (default 2)")
    ap.add_argument("--calls", action="store_true")
    ap.add_argument("--puts", action="store_true")
    a = ap.parse_args()
    kind = "C" if a.calls else "P" if a.puts else "both"
    print(render(build(a.expiry, a.width, kind)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
