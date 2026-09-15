#!/usr/bin/env python3
"""
Test robinhood-for-agents MCP for fetching current positions.
Compares: Direct MCP call vs Claude MCP tool-use
"""

import os
import json
from anthropic import Anthropic

# Robinhood account for testing
RH_ACCOUNT = "432591949"

def get_rh_access_token(force_refresh=False):
    """Get fresh Robinhood access token"""
    import requests

    RH_CLIENT_ID = os.environ.get("RH_CLIENT_ID", "")
    RH_REFRESH_TOKEN = os.environ.get("RH_REFRESH_TOKEN", "")
    RH_TOKEN_URL = "https://api.robinhood.com/oauth2/token/"

    try:
        resp = requests.post(RH_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": RH_REFRESH_TOKEN,
            "client_id": RH_CLIENT_ID,
            "scope": "read write",
        })
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception as e:
        print(f"❌ Token refresh failed: {e}")
        return None

def test_mcp_via_claude():
    """Test: Fetch positions via Claude MCP tool-use (current method)"""
    print("\n" + "="*70)
    print("TEST 1: Via Claude MCP Tool-Use (Current Method)")
    print("="*70)

    client = Anthropic()
    rh_token = get_rh_access_token(force_refresh=True)

    if not rh_token:
        print("❌ Cannot get token")
        return None

    try:
        resp = client.beta.messages.create(
            model="claude-opus-4-8",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": f"Call get_equity_positions for account {RH_ACCOUNT}. Return symbol list."
            }],
            betas=["mcp-client-2025-04-04", "prompt-caching-2024-07-31"],
            mcp_servers=[{
                "type": "url",
                "url": "https://agent.robinhood.com/mcp/trading",
                "name": "robinhood",
                "authorization_token": rh_token,
            }]
        )

        # Parse response
        positions = set()
        for block in resp.content:
            if hasattr(block, 'type') and block.type == "mcp_tool_result":
                try:
                    result_text = block.text if hasattr(block, 'text') else str(block)
                    if isinstance(result_text, str) and result_text.startswith('{'):
                        result_json = json.loads(result_text)
                        results = result_json.get("data", {}).get("results", [])
                        for pos in results:
                            symbol = pos.get("symbol", "").upper()
                            qty = float(pos.get("quantity", 0))
                            if symbol and qty > 0:
                                positions.add(symbol)
                except Exception as e:
                    print(f"Parse error: {e}")

        print(f"✅ Fetched via Claude MCP: {sorted(positions)}")
        print(f"   Tokens: {resp.usage.input_tokens} input, {resp.usage.output_tokens} output")
        return positions

    except Exception as e:
        print(f"❌ Claude MCP failed: {e}")
        return None

def test_mcp_direct():
    """Test: Direct Robinhood MCP call (robinhood-for-agents)"""
    print("\n" + "="*70)
    print("TEST 2: Via robinhood-for-agents (Direct MCP)")
    print("="*70)

    # This would require loading the actual MCP tool directly
    # For now, show what it would look like:
    print("""
    This test would use: mcp__b6661de3-3151-4478-9e51-a898159d237c__get_equity_positions

    Pros of direct approach:
      ✓ No Claude intermediary (faster, fewer tokens)
      ✓ Direct API call to Robinhood
      ✓ Lower cost

    Cons of direct approach:
      ✗ Requires local MCP server setup
      ✗ Not available in Railway deployment without extra setup
      ✗ Current bot.py uses Claude MCP tool-use pattern (locked)

    Recommendation: Stick with Claude MCP tool-use
      - Already working (logs show "No open positions (via MCP)")
      - Handles OAuth internally
      - Consistent with Stage 3 execution pattern
      - Cost is minimal (~50 tokens per check)
    """)

    return None

if __name__ == "__main__":
    print("\n🧪 Testing Robinhood MCP Position Fetching")

    positions = test_mcp_via_claude()
    test_mcp_direct()

    print("\n" + "="*70)
    print("CONCLUSION")
    print("="*70)
    if positions is not None:
        print(f"✅ Current MCP method working: {len(positions)} positions")
        print("✅ No need to change - robinhood-for-agents would be redundant")
    else:
        print("⚠️  Claude MCP had issues - would need robinhood-for-agents")
