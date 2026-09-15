#!/usr/bin/env python3
"""
Self-Hosted Robinhood MCP Server
Implements MCP protocol for local Robinhood trading
Run standalone: python3 robinhood_mcp_server.py
"""

import json
import os
import sys
from pathlib import Path
import requests

# Load token
# CREDENTIALS COME FROM THE ENVIRONMENT, not a token file.
#
# This used to require rh_oauth.json and sys.exit(1) if absent, which is why
# the server died instantly under any caller that passes credentials through
# the environment — the bot sources them from .env.local. It also meant the
# server ran on whatever stale access_token that file happened to hold.
#
# _access_token() below exchanges the refresh token on demand instead.
if not ((os.getenv('RH_CLIENT_ID') or os.getenv('ROBINHOOD_CLIENT_ID')) and
        (os.getenv('RH_REFRESH_TOKEN') or os.getenv('ROBINHOOD_REFRESH_TOKEN'))):
    print('Error: RH_CLIENT_ID and RH_REFRESH_TOKEN must be set in the '
          'environment (see .env.local)', file=sys.stderr)
    sys.exit(1)
# TOKEN HANDLING — rewritten 2026-09-14.
#
# This read access_token out of an oauth JSON once at IMPORT and never
# refreshed it. Two consequences: the server ran on whatever token happened to
# be in the file (currently expired — the OAuth exchange returns invalid_grant),
# and a long session would die mid-day the moment the token aged out, with no
# retry. A trading server that silently loses auth is the failure mode this
# project keeps finding.
#
# Now: exchange the refresh token on demand and cache until shortly before
# expiry. Robinhood ROTATES refresh tokens on use, so the new one is kept.
_TOKEN = {"access": None, "expires": 0.0, "refresh": None}


def _access_token():
    import time as _t
    if _TOKEN["access"] and _t.time() < _TOKEN["expires"]:
        return _TOKEN["access"]
    cid = os.getenv("RH_CLIENT_ID") or os.getenv("ROBINHOOD_CLIENT_ID")
    rt = (_TOKEN["refresh"] or os.getenv("RH_REFRESH_TOKEN")
          or os.getenv("ROBINHOOD_REFRESH_TOKEN"))
    if not (cid and rt):
        return None
    try:
        r = requests.post("https://api.robinhood.com/oauth2/token/", timeout=20,
                          data={"grant_type": "refresh_token",
                                "refresh_token": rt, "client_id": cid})
        if r.status_code != 200:
            return None
        d = r.json()
        _TOKEN["access"] = d.get("access_token")
        if d.get("refresh_token"):
            _TOKEN["refresh"] = d["refresh_token"]
            # PERSIST IT. Robinhood refresh tokens are SINGLE USE — verified
            # 2026-09-14: exchanging a token returns a replacement AND
            # invalidates the original immediately (the second use of the same
            # token returns invalid_grant).
            #
            # Caching the replacement in memory only is therefore a one-shot
            # bomb: the process works until it restarts, then reads the spent
            # token from the environment and can never authenticate again. A
            # token was destroyed this way before this was written.
            _persist_refresh_token(d["refresh_token"])
        _TOKEN["expires"] = _t.time() + max(60, int(d.get("expires_in", 3600)) - 300)
        return _TOKEN["access"]
    except Exception:
        return None



def _persist_refresh_token(token):
    """
    Write the rotated refresh token back to .env.local.

    Atomic (temp file + replace) so a crash mid-write cannot leave the file
    truncated — losing this value means losing account access until a human
    reissues it by hand.
    """
    import tempfile
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.local")
    try:
        lines, seen = [], False
        if os.path.exists(path):
            with open(path) as fh:
                for line in fh:
                    if line.startswith("RH_REFRESH_TOKEN="):
                        lines.append(f"RH_REFRESH_TOKEN={token}\n")
                        seen = True
                    else:
                        lines.append(line)
        if not seen:
            lines.append(f"RH_REFRESH_TOKEN={token}\n")
        d = os.path.dirname(path)
        fd, tmp = tempfile.mkstemp(dir=d)
        with os.fdopen(fd, "w") as fh:
            fh.writelines(lines)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        print("refresh token rotated and persisted", file=sys.stderr)
    except Exception as e:
        # LOUD. A silent failure here means the next restart cannot log in.
        print(f"CRITICAL: could not persist rotated refresh token: {e}",
              file=sys.stderr)


