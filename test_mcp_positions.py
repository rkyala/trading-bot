#!/usr/bin/env python3
"""
Test: Verify MCP can fetch actual Robinhood positions
"""

import os
import sys
import json
from anthropic import Anthropic

# Load credentials
RH_ACCOUNT = "432591949"
RH_CLIENT_ID = os.getenv("ROBINHOOD_CLIENT_ID")
RH_REFRESH_TOKEN = os.getenv("ROBINHOOD_REFRESH_TOKEN")

if not RH_CLIENT_ID or not RH_REFRESH_TOKEN:
    print("❌ Missing Robinhood credentials")
    print("   Set ROBINHOOD_CLIENT_ID and ROBINHOOD_REFRESH_TOKEN")
    sys.exit(1)

print("\n" + "="*70)
print("  TEST: MCP Position Fetching")
print("="*70 + "\n")

# Get Robinhood token
print("1️⃣  Getting Robinhood OAuth token...")
client = Anthropic()

try:
    # This would need the actual OAuth flow, but for testing we'll use the env token
    rh_token = RH_REFRESH_TOKEN  # In real code, this needs refresh logic
    print(f"   ✓ Got token (first 20 chars): {rh_token[:20]}...")
except Exception as e:
    print(f"   ✗ Failed to get token: {e}")
    sys.exit(1)

# Test MCP connection
print("\n2️⃣  Testing MCP connection to Robinhood...")
try:
    resp = client.beta.messages.create(
        model="claude-opus-4-8",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": f"Use the get_equity_positions tool to fetch ALL open positions for account {RH_ACCOUNT}. Return complete results."
        }],
        betas=["mcp-client-2025-04-04", "prompt-caching-2024-07-31"],
        mcp_servers=[{
            "type": "url",
            "url": "https://agent.robinhood.com/mcp/trading",
            "name": "robinhood",
            "authorization_token": rh_token,
        }]
    )
    print(f"   ✓ MCP responded with {len(resp.content)} blocks")
except Exception as e:
    print(f"   ✗ MCP call failed: {e}")
    sys.exit(1)

# Parse response
print("\n3️⃣  Parsing MCP response...")
owned_symbols = set()

for i, block in enumerate(resp.content):
    block_type = getattr(block, 'type', 'unknown')
    print(f"   Block {i}: {block_type}")

    if block_type == "mcp_tool_result":
        try:
            result_text = block.text if hasattr(block, 'text') else str(block)
            print(f"   Result text (first 200 chars): {result_text[:200]}...")

            if isinstance(result_text, str) and result_text.startswith('{'):
                result_json = json.loads(result_text)

                # Try different formats
                positions = result_json.get("data", {}).get("positions", [])
                if not positions:
                    positions = result_json.get("data", {}).get("results", [])
                if not positions:
                    positions = result_json.get("results", []) or result_json.get("positions", [])

                print(f"   ✓ Parsed {len(positions)} positions")

                for pos in positions:
                    symbol = pos.get("symbol", "").upper()
                    qty = float(pos.get("quantity", 0))
                    if symbol and qty > 0:
                        owned_symbols.add(symbol)
                        print(f"     • {symbol}: {qty} shares")

        except Exception as parse_error:
            print(f"   ✗ Parse error: {parse_error}")

    elif block_type == "text":
        text = getattr(block, 'text', '')[:100]
        print(f"   Text: {text}...")

print("\n" + "="*70)
if owned_symbols:
    print(f"✅ SUCCESS: MCP fetched {len(owned_symbols)} positions")
    print(f"   Owned symbols: {sorted(owned_symbols)}")
else:
    print(f"⚠️  WARNING: MCP returned empty positions list")
    print(f"   Check: Are there actually positions in account {RH_ACCOUNT}?")
print("="*70 + "\n")
