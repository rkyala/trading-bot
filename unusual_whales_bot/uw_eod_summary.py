#!/usr/bin/env python3
"""
End-of-day summary -> Discord. One message, after the book is flat.

WHY THIS IS THE MOST VALUABLE ALERT ON THE LIST
Every other alert describes a moment. This one describes the DAY, and it is the
only one that answers the question that actually matters: did the machinery do
what it was supposed to?

The failures on this project were never loud. The bot opened five positions in
silence on Sep 8 and nobody noticed. Tier 2 announced "ACTIVE" through two
separate periods when it could not close a position. Rule toggles were read
only by a reporting function. cron never once started the bot. In every case a
daily "what actually fired" line would have exposed it immediately.

So this reports MECHANISM, not just P&L:
  - which exit reasons fired, and which did NOT
  - whether a stop or target ever triggered
  - whether Tier 2 is shadowed and how many signals it discarded
  - positions still open after the flatten (should be zero)

A zero in the TARGET_HIT row is information. So is a zero in the STOP_HIT row.

NOT A PERFORMANCE REPORT
Paper P&L on a strategy measured at zero edge is noise, and reading it as
performance is how people talk themselves into a system. The numbers are here
for accounting and for spotting mechanical breakage, not for evaluating a
strategy that fifteen backtests say has no edge.
"""

import json
import os
import sys
from collections import Counter
from datetime import date, datetime
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Exit reasons we expect to be POSSIBLE. A reason that never fires across a
# whole session is worth seeing, because "never fires" has repeatedly meant
# "structurally cannot fire" on this project rather than "conditions not met".
EXPECTED_REASONS = ("STOP_HIT", "TARGET_HIT", "bearish_flow",
                    "rotated_for_better_signal", "eod_flatten", "tier2")


def _jsonl(path: str) -> List[Dict]:
    out = []
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except FileNotFoundError:
        pass
    return out


def collect(day: str) -> Dict:
    closed = [c for c in _jsonl(os.path.join(REPO, "closed_trades.jsonl"))
              if str(c.get("exit_time", ""))[:10] == day]
    shadow = [s for s in _jsonl(os.path.join(REPO, "tier2_shadow.jsonl"))
              if str(s.get("logged_at", ""))[:10] == day]
    try:
        with open(os.path.join(REPO, "open_positions.json")) as fh:
            d = json.load(fh)
        still_open = list(d.values()) if isinstance(d, dict) else list(d)
    except Exception:
        still_open = []

    pnl = sum(c.get("pnl", 0) or 0 for c in closed)
    wins = sum(1 for c in closed if (c.get("pnl", 0) or 0) > 0)
    return {
        "closed": closed, "shadow": shadow, "still_open": still_open,
        "pnl": pnl, "wins": wins,
        "reasons": Counter(c.get("exit_reason") for c in closed),
        "symbols": sorted({c.get("symbol") for c in closed if c.get("symbol")}),
    }


def build_embed(day: str, d: Dict) -> Dict:
    n = len(d["closed"])
    wr = (d["wins"] / n * 100) if n else 0.0
    lines = [f"**{n} closed · {d['wins']}W/{n - d['wins']}L ({wr:.0f}%) · "
             f"P&L ${d['pnl']:+,.2f}**", ""]

    lines.append("**Exit reasons — what actually fired:**")
    for r in EXPECTED_REASONS:
        c = d["reasons"].get(r, 0)
        mark = "" if c else "   ← never fired"
        lines.append(f"`{r:<26}` {c}{mark}")
    for r, c in d["reasons"].items():
        if r not in EXPECTED_REASONS:
            lines.append(f"`{str(r):<26}` {c}")

    if d["shadow"]:
        by = Counter(s.get("reason") for s in d["shadow"])
        lines += ["", f"**Tier 2 — SHADOW, {len(d['shadow'])} signals discarded:**",
                  "  " + " · ".join(f"{k} {v}" for k, v in by.most_common(4))]

    if d["still_open"]:
        syms = ", ".join(sorted({str(p.get("symbol")) for p in d["still_open"]}))
        lines += ["", f"⚠️ **{len(d['still_open'])} position(s) STILL OPEN "
                      f"after the flatten** — {syms}"]
    else:
        lines += ["", "✅ Book flat"]

    if d["symbols"]:
        lines += ["", "traded: " + ", ".join(d["symbols"][:18])]

    return {
        "title": f"📕 EOD Summary — {day}",
        "description": "\n".join(lines)[:3900],
        "color": 3066993 if d["pnl"] >= 0 else 15158332,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "paper · mechanism report, not performance — "
                           "15 backtests say this strategy has no measured edge"},
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", action="store_true")
    ap.add_argument("--date", default=date.today().isoformat())
    a = ap.parse_args()

    d = collect(a.date)
    embed = build_embed(a.date, d)
    print(embed["title"])
    print(embed["description"])

    if not a.post:
        print("\n(dry run — pass --post)")
        return 0
    from uw_discord import post_embed
    ok = post_embed(embed)
    print(f"\nposted: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
