#!/usr/bin/env python3
"""
NDX intraday monitor — trend, volume, dealer flow.

WHAT NDX ACTUALLY GIVES YOU ON THIS PLAN, measured 2026-09-14:

    /stock/NDX/spot-exposures   ~103 rows/day, ~2.5 min apart, carrying price
                                AND gamma/vanna/charm per 1% move. Timestamps
                                are UTC: the series runs roughly 06:30-16:00 ET,
                                so it INCLUDES pre-market.
    /stock/NDX/gex-levels       put wall / gamma flip / magnet / call wall.
    /stock/NDX/greek-exposure   251 daily rows.
    /stock/NDX/ohlc/*           422. NO price series, NO volume.
    /stock/NDX/flow-alerts      0 rows.

Two consequences shape this module:

1. TREND is built from the spot-exposures price series, because it is the only
   NDX price series that exists here. It begins in PRE-MARKET, so "since open"
   is not the 09:30 open — the card names the actual start time in ET rather
   than implying a regular-session number.

2. VOLUME cannot be NDX's own — an index has no share volume. QQQ 1-minute
   volume stands in, and is LABELLED as a proxy everywhere it appears. QQQ
   tracks the same 100 names, so participation is a fair read; it is not NDX
   option volume and must not be read as such.

WHAT THIS DOES NOT DO
It does not tell you which way to trade. On this project dealer gamma predicts
move MAGNITUDE (SPY 0.53% at high gamma vs 0.87% at low, t+2.9, survived a
trailing-vol control) and has NEVER predicted direction: GEX-timed vol was null
at |t|<1, and gamma walls as barriers failed (t+1.98 pooled, with AMD alone
contributing 70% of it). Sixteen hypotheses have nulled on this data.

So trend and volume here are DESCRIPTIVE — they tell you what is happening, not
what will happen. The defensible use of the gamma line is sizing and stop
width. Anything stronger is the inference the nulls refuse to support.
"""

import os
from datetime import datetime
from typing import Dict, List, Optional

import requests

BASE = "https://api.unusualwhales.com/api"

# Fire only on a real change. A channel that posts every poll gets muted, and a
# muted channel is worth less than no channel.
VOL_SURGE_MULT = 2.0      # 1m volume vs the session's own average
MIN_MOVE_PCT = 0.25       # re-alert only after price moves this much again
EXTREME_EPS_PCT = 0.05    # within this of session high/low counts as a test



# TIMESTAMPS FROM THIS API ARE UTC, NOT ET.
#
# The `time` field ends in Z ("2026-09-14T15:29:36.000000Z"). Slicing [11:16]
# and labelling it ET printed "since 10:30 ET" on a card meant for trading,
# when 10:30Z is 06:30 ET — PRE-MARKET. The card then carried a caveat saying
# the series misses the first hour of the session, which was the opposite of
# true: it starts two hours BEFORE the open and includes pre-market.
#
# Wrong by four hours in the label and wrong in the caveat drawn from it.
def _et(iso: str) -> str:
    """'HH:MM' in US/Eastern from a UTC ISO string."""
    try:
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        t = str(iso).replace("Z", "+00:00")
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M")
    except Exception:
        return str(iso)[11:16]


def _key() -> Optional[str]:
    return os.getenv("UW_API_KEY")


def _get(path: str, params: Dict = None) -> Optional[List[Dict]]:
    try:
        r = requests.get(BASE + path, params=params or {},
                         headers={"Authorization": f"Bearer {_key()}"}, timeout=20)
        if r.status_code != 200:
            return None
        d = r.json().get("data")
        return d if isinstance(d, list) else ([d] if d else None)
    except Exception:
        return None


def _f(x) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def ndx_series() -> List[Dict]:
    """Intraday NDX rows, OLDEST FIRST.

    The sort is not cosmetic. This endpoint returns oldest-first and the daily
    OHLC one does too — assuming newest-first is what made INTC read -82.5%
    instead of -26.5%. Sorting explicitly means the assumption cannot rot.
    """
    rows = _get("/stock/NDX/spot-exposures") or []
    rows.sort(key=lambda r: str(r.get("time") or ""))
    return [r for r in rows if _f(r.get("price"))]


