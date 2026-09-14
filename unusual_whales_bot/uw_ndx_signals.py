#!/usr/bin/env python3
"""
NDX scalper signals — TTM squeeze, RSI, ATR levels, opening range — plus the
contracts actually seeing directional flow today.

SOURCE, AND WHY IT IS QQQ
NDX has no OHLC on this plan and no volume at all, so every bar-based indicator
here is computed on QQQ 1-minute and converted to NDX points by the live ratio.
Levels shown in NDX terms are ESTIMATES; the basis moves during the day.

WHAT "TRENDING OPTIONS" MEANS HERE, AND THE TRAP IN IT
/stock/NDX/oi-change gives per-contract volume, trades, open interest change,
premium and — critically — prev_multi_leg_volume. Multi-leg volume is spread
volume: verticals, condors, calendars, conversions. It carries NO directional
view, because the other leg offsets it.

The first sample pulled from this endpoint had volume 412 and
prev_multi_leg_volume 412. One hundred per cent spread. Ranked naively on
volume, a list of "trending contracts" is mostly people building spreads, which
is exactly the mistake the deep-ITM whale alerts were making a few hours ago
(two QQQ blocks that were one synthetic long, reported as two bullish whales).

So contracts are ranked on SINGLE-LEG volume, the multi-leg share is shown on
every row, and ask-vs-bid side is reported so a bought contract is not confused
with a sold one.

ON THE INDICATORS
TTM squeeze, RSI and ATR are computed faithfully and are genuinely useful for
describing state — is range compressing, how wide is normal movement. What they
have never done on this project is predict returns:

    27-feature panel   rsi_14 t+0.43, dist_ma20 t+0.23 — bottom of 27 features
    combined ridge     quant + technicals, held-out test IC  -0.0131
    technical gates    104,924 obs: traded -0.03% vs skipped +0.01%

ATR is the exception worth naming: it measures how far price typically travels,
which is a MAGNITUDE question, and magnitude is the one thing that has survived
its controls here. So the ATR levels below are offered as STOP WIDTH and TARGET
DISTANCE — not as entry triggers.

None of this is a recommendation, and none of it is backtested on NDX intraday.
"""

import math
import os
from typing import Dict, List, Optional

import requests

BASE = "https://api.unusualwhales.com/api"

BB_PERIOD, BB_MULT = 20, 2.0
KC_PERIOD, KC_MULT = 20, 1.5
RSI_PERIOD = 14
ATR_PERIOD = 14
OPENING_RANGE_MIN = 15


def _f(x) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _sma(xs: List[float], n: int) -> Optional[float]:
    return sum(xs[-n:]) / n if len(xs) >= n else None


def _stdev(xs: List[float], n: int) -> Optional[float]:
    if len(xs) < n:
        return None
    w = xs[-n:]
    m = sum(w) / n
    return math.sqrt(sum((x - m) ** 2 for x in w) / n)


def true_range(h: List[float], l: List[float], c: List[float]) -> List[float]:
    tr = [h[0] - l[0]]
    for i in range(1, len(c)):
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return tr


def rsi(c: List[float], n: int = RSI_PERIOD) -> Optional[float]:
    if len(c) <= n:
        return None
    gains, losses = [], []
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for i in range(n, len(gains)):          # Wilder smoothing
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    if al == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + ag / al))


def _linreg_slope_value(ys: List[float]) -> Optional[float]:
    """Value of the least-squares line at the LAST point — TTM's momentum."""
    n = len(ys)
    if n < 2:
        return None
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    b = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / den
    return (my - b * mx) + b * (n - 1)


def ttm_squeeze(h: List[float], l: List[float], c: List[float]) -> Dict:
    """
    TTM squeeze: Bollinger Bands inside Keltner Channels.

    Squeeze ON means volatility has compressed — the bands have contracted
    inside the channels. It is a statement about RANGE, not about direction,
    and the momentum histogram is what conventionally supplies the direction on
    release. Treat that second part as unverified here: nothing on this project
    has made an indicator predict direction, and this one has not been tested
    on NDX intraday either.
    """
    if len(c) < max(BB_PERIOD, KC_PERIOD) + 1:
        return {}
    mid = _sma(c, BB_PERIOD)
    sd = _stdev(c, BB_PERIOD)
    if mid is None or sd is None:
        return {}
    bb_up, bb_dn = mid + BB_MULT * sd, mid - BB_MULT * sd

    tr = true_range(h, l, c)
    atr = _sma(tr, KC_PERIOD)
    kc_mid = _sma(c, KC_PERIOD)
    if atr is None or kc_mid is None:
        return {}
    kc_up, kc_dn = kc_mid + KC_MULT * atr, kc_mid - KC_MULT * atr

    on = bb_up < kc_up and bb_dn > kc_dn

    # Momentum: close minus the midpoint of (donchian mid, SMA), linear-fitted.
    w = KC_PERIOD
    hh, ll = max(h[-w:]), min(l[-w:])
    base = [( (hh + ll) / 2 + kc_mid ) / 2] * w
    ys = [c[-w:][i] - base[i] for i in range(w)]
    mom = _linreg_slope_value(ys)

    return {"on": on, "bb_up": bb_up, "bb_dn": bb_dn, "kc_up": kc_up,
            "kc_dn": kc_dn, "mid": mid, "atr": atr, "mom": mom,
            "width_ratio": ((bb_up - bb_dn) / (kc_up - kc_dn)) if kc_up > kc_dn else None}


