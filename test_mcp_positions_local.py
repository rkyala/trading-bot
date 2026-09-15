#!/usr/bin/env python3
"""
Local test: Fetch positions via MCP and show raw response
"""

import os
import json
import sys
from anthropic import Anthropic

RH_ACCOUNT = "432591949"

def get_rh_access_token(force_refresh=False):
    """Get fresh Robinhood access token"""
    import requests

    RH_CLIENT_ID = os.environ.get("RH_CLIENT_ID", "")
    RH_REFRESH_TOKEN = os.environ.get("RH_REFRESH_TOKEN", "")
    RH_TOKEN_URL = "https://api.robinhood.com/oauth2/token/"

    if not RH_CLIENT_ID or not RH_REFRESH_TOKEN:
        print("❌ Missing RH_CLIENT_ID or RH_REFRESH_TOKEN")
        return None

    try:
        resp = requests.post(RH_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": RH_REFRESH_TOKEN,
            "client_id": RH_CLIENT_ID,
            "scope": "read write",
        }, timeout=5)
        resp.raise_for_status()
        token = resp.json()["access_token"]
        print(f"✅ Got token (first 20 chars): {token[:20]}...")
        return token
    except Exception as e:
        print(f"❌ Token refresh failed: {e}")
        return None

def test_mcp_positions():
    """Test MCP position fetching with detailed output"""
    print("\n" + "="*70)
    print("LOCAL TEST: MCP Position Fetching")
    print("="*70)

    client = Anthropic()
    rh_token = get_rh_access_token(force_refresh=True)

    if not rh_token:
        print("❌ Cannot proceed without token")
        return

    print(f"\nCalling MCP with account: {RH_ACCOUNT}")
    print("-" * 70)

    try:
        resp = client.beta.messages.create(
            model="claude-opus-4-8",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": f"Call get_equity_positions for account {RH_ACCOUNT}. Return the complete results."
            }],
            betas=["mcp-client-2025-04-04", "prompt-caching-2024-07-31"],
            mcp_servers=[{
                "type": "url",
                "url": "https://agent.robinhood.com/mcp/trading",
                "name": "robinhood",
                "authorization_token": rh_token,
            }]
        )

        print(f"\n📊 Response Details:")
        print(f"  Stop reason: {resp.stop_reason}")
        print(f"  Content blocks: {len(resp.content)}")
        print(f"  Tokens: {resp.usage.input_tokens} input, {resp.usage.output_tokens} output")

        print(f"\n📋 Content Blocks:")
        for i, block in enumerate(resp.content):
            block_type = getattr(block, 'type', 'unknown')
            print(f"\n  Block {i}: {block_type}")

            if block_type == "text":
                text_content = getattr(block, 'text', '')
                print(f"    Text (first 150 chars): {text_content[:150]}")

            elif block_type == "mcp_tool_result":
                result_text = getattr(block, 'text', '')
                print(f"    Tool result (first 300 chars):")
                print(f"    {result_text[:300]}")

                # Try to parse as JSON
                if result_text.startswith('{'):
                    try:
                        result_json = json.loads(result_text)
                        print(f"\n    ✅ Parsed JSON successfully")
                        print(f"    Top-level keys: {list(result_json.keys())}")

                        # Navigate structure
                        data = result_json.get("data", {})
                        print(f"    'data' keys: {list(data.keys())}")

                        results = data.get("results", [])
                        print(f"    Number of results: {len(results)}")

                        if results:
                            print(f"\n    First result sample:")
                            print(json.dumps(results[0], indent=6))

                            print(f"\n    ✅ All positions:")
                            for pos in results:
                                symbol = pos.get("symbol", "?")
                                qty = pos.get("quantity", "?")
                                print(f"       {symbol}: {qty} shares")
                        else:
                            print(f"    ⚠️  No results in response")

                    except json.JSONDecodeError as e:
                        print(f"    ❌ JSON parse error: {e}")
                else:
                    print(f"    ⚠️  Not JSON format")

        print("\n" + "="*70)
        print("TEST COMPLETE")
        print("="*70)

    except Exception as e:
        print(f"\n❌ Error during MCP call: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_mcp_positions()
