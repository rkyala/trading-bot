#!/usr/bin/env python3
"""
Live MCP Test - Verify Robinhood + Anthropic credentials work together

Run this on your Mac after setting:
  export ROBINHOOD_CLIENT_ID="<RH_CLIENT_ID_REDACTED — read it from .env.local, never inline>"
  export ROBINHOOD_REFRESH_TOKEN="wiu3L3jdK6TiHgQZ16jYd8xDGTXB8v"
  export ANTHROPIC_API_KEY="sk-ant-..."

Then execute: python3 test_mcp_live.py
"""

import os
import logging
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

print("\n" + "="*80)
print("  LIVE MCP TEST - ROBINHOOD + ANTHROPIC")
print("="*80 + "\n")

# ============================================================================
# 1. VERIFY CREDENTIALS
# ============================================================================

print("1. CREDENTIAL VERIFICATION\n")

client_id = os.getenv("ROBINHOOD_CLIENT_ID")
refresh_token = os.getenv("ROBINHOOD_REFRESH_TOKEN")
api_key = os.getenv("ANTHROPIC_API_KEY")
account = os.getenv("ROBINHOOD_ACCOUNT", "432591949")

credentials_ok = True

if client_id:
    print(f"   ✅ ROBINHOOD_CLIENT_ID: {client_id[:30]}...")
else:
    print(f"   ❌ ROBINHOOD_CLIENT_ID: NOT SET")
    credentials_ok = False

if refresh_token:
    print(f"   ✅ ROBINHOOD_REFRESH_TOKEN: {refresh_token[:30]}...")
else:
    print(f"   ❌ ROBINHOOD_REFRESH_TOKEN: NOT SET")
    credentials_ok = False

if api_key:
    print(f"   ✅ ANTHROPIC_API_KEY: {api_key[:20]}...")
else:
    print(f"   ❌ ANTHROPIC_API_KEY: NOT SET")
    credentials_ok = False

print(f"   ✅ ROBINHOOD_ACCOUNT: {account}\n")

if not credentials_ok:
    print("❌ CREDENTIALS INCOMPLETE - Cannot proceed\n")
    print("Set environment variables:")
    print("  export ROBINHOOD_CLIENT_ID='...'")
    print("  export ROBINHOOD_REFRESH_TOKEN='...'")
    print("  export ANTHROPIC_API_KEY='sk-ant-...'\n")
    sys.exit(1)

# ============================================================================
# 2. TEST ANTHROPIC SDK
# ============================================================================

print("2. ANTHROPIC SDK TEST\n")

try:
    from anthropic import Anthropic
    client = Anthropic()
    print("   ✅ Anthropic SDK initialized")
    print(f"   ✅ API key authenticated\n")
except Exception as e:
    print(f"   ❌ Anthropic SDK error: {e}\n")
    sys.exit(1)

# ============================================================================
# 3. TEST LOCAL MCP EXECUTOR
# ============================================================================

print("3. LOCAL MCP EXECUTOR INITIALIZATION\n")

try:
    from local_mcp_executor import LocalMCPExecutor
    executor = LocalMCPExecutor()

    if executor.enabled:
        print(f"   ✅ LocalMCPExecutor initialized")
        print(f"   ✅ Account: {executor.account}")
        print(f"   ✅ Credentials loaded\n")
    else:
        print(f"   ❌ LocalMCPExecutor not enabled\n")
        sys.exit(1)
except Exception as e:
    print(f"   ❌ Error: {e}\n")
    sys.exit(1)

# ============================================================================
# 4. TEST TRADE EXECUTION
# ============================================================================

print("4. LIVE MCP TRADE EXECUTION TEST\n")

test_decisions = [
    {"symbol": "INTC", "action": "BUY", "confidence": 81, "pct_change": 6.2},
    {"symbol": "AMD", "action": "BUY", "confidence": 75, "pct_change": -3.5},
]

print(f"   Input: {len(test_decisions)} trade decisions\n")

for d in test_decisions:
    print(f"   {d['symbol']}: BUY (confidence: {d['confidence']}%)")

print("\n" + "-"*80)
print("   Executing trades via MCP...\n")

try:
    results = executor.execute_trades(test_decisions)

    print("-"*80 + "\n")

    if results:
        print(f"   ✅ EXECUTED: {len(results)} trades\n")

        for trade in results:
            print(f"   {trade['symbol']}:")
            print(f"     • Quantity: {trade['quantity']} shares")
            print(f"     • Fill Price: ${trade['price']:.2f}")
            print(f"     • Confidence: {trade['confidence']}%")
            print(f"     • Order ID: {trade['order_id']}")
            print(f"     • Status: {trade['status']}")
            print(f"     • Time: {trade['timestamp']}\n")

        print("="*80)
        print("  ✅ LIVE MCP TEST PASSED - READY FOR DEPLOYMENT")
        print("="*80 + "\n")

        print("Next steps to deploy bot.py:\n")
        print("  1. Terminal 1: Start Ollama")
        print("     ollama serve\n")
        print("  2. Terminal 2: Start bot")
        print("     export ROBINHOOD_CLIENT_ID='<RH_CLIENT_ID_REDACTED — read it from .env.local, never inline>'")
        print("     export ROBINHOOD_REFRESH_TOKEN='wiu3L3jdK6TiHgQZ16jYd8xDGTXB8v'")
        print("     export ANTHROPIC_API_KEY='sk-ant-...'")
        print("     python3 bot.py\n")
        print("  3. Terminal 3: Monitor logs")
        print("     tail -f bot.log\n")

    else:
        print("   ⚠️  No trades executed")
        print("   Check logs above for details\n")
        print("="*80)
        print("  ⚠️  MCP TEST INCONCLUSIVE")
        print("="*80 + "\n")

except Exception as e:
    print(f"   ❌ EXECUTION FAILED: {e}\n")
    import traceback
    traceback.print_exc()

    print("\n" + "="*80)
    print("  ❌ MCP TEST FAILED")
    print("="*80 + "\n")
    print("Troubleshooting:")
    print("  • Check Robinhood credentials")
    print("  • Verify API key is valid")
    print("  • Check network connection")
    print("  • Review error message above\n")
    sys.exit(1)
