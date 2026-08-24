#!/usr/bin/env python3
"""
Robinhood Native OAuth Authenticator & Token Exporter
Obtains Client ID, Access Token, and Refresh Token via pure HTTP requests.
"""

import json
import os
import requests
from pathlib import Path

# Static Robinhood Web OAuth Client ID
CLIENT_ID = "c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS"
AUTH_URL = "https://api.robinhood.com/oauth2/token/"
OUTPUT_JSON = Path(".mcp_rh_tokens.json")
OUTPUT_ENV = Path(".env.mcp")


def authenticate_and_get_tokens():
    print("=" * 60)
    print(" Robinhood OAuth Authentication & MCP Token Generator")
    print("=" * 60)

    username = input("Enter Robinhood Username/Email: ").strip()
    password = input("Enter Robinhood Password: ").strip()
    mfa_code = input("Enter 2FA/MFA Code (leave blank if receiving SMS push): ").strip()

    # Initial OAuth Payload
    payload = {
        "client_id": CLIENT_ID,
        "grant_type": "password",
        "username": username,
        "password": password,
        "expires_in": 86400,  # 24-hour token duration
        "scope": "internal"
    }

    if mfa_code:
        payload["mfa_code"] = mfa_code

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    print("\n[+] Initiating authentication request...")

    try:
        response = requests.post(AUTH_URL, data=payload, headers=headers, timeout=15)
        res_data = response.json()

        # Handle SMS 2FA Requirement Challenge
        if response.status_code == 400 and res_data.get("mfa_required"):
            print("\n[!] 2FA Required. A SMS code was sent to your phone.")
            sms_code = input("Enter the 6-digit SMS code: ").strip()
            payload["mfa_code"] = sms_code

            # Retry login with SMS code
            response = requests.post(AUTH_URL, data=payload, headers=headers, timeout=15)
            res_data = response.json()

        # Check for challenge verification (Push notification / SMS Workflow)
        if "challenge" in res_data:
            challenge_id = res_data["challenge"]["id"]
            print(f"\n[!] Robinhood Challenge Triggered (Type: {res_data['challenge']['type']})")
            print("Please approve the login prompt in your Robinhood mobile app.")
            input("Press [ENTER] after approving on your phone...")

            # Challenge verification header call
            challenge_headers = dict(headers)
            challenge_headers["X-ROBINHOOD-CHALLENGE-RESPONSE-ID"] = challenge_id
            response = requests.post(AUTH_URL, data=payload, headers=challenge_headers, timeout=15)
            res_data = response.json()

        # Successful Token Generation
        if response.status_code == 200 and "access_token" in res_data:
            access_token = res_data["access_token"]
            refresh_token = res_data.get("refresh_token", "")
            expires_in = res_data.get("expires_in", 86400)
            token_type = res_data.get("token_type", "Bearer")

            print("\n✅ AUTHENTICATION SUCCESSFUL!")
            print("-" * 60)
            print(f"CLIENT_ID:      {CLIENT_ID}")
            print(f"ACCESS_TOKEN:   {access_token[:12]}...{access_token[-10:]}")
            print(f"REFRESH_TOKEN:  {refresh_token[:12]}...{refresh_token[-10:]}")
            print(f"EXPIRES_IN:     {expires_in} seconds")
            print("-" * 60)

            # Export data to JSON
            token_payload = {
                "CLIENT_ID": CLIENT_ID,
                "ROBINHOOD_ACCESS_TOKEN": access_token,
                "ROBINHOOD_REFRESH_TOKEN": refresh_token,
                "TOKEN_TYPE": token_type,
                "EXPIRES_IN": expires_in
            }
            OUTPUT_JSON.write_text(json.dumps(token_payload, indent=2))

            # Export data to .env file for MCP Server consumption
            with open(OUTPUT_ENV, "w") as f:
                f.write(f"ROBINHOOD_CLIENT_ID={CLIENT_ID}\n")
                f.write(f"ROBINHOOD_ACCESS_TOKEN={access_token}\n")
                f.write(f"ROBINHOOD_REFRESH_TOKEN={refresh_token}\n")

            print(f"\n[+] Credentials saved to: {OUTPUT_JSON.resolve()}")
            print(f"[+] Environment file saved to: {OUTPUT_ENV.resolve()}")

        else:
            print(f"\n❌ Authentication Failed (HTTP {response.status_code}):")
            print(json.dumps(res_data, indent=2))

    except Exception as e:
        print(f"\n❌ Connection or execution error: {e}")


if __name__ == "__main__":
    authenticate_and_get_tokens()