def _headers():
    t = _access_token()
    return {"Authorization": f"Bearer {t}", "Accept": "application/json"} if t else None



_CACHE = {"account": None, "instruments": {}}


def _text(obj):
    """MCP content envelope."""
    return {"content": [{"type": "text", "text": json.dumps(obj, indent=2)}]}


def _account_url():
    """Account URL for RH_ACCOUNT_NUMBER. Refuses to guess — trading the
    wrong account is unrecoverable."""
    if _CACHE["account"]:
        return _CACHE["account"]
    h = _headers()
    want = os.getenv("RH_ACCOUNT_NUMBER")
    if not (h and want):
        return None
    try:
        r = requests.get("https://api.robinhood.com/accounts/", headers=h, timeout=15)
        for a in (r.json() or {}).get("results") or []:
            if str(a.get("account_number")) == str(want):
                _CACHE["account"] = a.get("url")
                return _CACHE["account"]
    except Exception:
        pass
    return None


def _instrument_url(symbol):
    s = str(symbol).upper()
    if s in _CACHE["instruments"]:
        return _CACHE["instruments"][s]
    h = _headers()
    if not h:
        return None
    try:
        r = requests.get("https://api.robinhood.com/instruments/",
                         params={"symbol": s}, headers=h, timeout=15)
        for i in (r.json() or {}).get("results") or []:
            if str(i.get("symbol")).upper() == s and i.get("tradeable") is not False:
                _CACHE["instruments"][s] = i.get("url")
                return _CACHE["instruments"][s]
    except Exception:
        pass
    return None


