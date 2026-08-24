#!/usr/bin/env python3
"""
Local MCP Client - 100% Local, No Claude/Tokens
Connects to local MCP server via stdio JSON-RPC 2.0
"""

import json
import subprocess
import sys
from pathlib import Path


class LocalMCPClient:
    """Client for local MCP server"""
    
    def __init__(self):
        """Start local MCP server"""
        print("[+] Starting local MCP server...")
        self.process = subprocess.Popen(
            [sys.executable, "robinhood_mcp_local.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=Path.cwd(),
            bufsize=1
        )
        self.req_id = 1
        print("✅ Local MCP server started\n")
    
    def _rpc(self, method: str, params: dict = None) -> dict:
        """Send JSON-RPC request"""
        req = {
            "jsonrpc": "2.0",
            "id": self.req_id,
            "method": method,
            "params": params or {}
        }
        self.req_id += 1
        
        self.process.stdin.write(json.dumps(req) + "\n")
        self.process.stdin.flush()
        
        resp_line = self.process.stdout.readline()
        return json.loads(resp_line) if resp_line else {"error": "No response"}
    
    def list_tools(self):
        """List tools"""
        return self._rpc("tools/list")
    
    def place_order(self, symbol: str, qty: int, side: str = "buy"):
        """Place order"""
        return self._rpc("tools/call", {
            "name": "place_equity_order",
            "arguments": {"symbol": symbol, "quantity": qty, "side": side}
        })
    
    def get_positions(self):
        """Get positions"""
        return self._rpc("tools/call", {
            "name": "get_equity_positions",
            "arguments": {}
        })
    
    def get_portfolio(self):
        """Get portfolio"""
        return self._rpc("tools/call", {
            "name": "get_portfolio",
            "arguments": {}
        })
    
    def stop(self):
        """Stop server"""
        self.process.terminate()


if __name__ == "__main__":
    print("=" * 70)
    print(" Pure Local MCP - No Claude/Tokens/External APIs")
    print("=" * 70 + "\n")
    
    client = LocalMCPClient()
    
    # Test 1: List tools
    print("[1] Available Tools:")
    tools = client.list_tools()
    if "result" in tools:
        for t in tools["result"]["tools"]:
            print(f"   ✅ {t['name']}")
    
    # Test 2: Get portfolio
    print("\n[2] Fetching Portfolio...")
    portfolio = client.get_portfolio()
    if "result" in portfolio:
        print(f"   ✅ {json.dumps(portfolio['result'], indent=6)}")
    else:
        print(f"   ❌ {portfolio}")
    
    # Test 3: Get positions
    print("\n[3] Fetching Positions...")
    positions = client.get_positions()
    if "result" in positions:
        pos_list = positions["result"].get("positions", [])
        print(f"   ✅ Found {len(pos_list)} positions")
        for p in pos_list[:3]:
            print(f"      - {p.get('symbol', '?')}: {p.get('quantity', 0)} shares")
    else:
        print(f"   ❌ {positions}")
    
    print("\n[*] Shutting down...")
    client.stop()
    print("✅ Done\n")
