#!/usr/bin/env python3
"""
Setup credentials from manually copied token
"""

import json
from pathlib import Path

TOKEN_FILE = Path(".env.mcp")
JSON_FILE = Path(".mcp_rh_tokens.json")

print("="*70)
print(" Setup Robinhood Token - Manual Method")
print("="*70)

# Get token from user
print("\nPaste your access token from browser Developer Tools:")
print("(Right-click page → Inspect → Network tab → Find Authorization: Bearer ...)")
print("\nEnter token (or paste from clipboard):")

access_token = input().strip()

if not access_token.startswith("eyJ"):
    print("❌ Invalid token format (should start with 'eyJ')")
    exit(1)

client_id = "c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS"

# Save to .env.mcp
with open(TOKEN_FILE, "w") as f:
    f.write(f"ROBINHOOD_CLIENT_ID={client_id}\n")
    f.write(f"ROBINHOOD_ACCESS_TOKEN={access_token}\n")

print(f"\n✅ Saved to {TOKEN_FILE.resolve()}")

# Save to JSON (for reference)
json_data = {
    "CLIENT_ID": client_id,
    "ROBINHOOD_ACCESS_TOKEN": access_token,
    "ROBINHOOD_REFRESH_TOKEN": "Manual token - no refresh available",
    "EXPIRES_IN": 86400,
    "NOTE": "Token expires in 24 hours. Refresh via browser if needed."
}

with open(JSON_FILE, "w") as f:
    json.dump(json_data, f, indent=2)

print(f"✅ Saved to {JSON_FILE.resolve()}")

print("\nNext step: python3 test_mcp_auth.py")
