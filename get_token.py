"""
One-time Robinhood OAuth setup for the trading bot.

Run this on your desktop (browser required):

    python get_token.py

It registers an OAuth client with Robinhood, opens your browser to log in
and approve agentic trading access, then prints the two values to set as
env vars (locally and in Railway):

    RH_CLIENT_ID
    RH_REFRESH_TOKEN

The bot uses these to mint fresh access tokens automatically — no more
manually copying short-lived ROBINHOOD_TOKEN values.
"""

import base64
import hashlib
import http.server
import json
import secrets
import urllib.parse
import webbrowser

import requests

AUTH_URL  = "https://robinhood.com/oauth"
TOKEN_URL = "https://api.robinhood.com/oauth2/token/"
REG_URL   = "https://agent.robinhood.com/oauth/trading/register"
PORT      = 8721
REDIRECT  = f"http://localhost:{PORT}/callback"


def main():
    # 1. register a client (public client, PKCE, no secret)
    reg = requests.post(REG_URL, json={
        "client_name":                "trading-bot",
        "redirect_uris":              [REDIRECT],
        "grant_types":                ["authorization_code", "refresh_token"],
        "response_types":             ["code"],
        "token_endpoint_auth_method": "none",
        "scope":                      "internal",
    }, timeout=20)
    reg.raise_for_status()
    client_id = reg.json()["client_id"]
    print(f"Registered OAuth client: {client_id}")

    # 2. PKCE + state
    verifier  = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)

    auth_url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id":             client_id,
        "redirect_uri":          REDIRECT,
        "response_type":         "code",
        "scope":                 "internal",
        "state":                 state,
        "code_challenge":        challenge,
        "code_challenge_method": "S256",
    })

    # 3. catch the redirect on localhost
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [None])[0] == state and "code" in q:
                result["code"] = q["code"][0]
                body = b"<h2>Authorized — you can close this tab.</h2>"
            else:
                body = b"<h2>Missing/invalid code. Re-run get_token.py.</h2>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("localhost", PORT), Handler)
    print("\nOpening browser for Robinhood login/approval...")
    print(f"If it doesn't open, visit:\n\n{auth_url}\n")
    webbrowser.open(auth_url)
    while "code" not in result:
        server.handle_request()
    server.server_close()

    # 4. exchange the code for tokens
    resp = requests.post(TOKEN_URL, data={
        "grant_type":    "authorization_code",
        "code":          result["code"],
        "redirect_uri":  REDIRECT,
        "client_id":     client_id,
        "code_verifier": verifier,
    }, timeout=20)
    if resp.status_code != 200:
        print(f"Token exchange failed: {resp.status_code} {resp.text[:300]}")
        return
    tok = resp.json()

    with open("rh_oauth.json", "w") as f:
        json.dump({"client_id": client_id, **tok}, f, indent=2)

    print("Success! Tokens saved to rh_oauth.json (gitignored).")
    print(f"Access token valid ~{int(tok.get('expires_in', 0)) // 3600} hours; "
          "the bot refreshes it automatically.\n")
    print("Set these env vars locally AND in Railway:\n")
    print(f"  RH_CLIENT_ID={client_id}")
    print(f"  RH_REFRESH_TOKEN={tok['refresh_token']}")


if __name__ == "__main__":
    main()
