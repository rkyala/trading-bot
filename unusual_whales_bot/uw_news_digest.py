#!/usr/bin/env python3
"""
Curated news digest -> Discord.

WHAT THIS IS, AND WHAT IT IS NOT
This is SITUATIONAL AWARENESS, not a trading signal. Nothing here has been
shown to predict returns, and it cannot be: /news/headlines silently ignores
its `date` parameter (a request for 2026-09-03 returns 2026-09-10 rows) and
caps at limit=100, so the feed is today-only with no pagination. There is no
history to backtest against. Any claim that news sentiment adds edge would
need forward collection first - weeks of it.

So this digest is scored, ranked and posted for a human to read. It does NOT
feed the entry or exit path, and it should not until someone measures it.

ON SENTIMENT BACKENDS
UW ships a `sentiment` field on every headline. It is DEAD: measured
2026-09-10, it returned the string "neutral" on 100 of 100 headlines, and
`tags` was empty on all 100. Same shape as the useless `sentiment` field on
UW flow alerts. A first version of this digest read it faithfully and printed
+0.00 on every line.

So the backend is a real choice, not a formality:

  "uw"       REFUSES TO RUN. Kept only so the dead field cannot be selected
             by accident and mistaken for working sentiment.
  "lexicon"  DEFAULT. A finance word list scored per headline. Crude, but it
             has no dependencies and it actually varies with the text.
  "finbert"  ProsusAI/finbert. Needs transformers + torch (~2GB). This is the
             only backend that reads the sentence rather than counting words,
             and with UW's field dead it adds genuinely new information.

Note what still cannot be claimed for ANY backend: that sentiment predicts
returns. The feed is today-only, so there is no history to test against.

CURATION
100 raw headlines is noise. The digest keeps what is plausibly actionable:
  - anything on a ticker currently HELD (position risk beats novelty)
  - anything flagged is_major
  - the strongest-sentiment remainder
deduplicated by ticker, capped so a Discord embed stays readable.

SECURITY
Posting goes through UWBot._discord_post, which scrubs live credential values
out of the payload immediately before sending and refuses to send if the scrub
itself fails. The webhook URL is read from the environment (populated from
.env.local) and never logged. Headline text is third-party content echoed to
an external surface, so it is truncated and stripped of backticks/@ mentions
rather than passed through raw.
"""

import math
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = "https://api.unusualwhales.com/api"
SENTIMENT_BACKEND = os.getenv("SENTIMENT_BACKEND", "lexicon")  # lexicon | finbert | uw(dead)

# ---------------------------------------------------------------------------
# DESTINATION. News, FDA catalysts and insider buys go to their OWN channel,
# NOT the UW trade-alert channel.
#
# Trade alerts are things the bot DID — a fill, a stop, an exit. News is
# context a human reads. Mixing them means the entries and stops get buried
# under headlines, and the signal-to-noise of the channel you actually act on
# collapses.
#
# Falls back to DISCORD_WEBHOOK_URL so a missing news webhook degrades to the
# old behaviour rather than silently posting nothing.
# ---------------------------------------------------------------------------
def news_webhook() -> Optional[str]:
    return os.getenv("DISCORD_NEWS_WEBHOOK_URL") or os.getenv("DISCORD_WEBHOOK_URL")
MAX_ITEMS = 10
HEADLINE_CHARS = 180

# ---------------------------------------------------------------------------
# CADENCE. Polling and POSTING are deliberately different rates.
#
# The job runs every POLL (5 min) so a major headline is seen quickly, but the
# consolidated digest only posts every DIGEST_EVERY_MIN (30 min). A channel
# that fires every five minutes trains the reader to ignore it, which is worse
# than silence - the bot opened five positions unnoticed on Sep 8 for exactly
# that reason.
#
# The escape hatch is URGENT: a single headline scoring above URGENT_SCORE on
# a HELD name, or an is_major headline above URGENT_MAJOR, posts immediately
# rather than waiting up to 30 minutes. Urgent alerts are deduplicated by
# headline so a repeated poll cannot re-fire the same story.
# ---------------------------------------------------------------------------
DIGEST_EVERY_MIN = 30
URGENT_SCORE = 0.90      # on a ticker currently held
URGENT_MAJOR = 0.95      # is_major, any ticker
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", ".news_digest_state.json")


