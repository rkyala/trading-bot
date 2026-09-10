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

import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = "https://api.unusualwhales.com/api"
SENTIMENT_BACKEND = os.getenv("SENTIMENT_BACKEND", "lexicon")  # lexicon | finbert | uw(dead)
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
        if post_embed(build_urgent_embed(u)):
            state.setdefault("urgent_sent", []).append(u["headline"])
            sent_any = True
            print(f"  urgent sent: {u['sent']:+.2f} {u['headline'][:60]}")

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
    ok = post_embed(embed)
    if ok:
        state["last_digest"] = datetime.utcnow().isoformat()
    _save_state(state)
    print(f"\nconsolidated digest posted: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
