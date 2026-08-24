#!/usr/bin/env python3
"""
Robinhood MCP Refresh Token Exchange
Requests a fresh short-lived access token using an existing refresh token.
"""

import json
import os
import requests
from pathlib import Path

# Paths & Defaults
TOKEN_FILE = Path(".mcp_rh_token.json")
ROBINHOOD_TOKEN_URL = "https://api.robinhood.com/oauth2/token/"

# Robinhood's hardcoded OAuth App Client ID
CLIENT_ID = "c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS"


def refresh_access_token():
    print("=" * 50)
    print(" Robinhood MCP Token Refresh Execution")
    print("=" * 50)

    # 1. Retrieve current stored refresh token
    refresh_token = None
    if TOKEN_FILE.exists():
        try:
            data = json.loads(TOKEN_FILE.read_text())
            refresh_token = data.get("ROBINHOOD_REFRESH_TOKEN")
        except Exception as e:
            print(f"Error loading {TOKEN_FILE}: {e}")

    # Fallback to environment variable if JSON file is absent
    if not refresh_token:
        refresh_token = os.getenv("ROBINHOOD_REFRESH_TOKEN")

    if not refresh_token:
        refresh_token = input("Enter ROBINHOOD_REFRESH_TOKEN manually: ").strip()

    if not refresh_token:
        print("❌ Error: No refresh token found.")
        return

    # 2. Construct OAuth2 token refresh payload
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "expires_in": 86400  # Request 24-hour expiration
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }

    print("\nSending token refresh request to Robinhood...")

    try:
        response = requests.post(ROBINHOOD_TOKEN_URL, data=payload, headers=headers, timeout=10)

        if response.status_code == 200:
            res_data = response.json()
            new_access_token = res_data.get("access_token")
            new_refresh_token = res_data.get("refresh_token", refresh_token)
            expires_in = res_data.get("expires_in", 86400)

            print("✅ TOKEN REFRESH SUCCESSFUL!")

            # 3. Update configuration file
            updated_credentials = {
                "ROBINHOOD_ACCESS_TOKEN": new_access_token,
                "ROBINHOOD_REFRESH_TOKEN": new_refresh_token,
                "TOKEN_TYPE": res_data.get("token_type", "Bearer"),
                "EXPIRES_IN": expires_in
            }

            TOKEN_FILE.write_text(json.dumps(updated_credentials, indent=2))

            # Update .env file for MCP transport
            with open(".env.mcp", "w") as f:
                f.write(f"ROBINHOOD_ACCESS_TOKEN={new_access_token}\n")
                f.write(f"ROBINHOOD_REFRESH_TOKEN={new_refresh_token}\n")

            print(f"New Access Token: {new_access_token[:10]}...{new_access_token[-10:]}")
            print(f"Saved updated state to {TOKEN_FILE.resolve()}")

        else:
            print(f"❌ Refresh Failed (HTTP {response.status_code}): {response.text}")
            print("\nNote: If the refresh token has expired or been revoked, you must run the initial login flow to generate a new pair.")

    except Exception as e:
        print(f"❌ Connection Error during refresh: {e}")


if __name__ == "__main__":
    refresh_access_token()