def _f(v, d=0.0):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


def _clean(text: str) -> str:
    """
    Headlines are third-party text going to an external surface.

    Strip Discord control characters so a headline cannot ping a channel or
    break out of the embed's formatting, and truncate - embeds have hard
    field limits and a long headline silently drops the whole message.
    """
    t = " ".join(str(text or "").split())
    t = t.replace("`", "'").replace("@everyone", "@ everyone").replace("@here", "@ here")
    t = t.replace("@", "@​")
    return t[:HEADLINE_CHARS] + ("..." if len(t) > HEADLINE_CHARS else "")


# --------------------------------------------------------------------- score

def score_headline(row: Dict) -> Optional[float]:
    """
    Sentiment in [-1, +1]. The ONLY place the backend is chosen.

    "uw"      the sentiment UW already supplies with the headline
    "finbert" ProsusAI/finbert over the headline text; requires transformers
    """
    if SENTIMENT_BACKEND == "uw":
        # Deliberately fatal. UW's sentiment is the constant "neutral"; using
        # it produces a digest of zeros that LOOKS like working sentiment.
        # Silently-neutral is exactly how the dead all_opening_trades gate and
        # the "Tier 2 exits: ACTIVE" banner survived for weeks here.
        raise RuntimeError(
            "SENTIMENT_BACKEND=uw is disabled: UW returns 'neutral' on 100/100 "
            "headlines. Use lexicon (no deps) or finbert (needs transformers)."
        )

    if SENTIMENT_BACKEND == "lexicon":
        return _lexicon_score(row.get("headline", ""))

    if SENTIMENT_BACKEND == "finbert":
        try:
            from transformers import pipeline
        except ImportError:
            # Fail loudly rather than silently returning UW's number while
            # claiming to be FinBERT - that mislabelling is exactly how the
            # "Tier 2 exits: ACTIVE" banner misled this project twice.
            raise RuntimeError(
                "SENTIMENT_BACKEND=finbert but transformers is not installed. "
                "pip install transformers torch, or use SENTIMENT_BACKEND=uw."
            )
        global _PIPE
        if "_PIPE" not in globals() or _PIPE is None:
            _PIPE = pipeline("sentiment-analysis", model="ProsusAI/finbert")
        out = _PIPE(_clean(row.get("headline", ""))[:512])[0]
        sign = {"positive": 1.0, "negative": -1.0}.get(out["label"].lower(), 0.0)
        return sign * float(out["score"])

    raise RuntimeError(f"unknown SENTIMENT_BACKEND={SENTIMENT_BACKEND!r}")


# Small finance lexicon. Not a model - a transparent fallback so the digest
# works with zero dependencies. Terms chosen for headline language, not prose.
_POS = {
    "beats", "beat", "raises", "raised", "surges", "surge", "jumps", "soars",
    "upgrade", "upgraded", "outperform", "record", "approval", "approved",
    "wins", "awarded", "expands", "boosts", "boost", "growth", "profit",
    "buyback", "dividend", "acquires", "acquisition", "partnership", "rally",
    "strong", "higher", "gains", "tops", "exceeds", "bullish", "breakthrough",
}
_NEG = {
    "misses", "miss", "cuts", "cut", "plunges", "plunge", "falls", "slumps",
    "downgrade", "downgraded", "underperform", "probe", "investigation",
    "lawsuit", "sues", "recall", "halts", "halted", "bankruptcy", "default",
    "layoffs", "warns", "warning", "loss", "losses", "weak", "lower", "drops",
    "declines", "bearish", "fraud", "resigns", "delays", "delayed", "rejects",
    "reject", "threatens", "sanctions", "tariff", "strike",
}


