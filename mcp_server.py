#!/usr/bin/env python3
"""
Local MCP Server - Robinhood Trading
Lightweight HTTP server that handles OAuth + order placement
"""

import json
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

TOKEN_FILE = Path("rh_oauth.json")
PORT = 8888

class MCPHandler(BaseHTTPRequestHandler):
    """Handle requests from bot"""

    def do_POST(self):
        """Handle POST requests"""
        path = self.path.split('?')[0]  # Remove query string
        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len).decode() if content_len > 0 else ""
        
        try:
            data = json.loads(body) if body else {}
        except:
            data = {}

        # Load current token
        if not TOKEN_FILE.exists():
            self.send_json(400, {"error": "No token file"})
            return

        try:
            oauth_data = json.loads(TOKEN_FILE.read_text())
            token = oauth_data.get("access_token")

            if not token:
                self.send_json(400, {"error": "No access token"})
                return

            headers = {"Authorization": f"Bearer {token}"}

            # Route requests
            if path == "/place_order":
                self.handle_place_order(data, headers)
            elif path == "/get_positions":
                self.handle_get_positions(headers)
            elif path == "/get_portfolio":
                self.handle_get_portfolio(headers)
            elif path == "/get_quotes":
                self.handle_get_quotes(data, headers)
            else:
                self.send_json(404, {"error": "Not found"})
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def handle_place_order(self, data, headers):
        """Place an order"""
        symbol = data.get("symbol")
        quantity = data.get("quantity", 1)
        side = data.get("side", "buy")

        if not symbol:
            self.send_json(400, {"error": "Missing symbol"})
            return

        order_payload = {
            "symbol": symbol,
            "quantity": str(quantity),
            "side": side,
            "time_in_force": "day",
            "order_type": "market",
            "extended_hours": False,
        }

        resp = requests.post(
            "https://api.robinhood.com/orders/",
            headers=headers,
            json=order_payload,
            timeout=10
        )

        if resp.status_code in [200, 201]:
            order = resp.json()
            self.send_json(200, {
                "status": "success",
                "order_id": order.get("id"),
                "symbol": order.get("symbol"),
                "quantity": order.get("quantity"),
                "state": order.get("state")
            })
        else:
            self.send_json(400, {
                "status": "error",
                "code": resp.status_code,
                "message": resp.text[:200]
            })

    def handle_get_positions(self, headers):
        """Get current positions"""
        resp = requests.get(
            "https://api.robinhood.com/positions/",
            headers=headers,
            params={"nonzero": True},
            timeout=10
        )

        if resp.status_code == 200:
            self.send_json(200, {
                "status": "success",
                "positions": resp.json().get("results", [])
            })
        else:
            self.send_json(400, {
                "status": "error",
                "code": resp.status_code,
                "message": resp.text[:200]
            })

    def handle_get_portfolio(self, headers):
        """Get portfolio summary"""
        resp = requests.get(
            "https://api.robinhood.com/portfolio/",
            headers=headers,
            timeout=10
        )

        if resp.status_code == 200:
            portfolio = resp.json()
            self.send_json(200, {
                "status": "success",
                "account_value": portfolio.get("account_value"),
                "buying_power": portfolio.get("buying_power"),
                "portfolio_value": portfolio.get("portfolio_value")
            })
        else:
            self.send_json(400, {
                "status": "error",
                "code": resp.status_code,
                "message": resp.text[:200]
            })

    def handle_get_quotes(self, data, headers):
        """Get stock quotes"""
        symbols = data.get("symbols", [])
        if isinstance(symbols, str):
            symbols = [symbols]

        if not symbols:
            self.send_json(400, {"error": "Missing symbols"})
            return

        resp = requests.get(
            "https://api.robinhood.com/quotes/",
            headers=headers,
            params={"symbols": ",".join(symbols)},
            timeout=10
        )

        if resp.status_code == 200:
            self.send_json(200, {
                "status": "success",
                "quotes": resp.json().get("results", [])
            })
        else:
            self.send_json(400, {
                "status": "error",
                "code": resp.status_code,
                "message": resp.text[:200]
            })

    def send_json(self, status_code, data):
        """Send JSON response"""
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        """Suppress default logging"""
        pass


def main():
    print("=" * 70)
    print(" LOCAL MCP SERVER - Robinhood Trading")
    print("=" * 70)
    print(f"\n✅ Starting server on http://localhost:{PORT}\n")
    print("Available endpoints:")
    print("  POST /place_order     - Place buy/sell order")
    print("  POST /get_positions   - Get current positions")
    print("  POST /get_portfolio   - Get portfolio summary")
    print("  POST /get_quotes      - Get stock quotes")
    print("\n" + "=" * 70 + "\n")

    server = HTTPServer(("localhost", PORT), MCPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✅ Server stopped")


if __name__ == "__main__":
    main()
