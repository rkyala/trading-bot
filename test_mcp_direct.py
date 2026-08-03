#!/usr/bin/env python3
"""
Direct MCP test - place a single test order through Robinhood MCP.
"""
import os
import sys
import anthropic
import logging
import json

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Config
RH_ACCOUNT = "432591949"
RH_CLIENT_ID = os.environ.get("RH_CLIENT_ID", "")
RH_REFRESH_TOKEN = os.environ.get("RH_REFRESH_TOKEN", "")
RH_TOKEN_URL = "https://api.robinhood.com/oauth2/token/"

def get_rh_token():
    """Get Robinhood OAuth token."""
    import requests

    if not RH_CLIENT_ID or not RH_REFRESH_TOKEN:
        log.error("Missing OAuth credentials")
        return None

    try:
        r = requests.post(RH_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": RH_REFRESH_TOKEN,
            "client_id": RH_CLIENT_ID,
        }, timeout=10)

        if r.status_code == 200:
            token = r.json().get("access_token")
            log.info("✅ Got Robinhood token: %s...", token[:20] if token else "NONE")
            return token
        else:
            log.error("❌ Token refresh failed: %s - %s", r.status_code, r.text[:200])
            return None
    except Exception as e:
        log.error("❌ Error getting token: %s", e)
        return None

def test_mcp():
    """Test MCP with a simple order."""

    # Get token
    rh_token = get_rh_token()
    if not rh_token:
        log.error("Cannot proceed without token")
        return

    # Get Claude client
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("ANTHROPIC_API_KEY not set")
        return

    client = anthropic.Anthropic(api_key=api_key)

    # Simple test: Ask Claude to place a test order via MCP
    log.info("\n=== MCP TEST ===")
    log.info("Requesting Claude to place TEST order via MCP...")

    try:
        resp = client.beta.messages.create(
            model="claude-opus-4-8",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": f"""Place a test BUY order via MCP:

Account: {RH_ACCOUNT}
Symbol: AAPL
Side: BUY
Type: market
Quantity: 0.01 shares

Use place_equity_order tool to test if MCP is connected to Robinhood."""
            }],
            betas=["mcp-client-2025-04-04"],
            mcp_servers=[{
                "type": "url",
                "url": "https://agent.robinhood.com/mcp/trading",
                "name": "robinhood",
                "authorization_token": rh_token,
            }],
            tools=[{
                "name": "place_equity_order",
                "description": "Place equity order with Robinhood",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "account_number": {"type": "string"},
                        "symbol": {"type": "string"},
                        "side": {"type": "string", "enum": ["buy", "sell"]},
                        "type": {"type": "string", "enum": ["market", "limit"]},
                        "quantity": {"type": "string"},
                        "limit_price": {"type": "string"}
                    },
                    "required": ["account_number", "symbol", "side", "type", "quantity"]
                }
            }],
            tool_choice={"type": "tool", "name": "place_equity_order"}
        )

        log.info("\n✅ MCP Response received!")
        log.info("Stop reason: %s", resp.stop_reason)
        log.info("Content blocks: %d", len(resp.content) if resp.content else 0)

        for i, block in enumerate(resp.content):
            log.info("\nBlock %d: %s", i, block.type)

            if block.type == "tool_use":
                log.info("  Tool: %s", block.name)
                log.info("  Input: %s", json.dumps(block.input, indent=2))
                log.info("  ID: %s", block.id)

            elif block.type == "text":
                log.info("  Text: %s", block.text[:200] if block.text else "")

        # Check if order was placed
        if resp.stop_reason == "tool_use":
            log.info("\n✅ SUCCESS: Claude called place_equity_order via MCP!")
            log.info("If order appears in Robinhood in 30 seconds, MCP is working.")
        else:
            log.warning("\n⚠️  Unexpected response: %s", resp.stop_reason)

    except Exception as e:
        log.error("\n❌ MCP Error: %s", e)
        log.error("Error type: %s", type(e).__name__)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_mcp()
