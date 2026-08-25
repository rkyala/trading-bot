#!/usr/bin/env python3
"""
Local Robinhood MCP Server (Bridge to Agentic Endpoint)
Acts as a local MCP server that proxies requests to Robinhood's official Agentic MCP endpoint
Communicates via JSON-RPC 2.0 over stdio (local) and HTTPS (to Robinhood)
"""

import json
import sys
import os
import requests
from pathlib import Path

# ============================================================================
# CONFIGURATION LOADER
# ============================================================================

def load_config():
    """Load configuration from config.json"""
    config_file = Path("config.json")
    if not config_file.exists():
        print("❌ ERROR: config.json not found", file=sys.stderr)
        sys.exit(1)
    return json.load(open(config_file))


# Load configuration
CONFIG = load_config()

# Load token from rh_oauth.json
TOKEN_FILE = Path("rh_oauth.json")
oauth_data = json.loads(TOKEN_FILE.read_text()) if TOKEN_FILE.exists() else {}
ACCESS_TOKEN = oauth_data.get("access_token", "")

if not ACCESS_TOKEN:
    print("❌ ERROR: No access_token in rh_oauth.json", file=sys.stderr)
    sys.exit(1)

# Load from config (no hardcoding)
AGENTIC_ENDPOINT = CONFIG["robinhood"]["agentic_endpoint"]
AGENTIC_ACCOUNT = CONFIG["account"]["agentic_account_number"]

HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}


class MCPServer:
    """JSON-RPC 2.0 MCP Server for Robinhood"""

    def __init__(self):
        self.version = "2.0"
        self.account_number = AGENTIC_ACCOUNT  # From config.json
    
    def initialize(self):
        """MCP initialize call"""
        return {
            "protocolVersion": "2024-11",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "robinhood-mcp", "version": "1.0.0"}
        }
    
    def list_tools(self):
        """List available tools"""
        return {
            "tools": [
                {
                    "name": "place_equity_order",
                    "description": "Place a buy/sell order",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                            "quantity": {"type": "integer"},
                            "side": {"type": "string", "enum": ["buy", "sell"]}
                        },
                        "required": ["symbol", "quantity", "side"]
                    }
                },
                {
                    "name": "get_equity_positions",
                    "description": "Get current positions",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                {
                    "name": "get_portfolio",
                    "description": "Get portfolio summary",
                    "inputSchema": {"type": "object", "properties": {}}
                }
            ]
        }
    
    def call_tool(self, name: str, arguments: dict) -> dict:
        """Execute a tool"""
        if name == "place_equity_order":
            return self.place_order(arguments)
        elif name == "get_equity_positions":
            return self.get_positions(arguments)  # CRITICAL FIX #17: Pass arguments (includes account_number)
        elif name == "get_portfolio":
            return self.get_portfolio()
        else:
            return {"error": f"Unknown tool: {name}"}
    
    def _parse_sse_response(self, response_text: str) -> dict:
        """Parse Server-Sent Events (SSE) response from Agentic endpoint"""
        try:
            lines = response_text.strip().split('\n')
            for line in lines:
                if line.startswith('data: '):
                    json_str = line[6:]  # Remove 'data: ' prefix
                    return json.loads(json_str)
            return {"error": "No data in SSE response"}
        except json.JSONDecodeError as e:
            return {"error": f"Failed to parse SSE response: {e}"}
        except Exception as e:
            return {"error": str(e)}

    def _proxy_to_agentic(self, tool_name: str, arguments: dict) -> dict:
        """Proxy JSON-RPC tool call to Robinhood Agentic endpoint (SSE)"""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }

            resp = requests.post(
                AGENTIC_ENDPOINT,
                json=payload,
                headers=HEADERS,
                timeout=15,
                stream=False  # Read entire response
            )

            if resp.status_code == 200:
                # Parse SSE format: event: message\ndata: {...}
                parsed = self._parse_sse_response(resp.text)

                if "result" in parsed:
                    return parsed["result"]
                elif "error" in parsed:
                    return {"error": parsed["error"]}
                else:
                    return parsed
            else:
                return {"error": f"HTTP {resp.status_code}: {resp.text[:100]}"}
        except Exception as e:
            return {"error": str(e)}

    def place_order(self, args: dict) -> dict:
        """Place order via Robinhood Agentic MCP"""
        # Convert to Agentic endpoint parameters
        agentic_args = {
            "account_number": self.account_number,
            "symbol": args.get("symbol"),
            "side": args.get("side", "buy"),
            "type": args.get("order_type", "market")
        }

        # Add optional parameters if provided (must be strings)
        if "quantity" in args:
            agentic_args["quantity"] = str(args["quantity"])  # Convert to string
        if "price" in args:
            agentic_args["price"] = str(args["price"])  # Convert to string
            agentic_args["type"] = "limit"  # Switch to limit order if price provided

        return self._proxy_to_agentic("place_equity_order", agentic_args)

    def get_positions(self, arguments: dict = None) -> dict:
        """Get positions via Robinhood Agentic MCP with account_number"""
        args = arguments or {}
        # Add account number if not provided
        if "account_number" not in args:
            args["account_number"] = AGENTIC_ACCOUNT
        return self._proxy_to_agentic("get_equity_positions", args)

    def get_portfolio(self) -> dict:
        """Get portfolio via Robinhood Agentic MCP"""
        return self._proxy_to_agentic("get_portfolio", {})
    
    def handle_request(self, data: dict) -> dict:
        """Handle JSON-RPC 2.0 request"""
        method = data.get("method")
        params = data.get("params", {})
        req_id = data.get("id")
        
        result = None
        if method == "initialize":
            result = self.initialize()
        elif method == "tools/list":
            result = self.list_tools()
        elif method == "tools/call":
            result = self.call_tool(params.get("name"), params.get("arguments", {}))
        else:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}
        
        return {"jsonrpc": "2.0", "id": req_id, "result": result}


def main():
    """Main server loop"""
    server = MCPServer()
    
    # Read requests from stdin
    for line in sys.stdin:
        if line.strip():
            try:
                request = json.loads(line)
                response = server.handle_request(request)
                print(json.dumps(response), flush=True)
            except json.JSONDecodeError:
                print(json.dumps({"error": "Invalid JSON"}), flush=True)
            except Exception as e:
                print(json.dumps({"error": str(e)}), flush=True)


if __name__ == "__main__":
    main()