def _lexicon_score(text: str) -> float:
    words = "".join(c.lower() if (c.isalnum() or c.isspace()) else " "
                    for c in str(text or "")).split()
    p = sum(1 for w in words if w in _POS)
    n = sum(1 for w in words if w in _NEG)
    if p + n == 0:
        return 0.0
    return max(-1.0, min(1.0, (p - n) / (p + n)))


# ---------------------------------------------------------------------- data

def fetch_headlines(limit: int = 100) -> List[Dict]:
    """limit is capped at 100 by the API; 200 returns an explicit error."""
    import requests
    key = os.getenv("UW_API_KEY")
    if not key:
        return []
    try:
        r = requests.get(f"{BASE}/news/headlines",
                         params={"limit": min(limit, 100)},
                         headers={"Authorization": f"Bearer {key}",
                                  "Accept": "application/json"},
                         timeout=20)
        return r.json().get("data") or [] if r.status_code == 200 else []
    except Exception:
        return []


def held_symbols() -> List[str]:
    import json
    for path in ("open_positions.json", "../open_positions.json"):
        try:
            with open(path) as fh:
                d = json.load(fh)
            vals = d.values() if isinstance(d, dict) else d
            return sorted({str(p.get("symbol") or "").upper() for p in vals if p.get("symbol")})
        except Exception:
            continue
    return []


def curate(rows: List[Dict], held: List[str]) -> List[Dict]:
    """Rank: held tickers first, then major flags, then sentiment strength."""
    heldset = set(held)
    out, seen = [], set()
    for r in rows:
        tks = [str(t).upper() for t in (r.get("tickers") or []) if t]
        s = score_headline(r)
        if s is None:
            continue
        hit = sorted(heldset.intersection(tks))
        key = tks[0] if tks else _clean(r.get("headline"))[:40]
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "headline": _clean(r.get("headline")),
            "tickers": tks[:4],
            "held": hit,
            "major": bool(r.get("is_major")),
            "sent": s,
            "at": str(r.get("created_at") or "")[11:16],
            "source": _clean(r.get("source"))[:24],
        })
    out.sort(key=lambda x: (len(x["held"]) > 0, x["major"], abs(x["sent"])), reverse=True)
    return out[:MAX_ITEMS]


# ------------------------------------------------------------------- display

def build_embed(items: List[Dict], held: List[str]) -> Dict:
    if not items:
        return {}
    pos = sum(1 for i in items if i["sent"] > 0.15)
    neg = sum(1 for i in items if i["sent"] < -0.15)
    lines = []
    for i in items:
        arrow = "🟢" if i["sent"] > 0.15 else ("🔴" if i["sent"] < -0.15 else "⚪")
        tag = ",".join(i["tickers"]) or "—"
        mark = " ⚠️HELD" if i["held"] else ""
        lines.append(f"{arrow} `{tag}`{mark} {i['sent']:+.2f} · {i['at']} · {i['headline']}")
    body = "\n".join(lines)[:3900]
    return {
        "title": f"📰 News Digest — {pos} positive / {neg} negative",
        "description": body,
        "color": 3447003 if pos >= neg else 15158332,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": (f"backend={SENTIMENT_BACKEND} · situational awareness only, "
                            f"not a trading signal · held: {', '.join(held) or 'none'}")},
    }


LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "news_log.jsonl")