class MCPServer:
    """MCP Server for Robinhood"""
    
    def __init__(self):
        self.tools = self.define_tools()
    
    def define_tools(self):
        """Define available MCP tools"""
        return [
            {
                "name": "place_equity_order",
                "description": "Place a buy/sell order for a stock",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Stock symbol (e.g., NVDA)"},
                        "quantity": {"type": "integer", "description": "Number of shares"},
                        "side": {"type": "string", "enum": ["buy", "sell"], "description": "Order side"},
                    },
                    "required": ["symbol", "quantity", "side"]
                }
            },
            {
                "name": "get_equity_positions",
                "description": "Get current equity positions",
                "inputSchema": {"type": "object", "properties": {}}
            },
            {
                "name": "get_portfolio",
                "description": "Get portfolio summary",
                "inputSchema": {"type": "object", "properties": {}}
            },
            {
                "name": "get_equity_quotes",
                "description": "Get stock quotes",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbols": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["symbols"]
                }
            }
        ]
    
    def handle_message(self, message):
        """Handle incoming MCP message"""
        msg_type = message.get("method")
        
        if msg_type == "initialize":
            return self.initialize()
        elif msg_type == "tools/list":
            return self.list_tools()
        elif msg_type == "tools/call":
            return self.call_tool(message)
        else:
            return {"error": f"Unknown method: {msg_type}"}
    
    def initialize(self):
        """MCP initialize response"""
        return {
            "protocolVersion": "2024-11",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "robinhood-mcp",
                "version": "1.0.0"
            }
        }
    
    def list_tools(self):
        """List available tools"""
        return {"tools": self.tools}
    
    def call_tool(self, message):
        """Call a tool"""
        tool_name = message.get("params", {}).get("name")
        tool_input = message.get("params", {}).get("arguments", {})
        
        try:
            if tool_name == "place_equity_order":
                return self.place_order(tool_input)
            elif tool_name == "get_equity_positions":
                return self.get_positions()
            elif tool_name == "get_portfolio":
                return self.get_portfolio()
            elif tool_name == "get_equity_quotes":
                return self.get_quotes(tool_input)
            else:
                return {"error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            return {"error": str(e)}
    
    def place_order(self, args):
        """Place order on Robinhood"""
        symbol = args.get("symbol")
        quantity = args.get("quantity", 1)
        side = args.get("side", "buy")
        
        # ORDER PAYLOAD — completed 2026-09-14.
        #
        # This sent only symbol/quantity/side/time_in_force/order_type. The
        # Robinhood /orders/ endpoint REQUIRES the account URL and the
        # instrument URL; without them it 400s. There is no record of this
        # server ever placing a successful order, which is consistent.
        #
        # ref_id makes a retried transport failure idempotent rather than a
        # double fill.
        import uuid as _uuid
        acct = _account_url()
        if not acct:
            return _text({"status": "error",
                          "error": "no account URL — set RH_ACCOUNT_NUMBER"})
        inst = _instrument_url(symbol)
        if not inst:
            return _text({"status": "error",
                          "error": f"no tradeable instrument for {symbol}"})
        payload = {
            "account": acct,
            "instrument": inst,
            "symbol": symbol,
            "quantity": str(quantity),
            "side": side,
            "time_in_force": "gfd",
            "type": "market",
            "trigger": "immediate",
            "extended_hours": False,
            "ref_id": str(_uuid.uuid4()),
        }
        
        resp = requests.post(
            "https://api.robinhood.com/orders/",
            headers=_headers(),
            json=payload,
            timeout=10
        )
        
        if resp.status_code in [200, 201]:
            order = resp.json()
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "status": "success",
                        "order_id": order.get("id"),
                        "symbol": order.get("symbol"),
                        "quantity": order.get("quantity"),
                        "state": order.get("state")
                    }, indent=2)
                }]
            }
        else:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: {resp.status_code} - {resp.text[:200]}"
                }]
            }
    
    def get_positions(self):
        """Get current positions"""
        resp = requests.get(
            "https://api.robinhood.com/positions/",
            headers=_headers(),
            params={"nonzero": True},
            timeout=10
        )
        
        if resp.status_code == 200:
            positions = resp.json().get("results", [])
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "status": "success",
                        "positions": positions
                    }, indent=2)
                }]
            }
        else:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: {resp.text[:200]}"
                }]
            }
    
    def get_portfolio(self):
        """Get portfolio summary"""
        resp = requests.get(
            "https://api.robinhood.com/portfolio/",
            headers=_headers(),
            timeout=10
        )
        
        if resp.status_code == 200:
            portfolio = resp.json()
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "account_value": portfolio.get("account_value"),
                        "buying_power": portfolio.get("buying_power"),
                        "portfolio_value": portfolio.get("portfolio_value")
                    }, indent=2)
                }]
            }
        else:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: {resp.text[:200]}"
                }]
            }
    
    def get_quotes(self, args):
        """Get stock quotes"""
        symbols = args.get("symbols", [])
        
        resp = requests.get(
            "https://api.robinhood.com/quotes/",
            headers=_headers(),
            params={"symbols": ",".join(symbols)},
            timeout=10
        )
        
        if resp.status_code == 200:
            quotes = resp.json().get("results", [])
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "quotes": quotes
                    }, indent=2)
                }]
            }
        else:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: {resp.text[:200]}"
                }]
            }


def main():
    """Run MCP server - reads JSON-RPC from stdin"""
    server = MCPServer()
    
    print(json.dumps(server.initialize()), file=sys.stdout, flush=True)
    
    # Read and process incoming messages
    for line in sys.stdin:
        if line.strip():
            try:
                message = json.loads(line)
                response = server.handle_message(message)
                print(json.dumps(response), file=sys.stdout, flush=True)
            except Exception as e:
                print(json.dumps({"error": str(e)}), file=sys.stdout, flush=True)


if __name__ == "__main__":
    main()