def qqq_volume() -> Dict:
    """QQQ 1-minute volume — the NDX volume PROXY. Regular session only."""
    rows = _get("/stock/QQQ/ohlc/1m", {"limit": 500}) or []
    rows = [r for r in rows if str(r.get("market_time")) == "r"]
    rows.sort(key=lambda r: str(r.get("start_time") or ""))
    if not rows:
        return {}
    total = sum(_f(r.get("volume")) or 0.0 for r in rows)

    # DROP THE FINAL BAR. It is the minute currently in progress, so it holds a
    # fraction of a minute's volume. Measured live at 15:05: comparing it to the
    # session average gave 0.05x — the surge trigger could essentially never
    # fire, and the card would report a volume collapse during normal trade.
    # Compare the last COMPLETE bar against the average of complete bars.
    closed = rows[:-1]
    if not closed:
        return {"total": total, "bars": len(rows), "rel": None,
                "at": _et(rows[-1].get("start_time"))}
    vols = [_f(r.get("volume")) or 0.0 for r in closed]
    avg = sum(vols) / len(vols)
    last = vols[-1]
    return {"last": last, "avg": avg, "total": total, "bars": len(closed),
            "rel": (last / avg) if avg > 0 else None,
            "at": _et(closed[-1].get("start_time"))}


def snapshot() -> Dict:
    """Everything the card needs, in one place."""
    s = ndx_series()
    if not s:
        return {}
    px = [_f(r["price"]) for r in s]
    first, last = px[0], px[-1]
    hi, lo = max(px), min(px)

    # Trend over the most recent stretch, not the whole window — a session that
    # rallied then stalled should not keep reading "up".
    tail = px[-12:] if len(px) >= 12 else px
    recent = (tail[-1] / tail[0] - 1) * 100 if tail[0] else 0.0

    g = _f(s[-1].get("gamma_per_one_percent_move_dir"))
    v = _f(s[-1].get("vanna_per_one_percent_move_dir"))
    c = _f(s[-1].get("charm_per_one_percent_move_dir"))

    lv = (_get("/stock/NDX/gex-levels") or [{}])[0] or {}
    return {
        "price": last, "open": first, "hi": hi, "lo": lo,
        "from_open_pct": (last / first - 1) * 100 if first else 0.0,
        "recent_pct": recent,
        "range_pct": (hi / lo - 1) * 100 if lo else 0.0,
        # Where in the day's range price sits: 0 = at the low, 100 = at the high.
        "range_pos": ((last - lo) / (hi - lo) * 100) if hi > lo else 50.0,
        "since": _et(s[0].get("time")),
        "at": _et(s[-1].get("time")),
        "gamma": g, "vanna": v, "charm": c,
        "put_wall": _f(lv.get("put_wall")), "call_wall": _f(lv.get("call_wall")),
        "gamma_flip": _f(lv.get("gamma_flip")), "magnet": _f(lv.get("gamma_magnet")),
        "vol": qqq_volume(),
    }


def triggers(snap: Dict, state: Dict) -> List[str]:
    """Why this alert is firing. Empty list means stay quiet."""
    out = []
    if not snap:
        return out
    px = snap["price"]

    if state.get("last_price") is None:
        out.append("first read of the session")
    else:
        moved = abs(px / state["last_price"] - 1) * 100
        if moved >= MIN_MOVE_PCT:
            out.append(f"moved {moved:.2f}% since last alert")

    # EDGE-TRIGGERED, NOT LEVEL-TRIGGERED.
    #
    # These three conditions PERSIST — price sits at the session high for many
    # polls, volume stays elevated through a busy stretch. Firing on the
    # condition rather than on entering it re-posts every cycle for as long as
    # it lasts. Caught live: two consecutive run_once calls seconds apart both
    # posted, because a 2.70x volume reading was still true the second time.
    #
    # So each records whether it was already true, and fires only on the
    # transition into it. That is also why they are cleared below — a condition
    # that ends must be able to fire again when it returns.
    hi, lo = snap["hi"], snap["lo"]
    at_hi = bool(hi and px >= hi * (1 - EXTREME_EPS_PCT / 100))
    at_lo = bool(lo and px <= lo * (1 + EXTREME_EPS_PCT / 100))
    if at_hi and not state.get("was_at_hi"):
        out.append("made a new session high")
    if at_lo and not state.get("was_at_lo"):
        out.append("made a new session low")
    state["was_at_hi"], state["was_at_lo"] = at_hi, at_lo

    rel = (snap.get("vol") or {}).get("rel")
    surging = bool(rel and rel >= VOL_SURGE_MULT)
    if surging and not state.get("was_surging"):
        out.append(f"volume surged to {rel:.1f}× session average (QQQ proxy)")
    state["was_surging"] = surging

    g = snap.get("gamma")
    pg = state.get("last_gamma")
    if g is not None and pg is not None and (g > 0) != (pg > 0):
        out.append(f"dealer gamma flipped {'short → long' if g > 0 else 'long → short'}")

    return out


