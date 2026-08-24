#!/usr/bin/env python3
"""
Self-Hosted Robinhood MCP Server
Implements MCP protocol for local Robinhood trading
Run standalone: python3 robinhood_mcp_server.py
"""

import json
import sys
from pathlib import Path
import requests

# Load token
TOKEN_FILE = Path("rh_oauth.json")

if not TOKEN_FILE.exists():
    print("Error: rh_oauth.json not found. Run: python3 get_token.py", file=sys.stderr)
    sys.exit(1)

oauth_data = json.loads(TOKEN_FILE.read_text())
ACCESS_TOKEN = oauth_data.get("access_token")
HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}"}


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
        
        payload = {
            "symbol": symbol,
            "quantity": str(quantity),
            "side": side,
            "time_in_force": "day",
            "order_type": "market",
            "extended_hours": False,
        }
        
        resp = requests.post(
            "https://api.robinhood.com/orders/",
            headers=HEADERS,
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
            headers=HEADERS,
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
            headers=HEADERS,
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
            headers=HEADERS,
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