def append_log(rows: List[Dict]) -> int:
    """
    Append every scored headline to a JSONL, deduplicated.

    THIS IS THE POINT OF THE WHOLE EXERCISE.

    News sentiment cannot be backtested today because /news/headlines is
    today-only - it silently ignores `date` and caps at 100 rows. The reason
    there is no history is simply that nobody has been recording it. Every
    30-minute run appends what it saw, so in four to six weeks there IS a
    dataset, and the same controls used on flow and gamma can be pointed at
    it: forward returns, market adjustment, non-overlapping windows,
    per-ticker sign.

    Dedup is by (created_at, headline) since polls overlap by design - the
    buffer refills every ~84 minutes and we poll every 30.
    """
    import json
    seen = set()
    try:
        with open(LOG_PATH) as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                    seen.add((o.get("created_at"), o.get("headline")))
                except Exception:
                    continue
    except FileNotFoundError:
        pass

    n = 0
    try:
        with open(LOG_PATH, "a") as fh:
            for r in rows:
                s_ = score_headline(r)
                if s_ is None:
                    continue
                key = (str(r.get("created_at")), _clean(r.get("headline")))
                if key in seen:
                    continue
                seen.add(key)
                fh.write(json.dumps({
                    "created_at": str(r.get("created_at")),
                    "logged_at": datetime.utcnow().isoformat(),
                    "headline": _clean(r.get("headline")),
                    "tickers": [str(t).upper() for t in (r.get("tickers") or []) if t],
                    "is_major": bool(r.get("is_major")),
                    "source": _clean(r.get("source"))[:32],
                    "sentiment": s_,
                    "backend": SENTIMENT_BACKEND,
                }) + "\n")
                n += 1
    except Exception as e:
        print(f"  log append failed: {e}")
    return n


# ---------------------------------------------------------------------------
# INSIDER BUY ALERTS
#
# NOT a trading signal. The 21-day backtest on a 500-ticker screener universe
# came back NULL (buys +1.67%, t+1.25, drop-one-ticker worst t+0.98), and an
# earlier t+2.92 collapsed once the universe was not hand-picked. So this is
# the same category as the news digest: a human should see a CEO putting $10M
# of their own money into their own stock, whether or not it predicts a return.
#
# Only DISCRETIONARY buys count. UW pre-computes the split, and most insider
# activity is pre-scheduled 10b5-1 — a plan set six months ago carries no
# information about today, so premium_10b5 is subtracted out.
# ---------------------------------------------------------------------------
INSIDER_MIN_BUY = 1_000_000     # discretionary dollars; below this is noise


def insider_buys(symbols: List[str]) -> List[Dict]:
    """Today's large discretionary insider BUYS on the given tickers."""
    import requests
    from datetime import date as _date
    key = os.getenv("UW_API_KEY")
    if not key or not symbols:
        return []
    today = _date.today().isoformat()
    out = []
    for sym in symbols[:25]:                 # bound the work per run
        try:
            r = requests.get(f"{BASE}/insider/{sym}/ticker-flow",
                             params={"limit": 5},
                             headers={"Authorization": f"Bearer {key}",
                                      "Accept": "application/json"},
                             timeout=15)
            if r.status_code != 200:
                continue
            for row in (r.json().get("data") or []):
                if str(row.get("date") or "")[:10] != today:
                    continue
                prem = _f(row.get("premium"), 0.0)
                p10 = _f(row.get("premium_10b5"), 0.0)
                disc = prem - p10            # the informative portion
                if disc >= INSIDER_MIN_BUY:
                    out.append({"symbol": sym, "disc": disc,
                                "insiders": int(_f(row.get("uniq_insiders"), 0) or 0),
                                "price": _f(row.get("avg_price"), 0.0)})
        except Exception:
            continue
    return sorted(out, key=lambda x: -x["disc"])


def build_insider_embed(it: Dict) -> Dict:
    return {
        "title": f"💰 INSIDER BUY — {it['symbol']}  ${it['disc']:,.0f}",
        "description": (f"{it['insiders']} insider(s) bought "
                        f"~${it['disc']:,.0f} discretionary "
                        f"(10b5-1 excluded) around ${it['price']:,.2f}"),
        "color": 3066993,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "open-market, non-10b5-1 · context only — the "
                           "21-day backtest on this was null"},
    }