def build_embed(snap: Dict, why: List[str]) -> Dict:
    px = snap["price"]
    up = snap["recent_pct"] >= 0
    arrow = "▲" if up else "▼"

    ladder = []
    rungs = [(snap.get("call_wall"), "🟢 call wall"), (snap.get("magnet"), "⚪ magnet"),
             (snap.get("gamma_flip"), "🟡 gamma flip"), (snap.get("put_wall"), "🔴 put wall")]
    rungs = [(v, l) for v, l in rungs if v]
    rungs.append((px, "➤ **NDX**"))
    for v, l in sorted(rungs, key=lambda x: -x[0]):
        if l.startswith("➤"):
            ladder.append(f"`{v:>9,.0f}`  {l}")
        else:
            ladder.append(f"`{v:>9,.0f}`  {l}  ({(v/px-1)*100:+.2f}%)")

    vol = snap.get("vol") or {}
    volline = "—"
    if vol.get("rel"):
        volline = (f"{vol['rel']:.1f}× session avg  ·  {vol['last']:,.0f} sh in the "
                   f"{vol['at']} bar  ·  {vol['total']/1e6:.1f}M today")

    g = snap.get("gamma")
    if g is None:
        regime = "dealer gamma unavailable"
    elif g > 0:
        regime = ("**long gamma** — dealers DAMPEN moves → ranges compress, breakouts "
                  "tend to fail, tighter stops survive")
    else:
        regime = ("**short gamma** — dealers AMPLIFY moves → wider ranges and trend "
                  "extension; widen stops or cut size")

    return {
        "title": f"📈 NDX {arrow} {px:,.0f}   ({snap['recent_pct']:+.2f}% recent)",
        "description": (
            f"**{' · '.join(why)}**\n\n"
            f"{chr(10).join(ladder)}\n"
        ),
        "color": 3066993 if up else 15158332,
        "fields": [
            {"name": "Trend", "value":
             f"{snap['from_open_pct']:+.2f}% since {snap['since']} ET\n"
             f"{snap['recent_pct']:+.2f}% last ~30 min\n"
             f"{snap['range_pos']:.0f}% up the day's range", "inline": True},
            {"name": "Range", "value":
             f"hi {snap['hi']:,.0f}\nlo {snap['lo']:,.0f}\n"
             f"{snap['range_pct']:.2f}% wide", "inline": True},
            {"name": "Volume (QQQ proxy)", "value": volline, "inline": False},
            {"name": "Dealer positioning", "value": regime, "inline": False},
            *( [snap["tech_field"]] if snap.get("tech_field") else [] ),
            {"name": "Read this before trading it", "value":
             "Trend and volume here are DESCRIPTIVE — what has happened, not what "
             "comes next. Dealer gamma predicts move SIZE on this data (t+2.9), "
             "never DIRECTION: gamma-timed direction nulled every way it was "
             "tested. Use the regime for SIZING and STOP WIDTH.\n"
             "NDX has no share volume — the figure above is QQQ. The NDX series "
             f"begins {snap['since']} ET, which includes PRE-MARKET, so "
             "\"since open\" is not the 09:30 open.", "inline": False},
        ],
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "Unusual Whales bot · NDX monitor · not trade logic"},
    }


def webhook() -> Optional[str]:
    """NDX channel, degrading to the UW one rather than to None."""
    return os.getenv("DISCORD_NDX_WEBHOOK_URL") or os.getenv("DISCORD_WEBHOOK_URL")


def run_once(state: Dict) -> Optional[Dict]:
    """Poll, decide, post. Returns the snapshot when it alerted, else None."""
    from uw_discord import post_embed
    snap = snapshot()
    if not snap:
        return None

    # Technicals are DESCRIPTIVE and LOGGED — they never gate an alert. See
    # uw_ndx_technicals for why: the closest thing measured on this project
    # (technical gates over 104,924 obs) had the traded set UNDERPERFORM the
    # skipped set, and there is not enough 1-minute history to test the
    # intraday version. Logging forward is how it becomes evidence.
    try:
        import uw_ndx_technicals as _t
        tech = _t.compute(snap["price"])
        if tech:
            _t.log(tech)
            snap["tech_field"] = _t.field(tech)
    except Exception:
        pass

    why = triggers(snap, state)
    if not why:
        return None
    if post_embed(build_embed(snap, why), webhook()):
        state["last_price"] = snap["price"]
        state["last_gamma"] = snap.get("gamma")
        return snap
    return None


if __name__ == "__main__":
    import json
    st = {}
    s = snapshot()
    print(json.dumps({k: v for k, v in s.items() if k != "vol"}, indent=2, default=str))
    print("triggers:", triggers(s, st))
