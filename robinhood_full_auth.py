#!/usr/bin/env python3
"""
Robinhood OAuth Authenticator & Full Spec Extractor
Obtains Access Token, Refresh Token, and fetches dynamic Client IDs/App Profiles post-login.
"""

import json
import os
import requests
from pathlib import Path

# Base OAuth Endpoint & Initial App Client ID
BASE_AUTH_URL = "https://api.robinhood.com/oauth2/token/"
USER_PROFILE_URL = "https://api.robinhood.com/user/"
ACCOUNTS_URL = "https://api.robinhood.com/accounts/"
OAUTH_APPS_URL = "https://api.robinhood.com/oauth2/applications/"

STATIC_CLIENT_ID = "c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS"
OUTPUT_JSON = Path(".mcp_rh_tokens.json")
OUTPUT_ENV = Path(".env.mcp")


def fetch_account_client_ids(access_token: str) -> dict:
    """Queries Robinhood's authenticated APIs to extract dynamic client IDs and account details."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    fetched_info = {
        "user_id": None,
        "account_number": None,
        "custom_client_ids": []
    }

    # 1. Fetch User Profile & User ID
    try:
        user_res = requests.get(USER_PROFILE_URL, headers=headers, timeout=10)
        if user_res.status_code == 200:
            user_data = user_res.json()
            fetched_info["user_id"] = user_data.get("id")
            fetched_info["username"] = user_data.get("username")
    except Exception as e:
        print(f"[!] Warning: Could not fetch user profile: {e}")

    # 2. Fetch Account Number
    try:
        acc_res = requests.get(ACCOUNTS_URL, headers=headers, timeout=10)
        if acc_res.status_code == 200:
            acc_data = acc_res.json()
            results = acc_data.get("results", [])
            if results:
                fetched_info["account_number"] = results[0].get("account_number")
    except Exception as e:
        print(f"[!] Warning: Could not fetch account number: {e}")

    # 3. Query User Authorized OAuth Applications / Client IDs
    try:
        oauth_res = requests.get(OAUTH_APPS_URL, headers=headers, timeout=10)
        if oauth_res.status_code == 200:
            apps_data = oauth_res.json()
            for app in apps_data.get("results", []):
                fetched_info["custom_client_ids"].append({
                    "name": app.get("name"),
                    "client_id": app.get("client_id")
                })
    except Exception as e:
        pass

    return fetched_info


def authenticate_and_extract():
    print("=" * 65)
    print(" Robinhood OAuth Authenticator & Dynamic Spec Extractor")
    print("=" * 65)

    username = input("Enter Robinhood Username/Email: ").strip()
    password = input("Enter Robinhood Password: ").strip()
    mfa_code = input("Enter 2FA/MFA Code (leave blank if receiving SMS push): ").strip()

    payload = {
        "client_id": STATIC_CLIENT_ID,
        "grant_type": "password",
        "username": username,
        "password": password,
        "expires_in": 86400,
        "scope": "internal"
    }

    if mfa_code:
        payload["mfa_code"] = mfa_code

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    print("\n[+] Authenticating with Robinhood...")

    try:
        response = requests.post(BASE_AUTH_URL, data=payload, headers=headers, timeout=15)
        res_data = response.json()

        # Handle 2FA Challenge Flow
        if response.status_code == 400 and res_data.get("mfa_required"):
            print("\n[!] 2FA Required. SMS code sent.")
            sms_code = input("Enter 6-digit SMS code: ").strip()
            payload["mfa_code"] = sms_code
            response = requests.post(BASE_AUTH_URL, data=payload, headers=headers, timeout=15)
            res_data = response.json()

        # Handle App Challenge Approval Prompt
        if "challenge" in res_data:
            challenge_id = res_data["challenge"]["id"]
            print("\n[!] App Challenge Triggered. Please approve login on your phone.")
            input("Press [ENTER] after approving on your Robinhood App...")
            challenge_headers = dict(headers)
            challenge_headers["X-ROBINHOOD-CHALLENGE-RESPONSE-ID"] = challenge_id
            response = requests.post(BASE_AUTH_URL, data=payload, headers=challenge_headers, timeout=15)
            res_data = response.json()

        if response.status_code == 200 and "access_token" in res_data:
            access_token = res_data["access_token"]
            refresh_token = res_data.get("refresh_token", "")
            expires_in = res_data.get("expires_in", 86400)

            print("\n[+] Login Successful! Querying dynamic profile & client IDs...")
            profile_data = fetch_account_client_ids(access_token)

            # Build Full Specs
            client_id = STATIC_CLIENT_ID

            print("\n✅ AUTHENTICATION & EXTRACTION SUCCESSFUL")
            print("-" * 65)
            print(f"CLIENT_ID:           {client_id}")
            print(f"USER_ID:             {profile_data.get('user_id')}")
            print(f"ACCOUNT_NUMBER:      {profile_data.get('account_number')}")
            print(f"ACCESS_TOKEN:        {access_token[:12]}...{access_token[-10:]}")
            print(f"REFRESH_TOKEN:       {refresh_token[:12]}...{refresh_token[-10:]}")
            print(f"EXPIRES_IN:          {expires_in} seconds")
            print("-" * 65)

            # Persist to JSON
            output_payload = {
                "CLIENT_ID": client_id,
                "USER_ID": profile_data.get("user_id"),
                "ACCOUNT_NUMBER": profile_data.get("account_number"),
                "ROBINHOOD_ACCESS_TOKEN": access_token,
                "ROBINHOOD_REFRESH_TOKEN": refresh_token,
                "EXPIRES_IN": expires_in,
                "CUSTOM_CLIENT_IDS": profile_data.get("custom_client_ids", [])
            }
            OUTPUT_JSON.write_text(json.dumps(output_payload, indent=2))

            # Persist to .env file for MCP transport
            with open(OUTPUT_ENV, "w") as f:
                f.write(f"ROBINHOOD_CLIENT_ID={client_id}\n")
                f.write(f"ROBINHOOD_USER_ID={profile_data.get('user_id')}\n")
                f.write(f"ROBINHOOD_ACCOUNT_NUMBER={profile_data.get('account_number')}\n")
                f.write(f"ROBINHOOD_ACCESS_TOKEN={access_token}\n")
                f.write(f"ROBINHOOD_REFRESH_TOKEN={refresh_token}\n")

            print(f"\n[+] Specs saved to: {OUTPUT_JSON.resolve()}")
            print(f"[+] Environment file saved to: {OUTPUT_ENV.resolve()}")

        else:
            print(f"\n❌ Login Failed: {response.text}")

    except Exception as e:
        print(f"\n❌ Execution Error: {e}")


if __name__ == "__main__":
    authenticate_and_extract()