def compute(ndx_px: float) -> Dict:
    from uw_ndx_technicals import qqq_bars
    bars = qqq_bars()
    if len(bars) < 30:
        return {}
    h = [_f(b.get("high")) for b in bars]
    l = [_f(b.get("low")) for b in bars]
    c = [_f(b.get("close")) for b in bars]
    if any(x is None for x in c + h + l):
        return {}

    q = c[-1]
    ratio = ndx_px / q if q else None
    if not ratio:
        return {}

    sq = ttm_squeeze(h, l, c)
    tr = true_range(h, l, c)
    atr = _sma(tr, ATR_PERIOD)

    # Opening range — the first N minutes, a standard scalper reference.
    orb = {}
    if len(bars) >= OPENING_RANGE_MIN:
        oh, ol = max(h[:OPENING_RANGE_MIN]), min(l[:OPENING_RANGE_MIN])
        orb = {"hi": oh * ratio, "lo": ol * ratio,
               "hi_pct": (oh / q - 1) * 100, "lo_pct": (ol / q - 1) * 100,
               "inside": ol <= q <= oh}

    return {
        "ndx": ndx_px, "qqq": q, "ratio": ratio, "bars": len(bars),
        "rsi": rsi(c),
        "atr_qqq": atr, "atr_ndx": (atr * ratio) if atr else None,
        "atr_pct": (atr / q * 100) if atr else None,
        "squeeze": ({**sq,
                     "bb_up_ndx": sq["bb_up"] * ratio, "bb_dn_ndx": sq["bb_dn"] * ratio,
                     "kc_up_ndx": sq["kc_up"] * ratio, "kc_dn_ndx": sq["kc_dn"] * ratio,
                     "mid_ndx": sq["mid"] * ratio} if sq else {}),
        "orb": orb,
    }


def trending_options(top: int = 8) -> List[Dict]:
    """
    Contracts with the most SINGLE-LEG volume today.

    Ranked on single-leg, never on raw volume — see the module docstring. A
    contract whose volume is entirely multi-leg is spread construction and says
    nothing about direction, however large it is.
    """
    try:
        r = requests.get(f"{BASE}/stock/NDX/oi-change",
                         headers={"Authorization": f"Bearer {os.getenv('UW_API_KEY')}"},
                         timeout=25)
        rows = r.json().get("data") or []
    except Exception:
        return []

    out = []
    for x in rows:
        vol = _f(x.get("volume")) or 0.0
        ml = _f(x.get("prev_multi_leg_volume")) or 0.0
        single = max(vol - ml, 0.0)
        if single <= 0:
            continue
        ask = _f(x.get("prev_ask_volume")) or 0.0
        bid = _f(x.get("prev_bid_volume")) or 0.0
        sym = str(x.get("option_symbol") or "")
        try:
            strike = int(sym[-8:]) / 1000.0
            typ = sym[-9].upper()
            ymd = sym[-15:-9]
            exp = f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}"
        except (ValueError, IndexError):
            continue
        out.append({
            "symbol": sym, "type": typ, "strike": strike, "expiry": exp,
            "volume": vol, "single": single,
            "ml_share": (ml / vol * 100) if vol else 0.0,
            "oi": _f(x.get("curr_oi")) or 0.0,
            "oi_change_pct": (_f(x.get("oi_change")) or 0.0) * 100,
            "premium": _f(x.get("prev_total_premium")) or 0.0,
            "last": _f(x.get("last_fill")),
            # Ask-side = buyer-initiated. Reported rather than translated into
            # "bullish": a bought put and a sold put are both put volume, and
            # the UW sentiment field that conflates them is already recorded as
            # useless on this project.
            "ask_share": (ask / (ask + bid) * 100) if (ask + bid) > 0 else None,
        })
    out.sort(key=lambda r: -r["single"])
    return out[:top]


