#!/usr/bin/env python3
"""
Auto-Refresh Robinhood Access Token
Uses stored refresh_token to get fresh access_token
No CLIENT_ID needed - uses standard Robinhood OAuth endpoint
"""

import json
import requests
from pathlib import Path
from datetime import datetime

TOKEN_FILE = Path(".mcp_rh_tokens.json")
ENV_FILE = Path(".env.mcp")

# Robinhood OAuth endpoint (public)
ROBINHOOD_TOKEN_URL = "https://api.robinhood.com/oauth2/token/"

# Standard Robinhood Client ID (hardcoded in web app)
CLIENT_ID = "c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS"


def auto_refresh():
    """Automatically refresh access token using stored refresh token"""

    print("="*60)
    print(" Auto-Refresh Robinhood Access Token")
    print("="*60)

    # Step 1: Read stored refresh token
    if not TOKEN_FILE.exists():
        print(f"\n❌ Error: {TOKEN_FILE} not found")
        print("Run: python3 robinhood_oauth_auth.py first")
        return False

    try:
        data = json.loads(TOKEN_FILE.read_text())
        refresh_token = data.get("ROBINHOOD_REFRESH_TOKEN")
        old_access_token = data.get("ROBINHOOD_ACCESS_TOKEN", "")[:20]

        if not refresh_token:
            print(f"\n❌ Error: No ROBINHOOD_REFRESH_TOKEN in {TOKEN_FILE}")
            return False

        print(f"\n[+] Found refresh token")
        print(f"[+] Old access token: {old_access_token}...")

    except Exception as e:
        print(f"❌ Error reading {TOKEN_FILE}: {e}")
        return False

    # Step 2: Request new access token
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "expires_in": 86400  # 24-hour token
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }

    print(f"\n[+] Requesting new access token...")

    try:
        response = requests.post(
            ROBINHOOD_TOKEN_URL,
            data=payload,
            headers=headers,
            timeout=10
        )

        if response.status_code != 200:
            print(f"❌ Refresh failed (HTTP {response.status_code})")
            print(response.text)
            return False

        res_data = response.json()

        # Step 3: Extract new tokens
        new_access_token = res_data.get("access_token")
        new_refresh_token = res_data.get("refresh_token", refresh_token)
        expires_in = res_data.get("expires_in", 86400)

        if not new_access_token:
            print("❌ No access_token in response")
            print(json.dumps(res_data, indent=2))
            return False

        # Step 4: Update token file
        updated_data = {
            "CLIENT_ID": CLIENT_ID,
            "ROBINHOOD_ACCESS_TOKEN": new_access_token,
            "ROBINHOOD_REFRESH_TOKEN": new_refresh_token,
            "TOKEN_TYPE": res_data.get("token_type", "Bearer"),
            "EXPIRES_IN": expires_in,
            "REFRESHED_AT": datetime.now().isoformat()
        }

        TOKEN_FILE.write_text(json.dumps(updated_data, indent=2))

        # Step 5: Update .env.mcp file
        with open(ENV_FILE, "w") as f:
            f.write(f"ROBINHOOD_CLIENT_ID={CLIENT_ID}\n")
            f.write(f"ROBINHOOD_ACCESS_TOKEN={new_access_token}\n")
            f.write(f"ROBINHOOD_REFRESH_TOKEN={new_refresh_token}\n")

        print(f"\n✅ TOKEN REFRESH SUCCESSFUL!")
        print(f"New access token:  {new_access_token[:20]}...{new_access_token[-10:]}")
        print(f"Expires in:        {expires_in} seconds ({expires_in/3600:.1f} hours)")
        print(f"Saved to:          {TOKEN_FILE.resolve()}")
        print(f"Saved to:          {ENV_FILE.resolve()}")

        return True

    except requests.RequestException as e:
        print(f"❌ Network error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


if __name__ == "__main__":
    success = auto_refresh()
    exit(0 if success else 1)
