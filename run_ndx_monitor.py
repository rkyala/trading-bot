#!/usr/bin/env python3
"""
Standalone NDX monitor loop.

WHY THIS EXISTS SEPARATELY
The monitor normally runs inside uw_bot.py's main loop. But the bot has no
mechanism to pick up new code without a restart, and restarting it mid-session
costs real things: cooldowns are in-memory by design, so every symbol stopped
out earlier becomes immediately re-enterable — the exact defect the cooldown
was added to fix.

This process touches no positions, no orders and no bot state. It polls, it
posts NDX cards, it exits at the close. Safe to run alongside the live bot, and
unnecessary once the bot restarts with the monitor built in.

Exits on its own when the session ends, so it cannot linger overnight — the
bot's missing exit path is a lesson already paid for here.
"""

import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "unusual_whales_bot"))

POLL_SECONDS = 120          # the card itself decides whether to post


def main() -> int:
    import uw_ndx_monitor as ndx

    if not os.getenv("UW_API_KEY"):
        print("UW_API_KEY not set — source .env.local first", file=sys.stderr)
        return 1

    state = {}
    posts = 0
    print(f"[{datetime.now():%H:%M:%S}] NDX monitor loop started "
          f"(poll {POLL_SECONDS}s, heartbeat {ndx.HEARTBEAT_MIN:.0f}m)")

    idle_after_session = 0
    while True:
        try:
            if ndx.in_session():
                idle_after_session = 0
                snap = ndx.run_once(state)
                if snap:
                    posts += 1
                    print(f"[{datetime.now():%H:%M:%S}] posted #{posts}: "
                          f"NDX {snap['price']:,.0f} ({snap['recent_pct']:+.2f}%)")
            else:
                idle_after_session += 1
                # Two consecutive out-of-session polls once we have posted:
                # the session is over, so stop rather than idle overnight.
                if posts and idle_after_session >= 2:
                    print(f"[{datetime.now():%H:%M:%S}] session over — "
                          f"{posts} posts, exiting")
                    return 0
        except Exception as e:
            print(f"[{datetime.now():%H:%M:%S}] error: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