# ---------------------------------------------------------------------------
# FDA CATALYST CALENDAR — once per session.
#
# Binary events: PDUFA dates, AdComm meetings, FDA decisions, trial readouts.
# Unlike fundamentals (quarterly) or 13F (45-day lag), these are DATED and
# short-horizon, which is the one shape that fits a bot holding days.
#
# The most defensible use is a VETO, not a signal: do not hold a name through
# a binary readout. That needs no edge to justify — it avoids a coin flip.
#
# TWO API TRAPS, both hit while wiring this:
#   1. The filter params are announced_date_min/max and target_date_min/max.
#      Guessing `date=` or `min_date=` returns 2021 rows with a 200 — the
#      endpoint ignores unknown params rather than erroring.
#   2. target_date is often FUZZY: "2026-H2", "2027-Q1", "2026-MID". Only ISO
#      dates are actionable; the rest are filtered out of the alert.
# ---------------------------------------------------------------------------
FDA_LOOKAHEAD_DAYS = 14

# Publish once a day, at or after this LOCAL time. 09:00 puts it half an hour
# after the open — past the opening noise, while there is still a session left
# to act on a name that has a readout coming.
#
# The day key is the LOCAL date, not UTC. datetime.utcnow() rolls over at 19:00
# CDT, so a UTC key would let the alert re-fire the same trading afternoon. It
# happens to be masked right now by the market-hours guard ending at 15:05,
# which is exactly the kind of latent bug that surfaces the day a schedule
# changes.
FDA_PUBLISH_AFTER_HOUR = 9


def _iso_date(v) -> Optional[str]:
    """Return YYYY-MM-DD only if the value really is one. Rejects 2026-H2 etc."""
    t = str(v or "")[:10]
    if len(t) != 10 or t[4] != "-" or t[7] != "-":
        return None
    try:
        from datetime import date as _d
        _d.fromisoformat(t)
        return t
    except Exception:
        return None


def fda_catalysts(held: List[str]) -> List[Dict]:
    """Dated FDA catalysts inside the look-ahead window."""
    import requests
    from datetime import date as _d, timedelta as _td
    key = os.getenv("UW_API_KEY")
    if not key:
        return []
    today = _d.today()
    hi = today + _td(days=FDA_LOOKAHEAD_DAYS)
    try:
        r = requests.get(f"{BASE}/market/fda-calendar",
                         params={"target_date_min": today.isoformat(),
                                 "target_date_max": hi.isoformat(), "limit": 100},
                         headers={"Authorization": f"Bearer {key}",
                                  "Accept": "application/json"}, timeout=20)
        rows = r.json().get("data") or [] if r.status_code == 200 else []
    except Exception:
        return []

    heldset = {h.upper() for h in held}
    out = []
    for x in rows:
        d = _iso_date(x.get("target_date"))
        if not d or not (today.isoformat() <= d <= hi.isoformat()):
            continue
        tk = str(x.get("ticker") or "").upper()
        out.append({
            "ticker": tk, "date": d,
            "days": (_d.fromisoformat(d) - today).days,
            "event": _clean(x.get("event_type"))[:40],
            "drug": _clean(x.get("drug"))[:28],
            "held": tk in heldset,
            "has_options": bool(x.get("has_options")),
        })
    # Held names first, then soonest.
    out.sort(key=lambda z: (not z["held"], z["days"]))
    out = out[:15]
    # Attach the market's expected move to the event (one call per ticker,
    # deduplicated — several catalysts can share a ticker).
    cache: Dict[str, Optional[float]] = {}
    for it in out:
        t = it["ticker"]
        if t not in cache:
            cache[t] = expected_move(t, max(it["days"], 1))
        it["exp_move"] = cache[t]
    return out


