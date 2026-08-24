#!/usr/bin/env python3
"""
Pure Local MCP Client Engine
Communicates directly with local MCP server via stdio.
No Claude tokens, no external APIs - 100% local.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


class LocalMCPClient:
    """Pure local MCP client using official @modelcontextprotocol/server-robinhood"""
    
    def __init__(self, env_file: str = ".env.mcp"):
        """Initialize local MCP server subprocess"""
        # Load credentials
        self.env = os.environ.copy()
        env_path = Path(env_file)
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    self.env[k.strip()] = v.strip()
        
        print("[+] Starting local MCP server (npx @modelcontextprotocol/server-robinhood)...")
        
        # Start local MCP server
        self.process = subprocess.Popen(
            ["npx", "-y", "@modelcontextprotocol/server-robinhood"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.env,
            bufsize=1  # Line buffered
        )
        self.req_id = 1
        print("✅ MCP server started on stdio\n")
    
    def _send_rpc(self, method: str, params: dict = None) -> dict:
        """Send JSON-RPC 2.0 request to local MCP server"""
        payload = {
            "jsonrpc": "2.0",
            "id": self.req_id,
            "method": method,
            "params": params or {}
        }
        self.req_id += 1
        
        try:
            json_str = json.dumps(payload) + "\n"
            self.process.stdin.write(json_str)
            self.process.stdin.flush()
            
            # Read response
            response_line = self.process.stdout.readline()
            if not response_line:
                return {"error": "No response from MCP server"}
            
            return json.loads(response_line)
        except Exception as e:
            return {"error": str(e)}
    
    def list_tools(self) -> list:
        """List all available MCP tools"""
        res = self._send_rpc("tools/list")
        return res.get("result", {}).get("tools", [])
    
    def place_order(self, symbol: str, quantity: int, side: str = "buy") -> dict:
        """Place order via MCP"""
        res = self._send_rpc("tools/call", {
            "name": "place_equity_order",
            "arguments": {
                "symbol": symbol,
                "quantity": quantity,
                "side": side,
                "time_in_force": "day",
                "order_type": "market"
            }
        })
        return res
    
    def get_positions(self) -> dict:
        """Get current positions via MCP"""
        res = self._send_rpc("tools/call", {
            "name": "get_equity_positions",
            "arguments": {}
        })
        return res
    
    def get_portfolio(self) -> dict:
        """Get portfolio summary via MCP"""
        res = self._send_rpc("tools/call", {
            "name": "get_portfolio",
            "arguments": {}
        })
        return res
    
    def stop(self):
        """Terminate local MCP server"""
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=5)


if __name__ == "__main__":
    print("=" * 70)
    print(" Local MCP Client - Pure Local (No Claude/Tokens Required)")
    print("=" * 70)
    
    client = LocalMCPClient()
    
    # Test 1: List tools
    print("\n[1] Listing available tools...")
    tools = client.list_tools()
    print(f"✅ Found {len(tools)} tools:")
    for tool in tools[:5]:
        print(f"   - {tool.get('name')}")
    
    # Test 2: Get portfolio
    print("\n[2] Fetching portfolio...")
    portfolio = client.get_portfolio()
    print(f"Response: {json.dumps(portfolio, indent=2)[:300]}")
    
    # Test 3: Get positions
    print("\n[3] Fetching positions...")
    positions = client.get_positions()
    print(f"Response: {json.dumps(positions, indent=2)[:300]}")
    
    # Cleanup
    print("\n[*] Shutting down...")
    client.stop()
    print("✅ Done")
