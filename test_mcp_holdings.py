#!/usr/bin/env python3
"""
Test Official Robinhood MCP - Fetch Current Holdings
Verify MCP connection and retrieve live account data
"""

import json
import subprocess
import sys

def test_mcp():
    print("=" * 80)
    print(" Testing Official Robinhood MCP - Fetch Current Holdings")
    print("=" * 80)

    print("\n[+] Starting official Robinhood MCP server...")
    process = subprocess.Popen(
        ["npx", "-y", "@modelcontextprotocol/server-robinhood"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    print("✅ MCP server started\n")

    req_id = 1

    # Test 1: Get Portfolio
    print("[1] PORTFOLIO SUMMARY")
    print("-" * 80)
    req = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {
            "name": "get_portfolio",
            "arguments": {}
        }
    }
    req_id += 1

    process.stdin.write(json.dumps(req) + "\n")
    process.stdin.flush()
    resp = json.loads(process.stdout.readline())

    if "result" in resp:
        portfolio = resp["result"]
        if "error" in portfolio:
            print(f"❌ Error: {portfolio['error']}")
        else:
            print(f"✅ Account Value:  ${portfolio.get('account_value', 0)}")
            print(f"✅ Buying Power:   ${portfolio.get('buying_power', 0)}")
            print(f"✅ Portfolio Value: ${portfolio.get('portfolio_value', 0)}")
    else:
        print(f"❌ {resp}")

    # Test 2: Get Positions
    print("\n[2] CURRENT HOLDINGS")
    print("-" * 80)
    req = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {
            "name": "get_equity_positions",
            "arguments": {}
        }
    }
    req_id += 1

    process.stdin.write(json.dumps(req) + "\n")
    process.stdin.flush()
    resp = json.loads(process.stdout.readline())

    if "result" in resp:
        positions = resp["result"]
        if "error" in positions:
            print(f"❌ Error: {positions['error']}")
        else:
            pos_list = positions.get("positions", [])
            if pos_list:
                print(f"✅ Found {len(pos_list)} position(s):\n")
                for pos in pos_list:
                    symbol = pos.get("symbol", "?")
                    qty = float(pos.get("quantity", 0))
                    avg_price = float(pos.get("average_buy_price", 0))
                    print(f"  {symbol:8} | Qty: {qty:8.0f} | Entry: ${avg_price:8.2f}")
            else:
                print("✅ No holdings (cash account)")
    else:
        print(f"❌ {resp}")

    # Test 3: List Available Tools
    print("\n[3] AVAILABLE MCP TOOLS")
    print("-" * 80)
    req = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/list",
        "params": {}
    }
    req_id += 1

    process.stdin.write(json.dumps(req) + "\n")
    process.stdin.flush()
    resp = json.loads(process.stdout.readline())

    if "result" in resp:
        tools = resp["result"].get("tools", [])
        print(f"✅ {len(tools)} tools available:\n")
        for tool in tools[:8]:
            print(f"  • {tool.get('name')}")

    # Cleanup
    print("\n[*] Shutting down MCP server...")
    process.terminate()
    process.wait(timeout=5)
    print("✅ Done\n")

if __name__ == "__main__":
    try:
        test_mcp()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nTroubleshooting:")
        print("  1. Is Node.js installed? (node --version)")
        print("  2. Does rh_oauth.json exist?")
        print("  3. Are ROBINHOOD_* env vars set?")
