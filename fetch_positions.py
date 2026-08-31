#!/usr/bin/env python3
"""
Fetch Current Positions from Robinhood
"""

import json
import logging
from bot_production_final import LocalMCPClient, ConfigLoader

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger(__name__)

print('='*80)
print('ROBINHOOD POSITION FETCHER')
print('='*80)

# Load config
config = ConfigLoader.load()
account_number = config.get('account', {}).get('agentic_account_number')
logger.info(f"Account: {account_number}")

# Initialize MCP
logger.info("\nInitializing MCP connection...")
try:
    mcp = LocalMCPClient(config)
    logger.info("✅ MCP connected")
except Exception as e:
    logger.error(f"❌ MCP init failed: {e}")
    exit(1)

# Fetch positions
logger.info("\nFetching positions from Robinhood...")
try:
    response = mcp.get_positions()

    if "error" in response:
        logger.error(f"❌ Error: {response.get('error')}")
        mcp.stop()
        exit(1)

    logger.info("✅ Position fetch successful")

    # Parse response
    positions = []
    try:
        if "result" in response and "content" in response["result"]:
            content_text = response["result"]["content"][0].get("text", "")
            if content_text:
                parsed = json.loads(content_text)

                # Extract positions from data.positions structure
                if isinstance(parsed.get("data"), dict):
                    positions = parsed["data"].get("positions", [])
    except Exception as e:
        logger.warning(f"Could not parse positions: {e}")

    # Display results
    print("\n" + "="*80)
    print("CURRENT POSITIONS")
    print("="*80)

    if not positions:
        print("No positions held")
    else:
        print(f"\nTotal positions: {len(positions)}\n")

        total_value = 0
        for pos in positions:
            symbol = pos.get("symbol", "N/A")
            qty = float(pos.get("quantity", 0))
            avg_price = float(pos.get("average_buy_price", 0))
            available = float(pos.get("shares_available_for_sells", 0))
            pos_type = pos.get("type", "long")

            value = qty * avg_price if qty and avg_price else 0
            total_value += value

            print(f"Symbol: {symbol:6} | Type: {pos_type}")
            print(f"  Quantity: {qty:.4f} shares (Available: {available:.4f})")
            print(f"  Avg Entry Price: ${avg_price:.2f}")
            print(f"  Position Value: ${value:.2f}")
            print()

        print("="*80)
        print(f"TOTAL POSITIONS: {len(positions)} symbols")
        print(f"TOTAL VALUE: ${total_value:.2f}")
        print("="*80)

        # Summary for dedup checking
        print("\n✅ DEDUP PROTECTION - Owned Symbols:")
        owned = [pos.get("symbol") for pos in positions]
        print(f"   {', '.join(owned)}")
        print(f"\n   Bot will skip entry for these {len(owned)} symbols")

except Exception as e:
    logger.error(f"❌ Failed to fetch positions: {e}")
    import traceback
    logger.error(f"Traceback: {traceback.format_exc()}")
finally:
    try:
        mcp.stop()
        logger.info("\n✅ MCP connection closed")
    except:
        pass
