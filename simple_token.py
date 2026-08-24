#!/usr/bin/env python3
import getpass
import requests

print("\n" + "="*60)
print("ROBINHOOD TOKEN - SIMPLE")
print("="*60)

user = input("\nRobinhood email: ")
pwd = getpass.getpass("Password: ")

print("\n[*] Getting token...")

try:
    r = requests.post(
        "https://api.robinhood.com/oauth2/token/",
        data={
            "username": user,
            "password": pwd,
            "grant_type": "password",
            "client_id": "c82SH0WZOsXWOEJw"
        }
    )

    if r.status_code == 200:
        token = r.json()["access_token"]
        print(f"\n✅ Token: {token}")

        # Save
        with open("/Users/ramayalala/trading_bot/.env", "a") as f:
            f.write(f"\nROBINHOOD_AUTH_TOKEN={token}\n")

        print(f"✅ Saved to .env\n")
    else:
        print(f"\n❌ Error: {r.status_code}")
        print(r.text)

except Exception as e:
    print(f"\n❌ {e}")
