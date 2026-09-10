#!/usr/bin/env python3
"""
Discord posting with an outbound credential scrub. NO heavy dependencies.

WHY THIS EXISTS SEPARATELY
The audited poster lived on UnusualWhalesBot._discord_post. Importing that
class pulls in the whole trading dependency tree - pandas, yfinance, the API
client - which the sentiment sidecar deliberately does NOT have: FinBERT runs
in its own 3.10 venv precisely so installing torch can never disturb the
interpreter holding live positions.

So the poster is factored out here with nothing but `requests`. Both the bot
and the sidecar can use it.

NOTE: uw_bot.py still carries its own copy of this logic. It is running live
with open positions, so it is not being edited mid-session. Fold it onto this
module when the book is flat.

THE SCRUB IS THE POINT
Discord is an external surface and a leak there is irreversible - the message
is delivered before anyone notices. The payload is therefore checked against
the ACTUAL live secret values immediately before sending, and any match is
redacted rather than posted. If the scrub itself raises, nothing is sent.
"""

import json as _json
import os
from typing import Optional

# Checked against the payload immediately before every send.
_SECRET_VARS = (
    "UW_API_KEY", "DISCORD_WEBHOOK_URL", "ANTHROPIC_API_KEY",
    "RH_CLIENT_ID", "RH_REFRESH_TOKEN", "RH_ACCESS_TOKEN",
    "SCHWAB_CLIENT_ID", "SCHWAB_CLIENT_SECRET", "HF_TOKEN",
)


def scrub(payload: dict) -> Optional[dict]:
    """
    Redact any live credential value found in the payload.

    Returns None if the scrub could not be completed - the caller must then
    NOT send. Failing closed matters more than delivering the message.
    """
    try:
        blob = _json.dumps(payload)
        leaked = []
        for var in _SECRET_VARS:
            val = os.getenv(var)
            # The length floor avoids redacting a short or empty env var that
            # happens to appear as a substring of ordinary text.
            if val and len(val) >= 12 and val in blob:
                blob = blob.replace(val, "<REDACTED>")
                leaked.append(var)
        if leaked:
            print(f"BLOCKED credential(s) from a Discord payload: "
                  f"{', '.join(leaked)} - redacted before sending")
            return _json.loads(blob)
        return payload
    except Exception as e:
        print(f"secret scrub failed, not sending: {e}")
        return None


def post_embed(embed: dict, webhook: Optional[str] = None) -> bool:
    """
    Send one embed. True only on a real 2xx.

    Delivery failures are reported rather than swallowed: a notification path
    that fails quietly is indistinguishable from one that has nothing to say,
    which is how several dead components on this project stayed hidden.
    Never raises - alerting must not break the caller.
    """
    wh = webhook or os.getenv("DISCORD_WEBHOOK_URL")
    if not wh:
        print("DISCORD_WEBHOOK_URL not set - not posting")
        return False

    safe = scrub(embed)
    if safe is None:
        return False

    try:
        import requests
        # TLS verification stays on: the webhook URL is itself a credential.
        r = requests.post(wh, json={"embeds": [safe]}, timeout=10)
        if r.status_code not in (200, 204):
            print(f"Discord rejected the post: HTTP {r.status_code}")
            return False
        return True
    except Exception as e:
        print(f"Discord post failed: {e}")
        return False
