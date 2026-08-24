#!/usr/bin/env python3
"""
Load Robinhood token from pickle file and set up .env.mcp
"""

import pickle
import pathlib
import requests
import sys

pickle_path = pathlib.Path.home() / ".tokens" / "robinhood.pickle"

if not pickle_path.exists():
    print(f"❌ Pickle file not found: {pickle_path}")
    sys.exit(1)

print(f"[+] Loading pickle from {pickle_path}")

try:
    data = pickle.loads(pickle_path.read_bytes())
    refresh_token = data.get("refresh_token")
    device_token = data.get("device_token")

    if not refresh_token:
        print("❌ No refresh_token in pickle")
        sys.exit(1)

    print(f"✅ Loaded refresh_token: {refresh_token[:20]}...")

except Exception as e:
    print(f"❌ Error loading pickle: {e}")
    sys.exit(1)

# Get fresh access token
print(f"\n[+] Getting fresh access token...")

resp = requests.post(
    "https://api.robinhood.com/oauth2/token/",
    data={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": "c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS",
        "scope": "internal",
        "device_token": device_token,
    }
)

print(f"Status: {resp.status_code}")

if resp.status_code != 200:
    print(f"❌ Token refresh failed: {resp.text}")
    sys.exit(1)

new_data = resp.json()

if "access_token" not in new_data:
    print(f"❌ No access_token in response: {new_data}")
    sys.exit(1)

access_token = new_data["access_token"]

# Update pickle with new token
try:
    data.update(new_data)
    pickle_path.write_bytes(pickle.dumps(data))
    print(f"✅ Updated pickle file")
except Exception as e:
    print(f"⚠️  Warning: Could not update pickle: {e}")

# Save to .env.mcp
env_file = pathlib.Path(".env.mcp")

with open(env_file, "w") as f:
    f.write(f"ROBINHOOD_CLIENT_ID=c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS\n")
    f.write(f"ROBINHOOD_ACCESS_TOKEN={access_token}\n")
    f.write(f"ROBINHOOD_REFRESH_TOKEN={refresh_token}\n")
    f.write(f"ROBINHOOD_DEVICE_TOKEN={device_token}\n")

print(f"\n✅ Saved credentials to {env_file.resolve()}")
print(f"\nAccess Token:")
print(f"  {access_token[:40]}...")
print(f"\n✅ Ready to trade!")
print(f"\nNext: python3 test_mcp_auth.py")