def expected_move(ticker: str, horizon_days: int) -> Optional[float]:
    """
    The market's own expected move to the event, as a fraction.

    WHY NOT FinBERT FOR THIS
    FinBERT scores SENTIMENT of text. A scheduled PDUFA date has no sentiment —
    the event has not happened, and "PDUFA Date for zidesamtinib" is neutral by
    construction. FinBERT also has no clinical knowledge: it cannot tell a
    pivotal Phase 3 readout from a label expansion. Asking it for "significance"
    would produce a confident number with nothing behind it.

    Implied move is the opposite: thousands of participants pricing a KNOWN
    binary date with real money. It is already a significance score, and it is
    the best magnitude estimator on this data — the vol-forecast test gave a
    ridge model the most favourable possible target and implied still won
    (test rho 0.522 vs 0.512 model vs 0.466 trailing RV).

    /interpolated-iv is used rather than the screener because it is per-ticker
    (small caps like NUVL fall outside the screener's top rows) and returns IV
    at FIXED day horizons, so the node nearest the event can be picked.
    """
    import requests
    key = os.getenv("UW_API_KEY")
    if not key:
        return None
    try:
        r = requests.get(f"{BASE}/stock/{ticker}/interpolated-iv",
                         headers={"Authorization": f"Bearer {key}",
                                  "Accept": "application/json"}, timeout=15)
        rows = r.json().get("data") or [] if r.status_code == 200 else []
    except Exception:
        return None
    best, gap = None, None
    for row in rows:
        d = _f(row.get("days"))
        im = _f(row.get("implied_move_perc"))
        if d is None or im is None or d <= 0 or im <= 0:
            continue
        g = abs(d - horizon_days)
        if gap is None or g < gap:
            best, gap = (d, im), g
    if not best:
        return None
    d, im = best
    # sqrt-time rescale when no node lands on the event horizon
    return im * math.sqrt(horizon_days / d) if d != horizon_days else im


def build_fda_embed(items: List[Dict]) -> Dict:
    held_n = sum(1 for i in items if i["held"])
    lines = []
    for i in items:
        mark = " ⚠️HELD" if i["held"] else ""
        em = i.get("exp_move")
        move = f" · **±{em*100:.1f}%** priced" if em else ""
        lines.append(f"`{i['ticker']:<6}` {i['date']} (+{i['days']}d){mark} · "
                     f"{i['event']} · {i['drug']}{move}")
    # Ranked by what the market thinks is at stake, not by our guess.
    lines.append("")
    lines.append("_±% is the options market's expected move to the event date —"
                 " its own significance score._")
    return {
        "title": f"🧪 FDA Catalysts — next {FDA_LOOKAHEAD_DAYS}d ({len(items)}"
                 f"{', ' + str(held_n) + ' HELD' if held_n else ''})",
        "description": "\n".join(lines)[:3900],
        "color": 15105570 if held_n else 3447003,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "binary events — best used as a VETO (do not hold "
                           "through a readout), not as a signal"},
    }


def _load_state() -> Dict:
    import json
    try:
        with open(STATE_PATH) as fh:
            return json.load(fh)
    except Exception:
        return {"last_digest": None, "urgent_sent": []}


def _save_state(st: Dict) -> None:
    import json
    try:
        # Cap the urgent history so the file cannot grow without bound.
        st["urgent_sent"] = st.get("urgent_sent", [])[-400:]
        st["insider_sent"] = st.get("insider_sent", [])[-200:]
        with open(STATE_PATH, "w") as fh:
            json.dump(st, fh)
    except Exception as e:
        print(f"  state save failed: {e}")


def _minutes_since(iso: Optional[str]) -> float:
    if not iso:
        return 1e9
    try:
        return (datetime.utcnow() - datetime.fromisoformat(iso)).total_seconds() / 60.0
    except Exception:
        return 1e9


def find_urgent(items: List[Dict], state: Dict) -> List[Dict]:
    """
    Headlines worth interrupting for, minus anything already sent.

    Two bars, because a held position is a risk question and everything else
    is only news: a held name needs URGENT_SCORE, anything else needs to be
    both is_major AND above the higher URGENT_MAJOR bar.
    """
    sent = set(state.get("urgent_sent", []))
    out = []
    for i in items:
        if i["headline"] in sent:
            continue
        hot = (i["held"] and abs(i["sent"]) >= URGENT_SCORE) or \
              (i["major"] and abs(i["sent"]) >= URGENT_MAJOR)
        if hot:
            out.append(i)
    return out


