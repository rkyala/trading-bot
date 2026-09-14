#!/usr/bin/env python3
"""
NDX intraday technicals — moving averages, session Fibonacci, VWAP.

WHY THE NUMBERS COME FROM QQQ
NDX has NO OHLC on this plan (/ohlc and /stock-state both 422) and its only
price series, /spot-exposures, is only ~2.5 min apart. That is too sparse for a
moving average worth the name, and it carries no volume at all, so VWAP is
impossible from it.

QQQ 1-minute has proper OHLCV, 1-minute resolution and ~3 sessions of history.
QQQ holds the same 100 names, so its shape IS the NDX shape. Levels are
computed on QQQ and converted to NDX points with the live ratio, which is
stated on every card — an NDX level derived from QQQ is an ESTIMATE, and the
basis moves.

READ THIS BEFORE ACTING ON ANY LEVEL BELOW
Entry-timing technicals is the most thoroughly tested idea on this project and
the one that failed most clearly:

    27-feature panel   dist_ma20 t+0.23, rsi_14 t+0.43 — bottom of 27
    combined ridge     quant + technicals, held-out test IC  -0.0131
    technical gates    104,924 obs: traded -0.03% vs skipped +0.01%

The gates are ACTIVE-in-shadow in the equity bot for exactly that reason: the
set they would have traded UNDERPERFORMED the set they skipped.

Those tests were daily bars, equities, a 3-day horizon. NDX intraday is a
different regime and genuinely untested — which is the problem, not the
defence. With ~3 sessions of 1-minute data there is no way to test it here
either, and wiring an unmeasured input into an entry decision is precisely how
this bot ended up trading a strategy that measured zero.

So this module is DESCRIPTIVE and LOGGED. It gates nothing. Every reading is
appended to ndx_technicals.jsonl with the forward price attached on the next
poll, so that in a few weeks there is a sample to test against instead of an
opinion. Until then the levels are context for a human, not a signal.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import requests

BASE = "https://api.unusualwhales.com/api"
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "ndx_technicals.jsonl")

# Periods are in MINUTES because the source bars are 1-minute. A "20 MA" here
# is 20 minutes, not 20 days — stated on the card so it cannot be misread as a
# daily average.
MA_PERIODS = (9, 20, 50)
FIB_LEVELS = (0.236, 0.382, 0.5, 0.618, 0.786)


def _et_time(iso: str) -> str:
    """UTC -> ET 'HH:MM'. This feed is UTC; see uw_ndx_monitor._et."""
    from uw_ndx_monitor import _et
    return _et(iso)


def _f(x) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def qqq_bars(limit: int = 2000, today_only: bool = True) -> List[Dict]:
    """Regular-session QQQ 1m bars for the CURRENT session, OLDEST FIRST.

    The market_time filter is mandatory: this endpoint interleaves pre/regular/
    post rows, and today's raw feed returned 413 bars for a 390-minute session.
    Without the filter every average silently spans different sessions.

    TWO SIZING TRAPS, both hit here:
      · limit is a cap on TOTAL rows including pre/post, so limit=500 left only
        119 regular bars — the 50-minute MA was then half the available data and
        "session high/low" covered the last two hours rather than the session.
        The Fibonacci levels built on that range were not session retracements
        at all, which is the kind of number that looks right and is not.
      · limit=5000 returns 422. 2000 is the ceiling this endpoint accepts.

    So: pull the maximum, then cut to the current session by DATE. The result
    is the real session — and short early in the day, which is honest rather
    than padded with yesterday's bars.
    """
    try:
        r = requests.get(f"{BASE}/stock/QQQ/ohlc/1m", params={"limit": limit},
                         headers={"Authorization": f"Bearer {os.getenv('UW_API_KEY')}"},
                         timeout=25)
        rows = [x for x in (r.json().get("data") or [])
                if str(x.get("market_time")) == "r"]
        rows.sort(key=lambda x: str(x.get("start_time") or ""))
        if today_only and rows:
            day = str(rows[-1].get("start_time"))[:10]
            rows = [x for x in rows if str(x.get("start_time"))[:10] == day]
        return rows
    except Exception:
        return []


def compute(ndx_px: float) -> Dict:
    """Technicals on QQQ 1m, with levels converted to NDX points."""
    bars = qqq_bars()
    if len(bars) < max(MA_PERIODS):
        return {}
    close = [_f(b.get("close")) for b in bars]
    high = [_f(b.get("high")) for b in bars]
    low = [_f(b.get("low")) for b in bars]
    vol = [_f(b.get("volume")) or 0.0 for b in bars]
    if any(c is None for c in close):
        return {}

    q = close[-1]
    ratio = ndx_px / q if q else None        # NDX points per QQQ dollar
    if not ratio:
        return {}

    mas = {}
    for p in MA_PERIODS:
        if len(close) >= p:
            m = sum(close[-p:]) / p
            mas[p] = {"qqq": m, "ndx": m * ratio, "dist_pct": (q / m - 1) * 100}

    # Session VWAP. Typical price is the standard (H+L+C)/3 rather than close,
    # so a bar that ranged widely is not represented only by where it settled.
    tpv = sum(((high[i] + low[i] + close[i]) / 3) * vol[i] for i in range(len(bars)))
    tv = sum(vol)
    vwap = (tpv / tv) if tv > 0 else None

    # Session Fibonacci on the QQQ session range. Retracements need only a high
    # and a low, so this is the one construct here that does NOT depend on the
    # short history — the session defines itself.
    hi, lo = max(high), min(low)
    up = close[-1] >= close[0]      # direction of the session move
    fibs = {}
    for lv in FIB_LEVELS:
        # Retrace from the extreme the move came FROM.
        price = (hi - (hi - lo) * lv) if up else (lo + (hi - lo) * lv)
        fibs[lv] = {"qqq": price, "ndx": price * ratio,
                    "dist_pct": (price / q - 1) * 100}

    stack = None
    if all(p in mas for p in (9, 20, 50)):
        if mas[9]["qqq"] > mas[20]["qqq"] > mas[50]["qqq"]:
            stack = "rising (9>20>50)"
        elif mas[9]["qqq"] < mas[20]["qqq"] < mas[50]["qqq"]:
            stack = "falling (9<20<50)"
        else:
            stack = "mixed — no alignment"

    return {
        "bars": len(bars), "qqq": q, "ndx": ndx_px, "ratio": ratio,
        "mas": mas, "stack": stack,
        "vwap": {"qqq": vwap, "ndx": vwap * ratio,
                 "dist_pct": (q / vwap - 1) * 100} if vwap else None,
        "session_hi": {"qqq": hi, "ndx": hi * ratio},
        "session_lo": {"qqq": lo, "ndx": lo * ratio},
        "direction": "up" if up else "down",
        "fibs": fibs,
        "at": _et_time(bars[-1].get("start_time")),
    }


def log(tech: Dict) -> None:
    """
    Append a reading so it can be TESTED later.

    Forward-logging is the only way these levels ever become evidence: there is
    not enough 1-minute history to backtest them, so the sample has to be built
    going forward. Same approach as news_log.jsonl, which is collecting for the
    sentiment question that also cannot be backtested.

    Failure here must never disturb anything else — a logging problem is not
    worth an alerting outage.
    """
    if not tech:
        return
    try:
        rec = {
            "ts": datetime.utcnow().isoformat(),
            "ndx": tech.get("ndx"), "qqq": tech.get("qqq"),
            "stack": tech.get("stack"), "direction": tech.get("direction"),
            "ma_dist": {str(p): round(v["dist_pct"], 4) for p, v in (tech.get("mas") or {}).items()},
            "vwap_dist": round(tech["vwap"]["dist_pct"], 4) if tech.get("vwap") else None,
        }
        with open(LOG_PATH, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def field(tech: Dict) -> Optional[Dict]:
    """Discord embed field. None when there is nothing trustworthy to show."""
    if not tech:
        return None
    lines = []
    if tech.get("stack"):
        lines.append(f"**MA stack** {tech['stack']}")
    for p, v in sorted((tech.get("mas") or {}).items()):
        side = "above" if v["dist_pct"] >= 0 else "below"
        lines.append(f"`{p:>2}m MA`  NDX {v['ndx']:>9,.0f}   "
                     f"{abs(v['dist_pct']):.2f}% {side}")
    if tech.get("vwap"):
        v = tech["vwap"]
        side = "above" if v["dist_pct"] >= 0 else "below"
        lines.append(f"`VWAP `  NDX {v['ndx']:>9,.0f}   {abs(v['dist_pct']):.2f}% {side}")

    f = tech.get("fibs") or {}
    if f:
        lines.append(f"\n**Session fib** ({tech['direction']} move, "
                     f"retracing from the {'high' if tech['direction']=='up' else 'low'})")
        for lv in (0.382, 0.5, 0.618):
            if lv in f:
                lines.append(f"`{lv:.3f}`  NDX {f[lv]['ndx']:>9,.0f}   "
                             f"({f[lv]['dist_pct']:+.2f}%)")
    return {"name": f"Technicals — from QQQ 1m, {tech['bars']} bars (est. NDX levels)",
            "value": "\n".join(lines)[:1020], "inline": False}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from uw_ndx_monitor import snapshot
    s = snapshot()
    t = compute(s["price"]) if s else {}
    if not t:
        print("no technicals available")
    else:
        print(f"NDX {t['ndx']:,.0f}  QQQ {t['qqq']:.2f}  ratio {t['ratio']:.2f}  "
              f"({t['bars']} bars, last {t['at']} ET)")
        print(f"  stack: {t['stack']}   session {t['direction']}")
        for p, v in sorted(t["mas"].items()):
            print(f"  {p:>2}m MA  NDX {v['ndx']:>9,.0f}  {v['dist_pct']:+.2f}%")
        if t["vwap"]:
            print(f"  VWAP    NDX {t['vwap']['ndx']:>9,.0f}  {t['vwap']['dist_pct']:+.2f}%")
        print(f"  session hi {t['session_hi']['ndx']:,.0f}  lo {t['session_lo']['ndx']:,.0f}")
        for lv, v in sorted(t["fibs"].items()):
            print(f"  fib {lv:.3f}  NDX {v['ndx']:>9,.0f}  {v['dist_pct']:+.2f}%")
