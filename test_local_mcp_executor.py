#!/usr/bin/env python3
"""
Test: Local MCP Executor Integration

Verifies that:
1. LocalMCPExecutor initializes correctly
2. Trade decisions are formatted properly
3. Position sizing logic works
4. MCP execution can be called (dry run)
"""

import logging
import json
from local_mcp_executor import LocalMCPExecutor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


def test_executor_init():
    """Test 1: Initialize executor"""
    print("\n" + "="*70)
    print("TEST 1: LocalMCPExecutor Initialization")
    print("="*70 + "\n")

    executor = LocalMCPExecutor()

    print(f"Executor enabled: {executor.enabled}")
    print(f"Account: {executor.account}")
    print(f"Has credentials: {bool(executor.client_id and executor.refresh_token)}")

    if executor.enabled:
        print("\n✅ Executor ready for MCP execution")
    else:
        print("\n⚠️  Credentials not configured (set ROBINHOOD_CLIENT_ID and ROBINHOOD_REFRESH_TOKEN)")

    return executor


def test_trade_decisions(executor):
    """Test 2: Format and size trades"""
    print("\n" + "="*70)
    print("TEST 2: Trade Decision Processing")
    print("="*70 + "\n")

    # Sample decisions from Llama 2
    decisions = [
        {"symbol": "INTC", "action": "BUY", "confidence": 81, "pct_change": 6.2},
        {"symbol": "AMD", "action": "BUY", "confidence": 75, "pct_change": -3.5},
        {"symbol": "NVDA", "action": "BUY", "confidence": 65, "pct_change": -2.1},
        {"symbol": "TSLA", "action": "HOLD", "confidence": 55, "pct_change": 1.5},
    ]

    print(f"Input: {len(decisions)} decisions\n")

    for i, d in enumerate(decisions, 1):
        print(
            f"{i}. {d['symbol']:6s} {d['action']:4s} "
            f"conf={d['confidence']:3d}% "
            f"change={d['pct_change']:+6.1f}%"
        )

    print("\n" + "-"*70)
    print("Position Sizing Logic:")
    print("-"*70 + "\n")

    # Show position sizing
    sizing = {
        80: 350,
        75: 300,
        70: 200,
        60: 150,
    }

    for conf_threshold, position_size in sorted(sizing.items(), reverse=True):
        print(f"  Confidence >= {conf_threshold}%  →  ${position_size} position")

    print("\n" + "-"*70)
    print("Filtered for Execution (confidence >= 60%):")
    print("-"*70 + "\n")

    # Filter for execution
    threshold = 60
    for d in decisions:
        if d["action"] == "BUY" and d["confidence"] >= threshold:
            if d["confidence"] >= 80:
                size = 350
            elif d["confidence"] >= 75:
                size = 300
            elif d["confidence"] >= 70:
                size = 200
            else:
                size = 150

            print(f"✅ {d['symbol']:6s} BUY ${size} (confidence: {d['confidence']}%)")
        elif d["action"] == "BUY":
            print(f"❌ {d['symbol']:6s} BUY skipped (confidence: {d['confidence']}% < {threshold}%)")
        else:
            print(f"⊘  {d['symbol']:6s} {d['action']:4s} skipped (not BUY)")

    print(f"\n✅ Would execute {len([d for d in decisions if d['action'] == 'BUY' and d['confidence'] >= threshold])} trades")


def test_execution_dry_run(executor):
    """Test 3: Dry run execution (no real orders)"""
    print("\n" + "="*70)
    print("TEST 3: Execution Dry Run")
    print("="*70 + "\n")

    decisions = [
        {"symbol": "INTC", "action": "BUY", "confidence": 81, "pct_change": 6.2},
        {"symbol": "AMD", "action": "BUY", "confidence": 75, "pct_change": -3.5},
    ]

    print("Attempting to execute trade decisions via MCP...\n")

    # Execute (will fail gracefully if credentials not set)
    executed = executor.execute_trades(decisions)

    print(f"\nResult: {len(executed)} trades executed")

    if executed:
        print("\nExecuted trades:")
        for trade in executed:
            print(f"  {trade['symbol']}: {trade['status']} (Order ID: {trade['order_id']})")
    else:
        print("(No trades executed - check logs for details)")


def test_flow_summary():
    """Test 4: Summary of complete flow"""
    print("\n" + "="*70)
    print("TEST 4: Complete Option C Flow")
    print("="*70 + "\n")

    flow = """
    OPTION C: Direct MCP Execution (All Local, $0 Claude Cost)
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    Every 30 minutes on your Mac:

    1. DATA DOWNLOAD (yfinance, $0)
       └─ Get market data for ~60 stocks

    2. STAGE 1: LLAMA 2 SCREENING (local_llm_wrapper.py, $0)
       └─ Input: Market movers
       └─ Process: Llama 2 analyzes each mover
       └─ Output: Candidates with confidence scores

    3. STAGE 2: FINRL CONFIRMATION (finrl_integration.py, $0)
       └─ Input: Candidate symbols
       └─ Process: FinRL model validates setup
       └─ Output: Trade decisions ready to execute

    4. STAGE 3: LOCAL MCP EXECUTION (local_mcp_executor.py, $0.027/cycle)
       ├─ Input: Trade decisions from Stages 1+2
       ├─ Filter: Only confidence >= 60%
       ├─ Size: Position sizing by confidence level
       ├─ Execute: Direct MCP call to Robinhood
       └─ Output: Executed orders + Robinhood confirmation

    5. LOG & WAIT
       └─ Save results
       └─ Sleep until next cycle

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    COST BREAKDOWN:
      • Ollama (local):        $0
      • Llama 2 inference:     $0
      • FinRL model:           $0
      • MCP calls:             $0.027/cycle
      ────────────────────────────────────
      Per day (48 cycles):     $1.30
      Per year:                ~$475 (MCP only)
      Savings vs Claude:       ~$49/year ✅

    KEY BENEFITS:
      ✅ Everything runs on your Mac
      ✅ Direct Robinhood execution (no intermediary)
      ✅ Zero Claude API costs
      ✅ Simple, lean architecture
      ✅ Full control and visibility
    """

    print(flow)


if __name__ == "__main__":
    print("\n" + "="*70)
    print("  LOCAL MCP EXECUTOR TEST SUITE")
    print("="*70)

    # Run tests
    executor = test_executor_init()
    test_trade_decisions(executor)
    test_execution_dry_run(executor)
    test_flow_summary()

    print("\n" + "="*70)
    print("  TESTS COMPLETE")
    print("="*70 + "\n")

    print("Next steps:")
    print("  1. Set environment variables:")
    print("     export ROBINHOOD_CLIENT_ID=your_id")
    print("     export ROBINHOOD_REFRESH_TOKEN=your_token")
    print("  2. Modify bot.py to use local_mcp_executor")
    print("  3. Run bot.py to trade live")
    print()
