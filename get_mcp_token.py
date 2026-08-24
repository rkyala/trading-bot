#!/usr/bin/env python3
import getpass
import requests

print("\n" + "="*60)
print("GET ROBINHOOD TOKEN FOR MCP")
print("="*60)

user = input("\nRobinhood email: ")
pwd = getpass.getpass("Password: ")

print("\n[*] Authenticating...")

try:
    r = requests.post(
        "https://api.robinhood.com/oauth2/token/",
        data={
            "username": user,
            "password": pwd,
            "grant_type": "password",
            "client_id": "c82SH0WZOsXWOEJw",
            "scope": "read write"
        },
        headers={"Accept": "application/json"}
    )

    print(f"Status: {r.status_code}")

    if r.status_code == 200:
        token = r.json()["access_token"]
        print(f"\n✅ SUCCESS!")
        print(f"Token: {token}")

        # Save
        with open("/Users/ramayalala/trading_bot/.env", "w") as f:
            f.write(f"ROBINHOOD_AUTH_TOKEN={token}\n")

        print(f"\n✅ Saved to .env")
        print(f"\nNow run:")
        print(f"  export ROBINHOOD_AUTH_TOKEN='{token}'")
        print(f"  python3 bot_v38_balanced_with_mcp.py")

    else:
        print(f"\n❌ Error: {r.status_code}")
        print(r.text)

except Exception as e:
    print(f"\n❌ {e}")
