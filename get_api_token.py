#!/usr/bin/env python3
"""
Robinhood API Token Generator - Direct Authentication
"""

import sys
import getpass
import json
from pathlib import Path

print("\n" + "="*80)
print("ROBINHOOD API TOKEN GENERATOR")
print("="*80)

try:
    import requests
except ImportError:
    print("\n❌ ERROR: requests library not found")
    print("Install with: pip install requests")
    sys.exit(1)

print("\nEnter your Robinhood credentials:\n")

username = input("Robinhood username/email: ").strip()
password = getpass.getpass("Password (hidden): ")

if not username or not password:
    print("\n❌ Username or password cannot be empty")
    sys.exit(1)

print("\n[*] Authenticating with Robinhood API...")
print("    This may take a few seconds...\n")

try:
    # Robinhood API authentication
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    auth_data = {
        "username": username,
        "password": password,
        "grant_type": "password",
        "client_id": "c82SH0WZOsXWOEJw",
        "scope": "read write",
        "expires_in": 86400
    }

    response = requests.post(
        "https://api.robinhood.com/oauth2/token/",
        data=auth_data,
        headers=headers,
        timeout=15
    )

    print(f"Response: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        token = data.get("access_token")

        if token:
            print("✅ Authentication successful!")
            print(f"\nToken received:")
            print(f"  Length: {len(token)} characters")
            print(f"  First 30 chars: {token[:30]}...")

            # Save to .env
            env_file = Path("/Users/ramayalala/trading_bot/.env")

            with open(env_file, "a") as f:
                f.write(f"\nROBINHOOD_AUTH_TOKEN={token}\n")

            print(f"\n✅ Token saved to: {env_file}")

            print("\n" + "="*80)
            print("NEXT STEPS")
            print("="*80)
            print("""
1. Deploy bot:
   cd ~/trading_bot
   cp bot_v38_balanced_with_mcp.py bot_final_production_v38.py

2. Test bot:
   python3 bot_final_production_v38.py

3. Check logs:
   tail -f ~/trading_bot/bot_v38.log

Expected:
   MCP Status: ENABLED
   ✅ Positions fetched from Robinhood
""")
        else:
            print(f"\n❌ No access token in response")
            print(f"Response: {json.dumps(data, indent=2)}")
            sys.exit(1)

    elif response.status_code == 401:
        print(f"\n❌ Authentication failed")
        print(f"   Wrong username/password")
        print(f"   Or account locked")
        print(f"\nResponse: {response.text}")
        sys.exit(1)

    elif response.status_code == 400:
        print(f"\n❌ Invalid request")
        print(f"Response: {response.text}")
        sys.exit(1)

    else:
        print(f"\n❌ Unexpected error (Status {response.status_code})")
        print(f"Response: {response.text}")
        sys.exit(1)

except requests.exceptions.Timeout:
    print("\n❌ Connection timeout")
    print("   Robinhood API may be down or slow")
    sys.exit(1)

except requests.exceptions.ConnectionError:
    print("\n❌ Connection error")
    print("   Check internet connection")
    sys.exit(1)

except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
