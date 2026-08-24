#!/usr/bin/env python3
"""
Get Robinhood Refresh Token for MCP
"""
import getpass
import requests
import json

print("\n" + "="*60)
print("GET ROBINHOOD REFRESH TOKEN")
print("="*60)

user = input("\nRobinhood email: ")
pwd = getpass.getpass("Password: ")

print("\n[*] Getting refresh token...")

try:
    r = requests.post(
        "https://api.robinhood.com/oauth2/token/",
        data={
            "username": user,
            "password": pwd,
            "grant_type": "password",
            "client_id": "c82SH0WZOsXWOEJw",
            "scope": "read write",
            "expires_in": 86400
        }
    )

    print(f"Status: {r.status_code}\n")

    if r.status_code == 200:
        data = r.json()
        refresh_token = data.get("refresh_token")
        access_token = data.get("access_token")

        if refresh_token:
            print("✅ SUCCESS!\n")
            print(f"Refresh Token: {refresh_token}")
            print(f"\nAccess Token: {access_token}\n")

            # Save to .env
            with open("/Users/ramayalala/trading_bot/.env", "w") as f:
                f.write(f"ROBINHOOD_REFRESH_TOKEN={refresh_token}\n")
                f.write(f"ROBINHOOD_ACCESS_TOKEN={access_token}\n")

            print("✅ Saved to .env\n")

            print("Now run:")
            print(f"export ROBINHOOD_REFRESH_TOKEN='{refresh_token}'")
            print(f"python3 bot_v38_balanced_with_mcp.py")

        else:
            print("❌ No refresh token in response")
            print(json.dumps(data, indent=2))

    else:
        print(f"❌ Error {r.status_code}")
        print(r.text)

except Exception as e:
    print(f"❌ {e}")
