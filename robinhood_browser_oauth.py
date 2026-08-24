#!/usr/bin/env python3
"""
Robinhood Browser OAuth - Proper OAuth 2.0 Flow
Opens browser for user login, handles callback, extracts tokens
"""

import json
import os
import sys
import webbrowser
import time
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import requests

# OAuth Configuration
CLIENT_ID = "c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS"
REDIRECT_URI = "http://localhost:8080/callback"
AUTH_BASE_URL = "https://api.robinhood.com/oauth2/authorize/"
TOKEN_URL = "https://api.robinhood.com/oauth2/token/"

OUTPUT_JSON = Path(".mcp_rh_tokens.json")
OUTPUT_ENV = Path(".env.mcp")

# Global to store auth code
AUTH_CODE = None
AUTH_ERROR = None


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handle OAuth redirect callback"""

    def do_GET(self):
        global AUTH_CODE, AUTH_ERROR

        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)

        if "code" in query_params:
            AUTH_CODE = query_params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html = b"<html><body><h1>Authorization Successful!</h1><p>You can close this window and return to the terminal.</p><script>window.close();</script></body></html>"
            self.wfile.write(html)
        elif "error" in query_params:
            AUTH_ERROR = query_params["error"][0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html = f"<html><body><h1>Authorization Failed</h1><p>Error: {AUTH_ERROR}</p></body></html>".encode()
            self.wfile.write(html)
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress default logging
        pass


def start_oauth_flow():
    print("=" * 70)
    print(" Robinhood Browser OAuth - Secure Login")
    print("=" * 70)

    # Step 1: Build authorization URL
    auth_url = f"{AUTH_BASE_URL}?client_id={CLIENT_ID}&response_type=code&redirect_uri={REDIRECT_URI}&scope=read%20write%20trading&state=state123"

    print(f"\n[+] Opening Robinhood login in your browser...")
    print(f"[+] If browser doesn't open, visit manually:")
    print(f"    {auth_url}")

    # Step 2: Start callback server
    print(f"\n[+] Starting OAuth callback server on http://localhost:8080...")
    server = HTTPServer(("localhost", 8080), OAuthCallbackHandler)
    server.timeout = 120  # 2 minute timeout

    # Step 3: Open browser for login
    webbrowser.open(auth_url)

    # Step 4: Wait for callback
    print(f"\n[+] Waiting for you to approve access in browser...")
    start_time = time.time()
    while AUTH_CODE is None and AUTH_ERROR is None:
        server.handle_request()
        if time.time() - start_time > 120:
            print("❌ Timeout waiting for authorization")
            return False

    if AUTH_ERROR:
        print(f"❌ Authorization failed: {AUTH_ERROR}")
        return False

    print(f"✅ Authorization code received: {AUTH_CODE[:20]}...")

    # Step 5: Exchange code for tokens
    print(f"\n[+] Exchanging code for access/refresh tokens...")

    payload = {
        "client_id": CLIENT_ID,
        "code": AUTH_CODE,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "scope": "read write trading"
    }

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    try:
        response = requests.post(TOKEN_URL, data=payload, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"❌ Token exchange failed (HTTP {response.status_code})")
            print(f"   Response: {response.text}")
            return False

        res_data = response.json()
        access_token = res_data.get("access_token")
        refresh_token = res_data.get("refresh_token")
        expires_in = res_data.get("expires_in", 3600)

        if not access_token:
            print("❌ No access token in response")
            print(json.dumps(res_data, indent=2))
            return False

        # Step 6: Fetch user details with new token
        print(f"\n[+] Fetching account details...")
        user_headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }

        user_response = requests.get("https://api.robinhood.com/user/", headers=user_headers, timeout=10)
        user_data = user_response.json() if user_response.status_code == 200 else {}

        acc_response = requests.get("https://api.robinhood.com/accounts/", headers=user_headers, timeout=10)
        accounts = acc_response.json().get("results", []) if acc_response.status_code == 200 else []

        user_id = user_data.get("id", "")
        account_number = accounts[0].get("account_number", "") if accounts else ""

        # Step 7: Save credentials
        print(f"\n✅ AUTHENTICATION SUCCESSFUL!")
        print("-" * 70)
        print(f"CLIENT_ID:           {CLIENT_ID}")
        print(f"USER_ID:             {user_id}")
        print(f"ACCOUNT_NUMBER:      {account_number}")
        print(f"ACCESS_TOKEN:        {access_token[:15]}...{access_token[-10:]}")
        print(f"REFRESH_TOKEN:       {refresh_token[:15]}...{refresh_token[-10:]}")
        print(f"EXPIRES_IN:          {expires_in} seconds ({expires_in/3600:.1f} hours)")
        print("-" * 70)

        # Save to JSON
        output_payload = {
            "CLIENT_ID": CLIENT_ID,
            "USER_ID": user_id,
            "ACCOUNT_NUMBER": account_number,
            "ROBINHOOD_ACCESS_TOKEN": access_token,
            "ROBINHOOD_REFRESH_TOKEN": refresh_token,
            "EXPIRES_IN": expires_in
        }
        OUTPUT_JSON.write_text(json.dumps(output_payload, indent=2))

        # Save to .env
        with open(OUTPUT_ENV, "w") as f:
            f.write(f"ROBINHOOD_CLIENT_ID={CLIENT_ID}\n")
            f.write(f"ROBINHOOD_USER_ID={user_id}\n")
            f.write(f"ROBINHOOD_ACCOUNT_NUMBER={account_number}\n")
            f.write(f"ROBINHOOD_ACCESS_TOKEN={access_token}\n")
            f.write(f"ROBINHOOD_REFRESH_TOKEN={refresh_token}\n")

        print(f"\n[+] Credentials saved:")
        print(f"    {OUTPUT_JSON.resolve()}")
        print(f"    {OUTPUT_ENV.resolve()}")

        print(f"\n✅ Ready for live trading!")
        print(f"Next step: python3 test_mcp_auth.py")

        return True

    except Exception as e:
        print(f"❌ Token exchange error: {e}")
        return False


if __name__ == "__main__":
    success = start_oauth_flow()
    sys.exit(0 if success else 1)