def build_urgent_embed(item: Dict) -> Dict:
    tag = ",".join(item["tickers"]) or "—"
    held = " · HELD" if item["held"] else ""
    return {
        "title": f"🚨 {tag}{held} — {item['sent']:+.2f}",
        "description": item["headline"],
        "color": 15158332 if item["sent"] < 0 else 3066993,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": f"urgent · {item['source']} · {item['at']} · "
                           f"backend={SENTIMENT_BACKEND}"},
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", action="store_true",
                    help="actually send to Discord (default: print only)")
    a = ap.parse_args()

    rows = fetch_headlines()
    if not rows:
        print("no headlines (check UW_API_KEY)")
        return 1
    held = held_symbols()
    items = curate(rows, held)
    added = append_log(rows)

    print(f"fetched {len(rows)} headlines | {added} new logged | "
          f"held: {', '.join(held) or 'none'} | backend={SENTIMENT_BACKEND}")
    print()
    for i in items:
        mark = " [HELD]" if i["held"] else ""
        print(f"  {i['sent']:+.2f} {','.join(i['tickers']) or '-':<18}{mark:<8}{i['headline'][:96]}")

    if not a.post:
        print("\n(dry run — pass --post to send to Discord)")
        return 0

    from uw_discord import post_embed
    state = _load_state()
    sent_any = False

    # 1. URGENT — bypasses the 30-minute consolidation.
    urgent = find_urgent(items, state)
    for u in urgent[:3]:                       # cap: never flood on a news burst
        if post_embed(build_urgent_embed(u), news_webhook()):
            state.setdefault("urgent_sent", []).append(u["headline"])
            sent_any = True
            print(f"  urgent sent: {u['sent']:+.2f} {u['headline'][:60]}")

    # 1b. INSIDER BUYS on held names — same urgency class as position news.
    seen_ins = set(state.get("insider_sent", []))
    for it in insider_buys(held):
        key = f"{it['symbol']}:{it['disc']:.0f}"
        if key in seen_ins:
            continue
        if post_embed(build_insider_embed(it), news_webhook()):
            state.setdefault("insider_sent", []).append(key)
            sent_any = True
            print(f"  insider buy sent: {it['symbol']} ${it['disc']:,.0f}")

    # 1c. FDA CATALYSTS — once per LOCAL day, at or after FDA_PUBLISH_AFTER_HOUR.
    now_local = datetime.now()
    today_str = now_local.strftime("%Y-%m-%d")
    if state.get("fda_day") != today_str and now_local.hour >= FDA_PUBLISH_AFTER_HOUR:
        cats = fda_catalysts(held)
        if cats and post_embed(build_fda_embed(cats), news_webhook()):
            state["fda_day"] = today_str
            sent_any = True
            print(f"  fda catalysts sent: {len(cats)} "
                  f"({sum(1 for c in cats if c['held'])} held)")
        elif not cats:
            state["fda_day"] = today_str      # nothing dated; do not retry all day
            print("  fda: no dated catalysts in window")

    # 2. CONSOLIDATED — only every DIGEST_EVERY_MIN.
    mins = _minutes_since(state.get("last_digest"))
    if mins < DIGEST_EVERY_MIN:
        _save_state(state)
        print(f"consolidated digest not due ({mins:.0f}/{DIGEST_EVERY_MIN} min)"
              f"{' — urgent posted' if sent_any else ''}")
        return 0

    notable = [i for i in items if i["held"]] or [i for i in items if abs(i["sent"]) > 0.15]
    if not notable:
        _save_state(state)
        print("nothing notable — not posting")
        return 0
    embed = build_embed(items, held)
    if not embed:
        _save_state(state)
        print("nothing to post")
        return 0
    # uw_discord carries the scrub with NO heavy dependencies. Importing
    # uw_bot here instead would pull pandas/yfinance into the sentiment venv,
    # which deliberately does not have them - the venv is isolated so that
    # installing torch can never disturb the interpreter holding positions.
    ok = post_embed(embed, news_webhook())
    if ok:
        state["last_digest"] = datetime.utcnow().isoformat()
    _save_state(state)
    print(f"\nconsolidated digest posted: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
