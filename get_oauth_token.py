#!/usr/bin/env python3
"""
Robinhood OAuth Token Generator with Browser Login
Opens browser for OAuth authentication
"""

import sys
import json
import webbrowser
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

print("\n" + "="*80)
print("ROBINHOOD OAUTH TOKEN GENERATOR (Browser Login)")
print("="*80)

# OAuth Configuration
ROBINHOOD_AUTH_URL = "https://api.robinhood.com/oauth2/authorize/"
ROBINHOOD_TOKEN_URL = "https://api.robinhood.com/oauth2/token/"
CLIENT_ID = "c82SH0WZOsXWOEJw"
REDIRECT_URI = "http://localhost:8888/callback"

token_received = None
server_running = True

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handle OAuth callback"""

    def do_GET(self):
        global token_received

        # Parse callback URL
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)

        if 'code' in query_params:
            auth_code = query_params['code'][0]
            print(f"\n✅ Authorization code received: {auth_code[:20]}...")

            # Exchange code for token
            print("[*] Exchanging code for OAuth token...")
            try:
                import requests

                response = requests.post(
                    ROBINHOOD_TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "code": auth_code,
                        "client_id": CLIENT_ID,
                        "redirect_uri": REDIRECT_URI,
                        "scope": "read write"
                    },
                    timeout=10
                )

                if response.status_code == 200:
                    data = response.json()
                    token_received = data.get("access_token")

                    # Send success page
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    html_response = """
                    <html>
                    <body style="font-family: Arial; text-align: center; padding: 50px;">
                        <h1>Success!</h1>
                        <p>OAuth token received successfully.</p>
                        <p>You can close this window and return to terminal.</p>
                    </body>
                    </html>
                    """.encode('utf-8')
                    self.wfile.write(html_response)

                    print("✅ OAuth token received!")
                else:
                    print(f"❌ Token exchange failed (Status {response.status_code})")
                    print(f"Response: {response.text}")

            except Exception as e:
                print(f"❌ Error: {e}")

        elif 'error' in query_params:
            error = query_params['error'][0]
            print(f"ERROR: OAuth error: {error}")

            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            html_error = """
            <html>
            <body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1>Error</h1>
                <p>OAuth authentication failed.</p>
                <p>Please try again.</p>
            </body>
            </html>
            """.encode('utf-8')
            self.wfile.write(html_error)

    def log_message(self, format, *args):
        # Suppress default logging
        pass

def start_oauth_flow():
    """Start OAuth browser flow"""

    print("\n" + "="*80)
    print("STEP 1: Opening Robinhood Login in Browser")
    print("="*80)

    # Build authorization URL
    auth_url = (
        f"{ROBINHOOD_AUTH_URL}?"
        f"client_id={CLIENT_ID}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"response_type=code&"
        f"scope=read%20write"
    )

    print(f"\n[*] Opening browser for login...")
    print(f"    URL: {auth_url[:60]}...")

    # Open browser
    webbrowser.open(auth_url)

    print("\n" + "="*80)
    print("STEP 2: Local Server Listening for Callback")
    print("="*80)
    print("\n[*] Waiting for OAuth callback...")
    print("    Listening on: http://localhost:8888/callback")
    print("\n    1. Log in with your Robinhood credentials in the browser")
    print("    2. Authorize access when prompted")
    print("    3. You'll be redirected back here")

    try:
        # Start local server to receive callback
        server = HTTPServer(("localhost", 8888), OAuthCallbackHandler)

        # Wait for callback (with timeout)
        start_time = time.time()
        timeout = 300  # 5 minutes

        while time.time() - start_time < timeout:
            server.handle_request()

            if token_received:
                print("\n✅ OAuth flow completed!")
                return token_received

        print("\n❌ Timeout waiting for OAuth callback")
        return None

    except OSError as e:
        print(f"\n❌ Error: Port 8888 already in use")
        print(f"   Try closing other processes or change port")
        return None
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return None

# Main flow
try:
    token = start_oauth_flow()

    if token:
        print("\n" + "="*80)
        print("SAVING TOKEN")
        print("="*80)

        # Save to .env
        env_file = Path("/Users/ramayalala/trading_bot/.env")

        with open(env_file, "a") as f:
            f.write(f"\nROBINHOOD_AUTH_TOKEN={token}\n")

        print(f"\n✅ Token saved!")
        print(f"   Length: {len(token)} characters")
        print(f"   First 20 chars: {token[:20]}...")
        print(f"   Saved to: {env_file}")

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
   tail -f ~/trading_bot/bot_v38.log | grep "MCP"

Expected output:
   MCP Status: ENABLED ✅
   ✅ MCP ORDER: SYMBOL BUY X @ $price
""")
    else:
        print("\n❌ Failed to get OAuth token")
        sys.exit(1)

except KeyboardInterrupt:
    print("\n\nExiting...")
    sys.exit(0)
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
