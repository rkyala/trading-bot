#!/usr/bin/env python3
"""
Test MCP Authentication
Verify that the OAuth tokens work with Robinhood API
"""

import json
import os
import sys
from pathlib import Path
import requests

TOKEN_FILE = Path(".mcp_rh_tokens.json")
ENV_FILE = Path(".env.mcp")


def test_mcp_auth():
    print("="*70)
    print(" MCP Authentication Test")
    print("="*70)

    # Step 1: Check if credentials file exists
    print("\n[1] Checking for credential files...")
    if not TOKEN_FILE.exists():
        print(f"❌ {TOKEN_FILE} not found")
        print("   Run: python3 robinhood_full_auth.py")
        return False

    if not ENV_FILE.exists():
        print(f"❌ {ENV_FILE} not found")
        print("   Run: python3 robinhood_full_auth.py")
        return False

    print(f"✅ {TOKEN_FILE} found")
    print(f"✅ {ENV_FILE} found")

    # Step 2: Load credentials from JSON
    print("\n[2] Loading credentials from JSON...")
    try:
        creds = json.loads(TOKEN_FILE.read_text())
        access_token = creds.get("ROBINHOOD_ACCESS_TOKEN", "")
        refresh_token = creds.get("ROBINHOOD_REFRESH_TOKEN", "")
        user_id = creds.get("USER_ID", "")
        account_number = creds.get("ACCOUNT_NUMBER", "")
        expires_in = creds.get("EXPIRES_IN", 0)

        if not access_token:
            print("❌ No ROBINHOOD_ACCESS_TOKEN in JSON")
            return False

        print(f"✅ Access Token: {access_token[:15]}...{access_token[-10:]}")
        print(f"✅ Refresh Token: {refresh_token[:15] if refresh_token else 'NONE'}...{refresh_token[-10:] if refresh_token else ''}")
        print(f"✅ User ID: {user_id}")
        print(f"✅ Account Number: {account_number}")
        print(f"✅ Expires In: {expires_in} seconds ({expires_in/3600:.1f} hours)")

    except Exception as e:
        print(f"❌ Error reading JSON: {e}")
        return False

    # Step 3: Test API call with token
    print("\n[3] Testing API authentication...")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }

    try:
        # Try to fetch user profile
        response = requests.get(
            "https://api.robinhood.com/user/",
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            print("✅ User profile API call successful")
            user_data = response.json()
            print(f"   Username: {user_data.get('username')}")
        elif response.status_code == 401:
            print(f"❌ Unauthorized (HTTP 401) - Token expired or invalid")
            print(f"   Response: {response.text}")
            return False
        else:
            print(f"❌ API call failed (HTTP {response.status_code})")
            print(f"   Response: {response.text}")
            return False

    except requests.RequestException as e:
        print(f"❌ Network error: {e}")
        return False

    # Step 4: Test account fetch
    print("\n[4] Testing account API...")
    try:
        response = requests.get(
            "https://api.robinhood.com/accounts/",
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            print("✅ Account API call successful")
            accounts = response.json().get("results", [])
            if accounts:
                acc = accounts[0]
                print(f"   Account Type: {acc.get('account_type')}")
                print(f"   Buying Power: ${acc.get('buying_power', 'N/A')}")
                print(f"   Margin Limit: ${acc.get('margin_limit', 'N/A')}")
        else:
            print(f"❌ Account API failed (HTTP {response.status_code})")
            return False

    except Exception as e:
        print(f"❌ Error fetching accounts: {e}")
        return False

    # Step 5: Check .env.mcp is loadable
    print("\n[5] Checking .env.mcp file...")
    try:
        with open(ENV_FILE, "r") as f:
            env_vars = {}
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    env_vars[key] = val

        print(f"✅ .env.mcp readable")
        print(f"   ROBINHOOD_CLIENT_ID: {env_vars.get('ROBINHOOD_CLIENT_ID', 'MISSING')[:15]}...")
        print(f"   ROBINHOOD_ACCESS_TOKEN: {env_vars.get('ROBINHOOD_ACCESS_TOKEN', 'MISSING')[:15]}...")
        print(f"   ROBINHOOD_USER_ID: {env_vars.get('ROBINHOOD_USER_ID', 'MISSING')}")
        print(f"   ROBINHOOD_ACCOUNT_NUMBER: {env_vars.get('ROBINHOOD_ACCOUNT_NUMBER', 'MISSING')}")

    except Exception as e:
        print(f"❌ Error reading .env.mcp: {e}")
        return False

    # Step 6: Summary
    print("\n" + "="*70)
    print("✅ ALL MCP AUTHENTICATION TESTS PASSED!")
    print("="*70)
    print("\nYou can now run:")
    print("  python3 bot_v38_mcp_live.py")
    print("\nOr enable cron for automatic 30-minute cycles")
    print("="*70)

    return True


if __name__ == "__main__":
    success = test_mcp_auth()
    sys.exit(0 if success else 1)