def field_signals(s: Dict) -> Optional[Dict]:
    if not s:
        return None
    L = []
    sq = s.get("squeeze") or {}
    if sq:
        state = "🟠 SQUEEZE ON — range compressed" if sq.get("on") else "⚪ no squeeze"
        L.append(f"**TTM** {state}")
        if sq.get("width_ratio") is not None:
            L.append(f"`BB/KC ` {sq['width_ratio']:.2f}  (<1.00 = squeezed)")
        if sq.get("mom") is not None:
            L.append(f"`mom   ` {sq['mom']*s['ratio']:+,.0f} NDX pts "
                     f"({'rising' if sq['mom'] >= 0 else 'falling'})")
        L.append(f"`BB up ` NDX {sq['bb_up_ndx']:>9,.0f}\n"
                 f"`BB dn ` NDX {sq['bb_dn_ndx']:>9,.0f}")
    if s.get("rsi") is not None:
        L.append(f"`RSI14 ` {s['rsi']:.0f}")
    if s.get("atr_ndx"):
        # SCALE IT, OR IT IS ACTIVELY DANGEROUS.
        # This is a 14-period ATR on ONE-MINUTE bars, i.e. the typical move in
        # a single minute — 18 NDX points. Printed as "ATR, use for stop width"
        # a scalper would set an 18-point stop and be taken out immediately.
        # Scaled by sqrt(time) it answers the question actually being asked:
        # how far does NDX typically travel over the period I intend to hold.
        L.append(f"`ATR   ` {s['atr_ndx']:,.0f} pts per MINUTE ({s['atr_pct']:.2f}%)")
        horizons = " · ".join(
            f"{m}m ±{s['atr_ndx'] * math.sqrt(m):,.0f}" for m in (5, 15, 30))
        L.append(f"`typical` {horizons}  — stop width, NOT an entry trigger")
    orb = s.get("orb") or {}
    if orb:
        L.append(f"\n**Opening range** ({OPENING_RANGE_MIN}m)  "
                 f"{'inside' if orb['inside'] else 'broken out'}\n"
                 f"`OR hi ` NDX {orb['hi']:>9,.0f}  ({orb['hi_pct']:+.2f}%)\n"
                 f"`OR lo ` NDX {orb['lo']:>9,.0f}  ({orb['lo_pct']:+.2f}%)")
    return {"name": f"Scalper signals — QQQ 1m, {s['bars']} bars (est. NDX levels)",
            "value": "\n".join(L)[:1020], "inline": False}


def field_trending(rows: List[Dict]) -> Optional[Dict]:
    if not rows:
        return None
    L = ["`  strike  exp     vol   spread%  ask%`"]
    for r in rows[:6]:
        ask = f"{r['ask_share']:.0f}%" if r["ask_share"] is not None else "  —"
        L.append(f"`{r['strike']:>8,.0f}{r['type']} {r['expiry'][5:]} "
                 f"{r['single']:>6,.0f}  {r['ml_share']:>5.0f}%  {ask:>4}`")
    L.append("\nRanked on SINGLE-LEG volume. `spread%` is the share that was "
             "multi-leg — high means spread construction, which carries no "
             "directional view. `ask%` is buyer-initiated share; it is not "
             "translated into bullish/bearish because a bought put and a sold "
             "put are both put volume.")
    return {"name": "Most active contracts today", "value": "\n".join(L)[:1020],
            "inline": False}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from uw_ndx_monitor import snapshot
    snap = snapshot()
    s = compute(snap["price"]) if snap else {}
    if s:
        sq = s["squeeze"]
        print(f"NDX {s['ndx']:,.0f}  ({s['bars']} QQQ 1m bars)")
        print(f"  TTM squeeze : {'ON — compressed' if sq.get('on') else 'off'}"
              f"   BB/KC {sq.get('width_ratio', 0):.2f}")
        print(f"  momentum    : {sq['mom']*s['ratio']:+,.0f} NDX pts")
        print(f"  RSI14       : {s['rsi']:.0f}")
        print(f"  ATR (1 min) : {s['atr_ndx']:,.0f} pts ({s['atr_pct']:.2f}%)")
        print("  typical move: " + " · ".join(
            f"{m}m ±{s['atr_ndx']*math.sqrt(m):,.0f}" for m in (5, 15, 30, 60)))
        print(f"  BB          : {sq['bb_dn_ndx']:,.0f} .. {sq['bb_up_ndx']:,.0f}")
        print(f"  KC          : {sq['kc_dn_ndx']:,.0f} .. {sq['kc_up_ndx']:,.0f}")
        o = s.get("orb") or {}
        if o:
            print(f"  opening rng : {o['lo']:,.0f} .. {o['hi']:,.0f}  "
                  f"({'inside' if o['inside'] else 'BROKEN OUT'})")
    print("\nMOST ACTIVE CONTRACTS (single-leg volume)")
    print(f"  {'strike':>9} {'exp':>10} {'single':>8} {'total':>8} {'spread%':>8} {'ask%':>6} {'OI':>8}")
    for r in trending_options(10):
        ask = f"{r['ask_share']:.0f}%" if r["ask_share"] is not None else "—"
        print(f"  {r['strike']:>8,.0f}{r['type']} {r['expiry']:>10} {r['single']:>8,.0f} "
              f"{r['volume']:>8,.0f} {r['ml_share']:>7.0f}% {ask:>6} {r['oi']:>8,.0f}")
