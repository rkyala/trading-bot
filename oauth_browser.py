#!/usr/bin/env python3
"""
Robinhood OAuth - Browser Authentication
Opens browser for login, then gets token
"""

import webbrowser
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import sys

print("\n" + "="*60)
print("ROBINHOOD OAUTH - BROWSER LOGIN")
print("="*60)

token_data = {}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global token_data

        query = parse_qs(urlparse(self.path).query)

        if 'code' in query:
            code = query['code'][0]
            print(f"\n✅ Code received: {code[:20]}...")

            # Exchange for token
            print("[*] Getting token...")
            try:
                r = requests.post(
                    "https://api.robinhood.com/oauth2/token/",
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "client_id": "c82SH0WZOsXWOEJw",
                        "redirect_uri": "http://localhost:8888"
                    }
                )

                if r.status_code == 200:
                    token_data['token'] = r.json()['access_token']
                    print(f"✅ Token received!")

                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"<h1>Success! Close this window.</h1>")
                else:
                    print(f"❌ Error: {r.status_code}")
                    print(r.text)

            except Exception as e:
                print(f"❌ {e}")

        else:
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Waiting...</h1>")

    def log_message(self, format, *args):
        pass

try:
    print("\n[*] Opening browser...")
    auth_url = (
        "https://api.robinhood.com/oauth2/authorize/"
        "?client_id=c82SH0WZOsXWOEJw"
        "&redirect_uri=http://localhost:8888"
        "&response_type=code"
        "&scope=read+write"
    )
    webbrowser.open(auth_url)

    print("[*] Waiting for OAuth callback...")
    print("    Browser should open for login")
    print("    Click 'Allow' when prompted\n")

    server = HTTPServer(("localhost", 8888), Handler)

    for _ in range(30):  # 30 second timeout
        server.handle_request()
        if token_data.get('token'):
            break

    if token_data.get('token'):
        token = token_data['token']
        print(f"\nToken: {token[:40]}...")

        # Save
        with open("/Users/ramayalala/trading_bot/.env", "a") as f:
            f.write(f"\nROBINHOOD_AUTH_TOKEN={token}\n")

        print("✅ Saved!\n")
    else:
        print("\n❌ Timeout - no token received")

except KeyboardInterrupt:
    print("\nCancelled")
except Exception as e:
    print(f"\n❌ {e}")
