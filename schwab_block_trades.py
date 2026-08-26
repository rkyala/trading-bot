#!/usr/bin/env python3
"""
Schwab Block Trade Detector - Level 1 Quote Based (Fixed Field Mapping)
Uses bid/ask size changes to infer institutional block liquidity.
Critical fixes: Correct Schwab Level 1 field mapping, ZeroDivisionError protection
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

import pandas as pd
import pytz

try:
    import schwab
    from schwab.streaming import StreamClient
except ImportError:
    print("ERROR: schwab-py not installed. Run: pip install schwab-py")
    sys.exit(1)

# ============================================================================
# CONFIGURATION
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('block_trade_stream.log')
    ]
)
logger = logging.getLogger(__name__)

BLOCK_TRADES_CSV = Path("block_trades.csv")
CREDENTIALS_FILE = Path("schwab_credentials.json")
TOKEN_CACHE = Path("schwab_token.json")

BLOCK_TRADE_CONFIG = {
    "min_shares": 10000,
    "min_notional_value": 200000,
    "size_surge_threshold": 5.0,
    "watchlist": [
        "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "NFLX",
        "AMD", "INTC", "MU", "AVGO", "LRCX", "ASML", "CRM", "ADBE",
        "SHOP", "PYPL", "SQ", "CRWD", "NET", "OKTA", "DDOG", "ZM",
        "PLTR", "U", "COIN", "HOOD", "UPST", "RBLX", "DASH", "ABNB"
    ]
}

# ============================================================================
# BLOCK TRADE MONITOR (FIXED FIELD MAPPING)
# ============================================================================

class SchwabBlockTradeMonitor:
    """Block trade detector using Level 1 quote bid/ask size changes"""

    def __init__(self):
        self.config = self._load_config()
        self.min_shares = BLOCK_TRADE_CONFIG["min_shares"]
        self.min_value = BLOCK_TRADE_CONFIG["min_notional_value"]
        self.size_surge_threshold = BLOCK_TRADE_CONFIG["size_surge_threshold"]
        self.watchlist = BLOCK_TRADE_CONFIG["watchlist"]
        self.rest_client = None
        self.stream_client = None
        self.eastern = pytz.timezone("US/Eastern")
        self.total_blocks_detected = 0

        # Track previous bid/ask sizes to detect changes
        self.quote_history = defaultdict(lambda: {"bid_size": 0, "ask_size": 0, "last_price": 0.0})

    def _load_config(self) -> dict:
        """Load Schwab credentials"""
        if not CREDENTIALS_FILE.exists():
            logger.error("❌ schwab_credentials.json not found")
            sys.exit(1)
        return json.loads(CREDENTIALS_FILE.read_text())

    def _init_clients(self):
        """Initialize Schwab REST and Stream clients"""
        try:
            creds = self.config
            logger.info("🔐 Authenticating with Schwab...")

            self.rest_client = schwab.auth.client_from_token_file(
                token_path=str(TOKEN_CACHE),
                api_key=creds["client_id"],
                app_secret=creds["client_secret"]
            )

            logger.info("✅ REST client authenticated")

            account_id = creds.get("account_number")
            if not account_id:
                logger.error("❌ account_number missing from schwab_credentials.json")
                sys.exit(1)

            self.stream_client = StreamClient(self.rest_client, account_id=account_id)
            logger.info("✅ Stream client initialized")

        except Exception as e:
            logger.error(f"❌ Authentication failed: {e}")
            sys.exit(1)

    def _write_to_csv(self, trade_data: dict):
        """Append block trade to CSV file"""
        try:
            df = pd.DataFrame([trade_data])
            header_needed = not BLOCK_TRADES_CSV.exists()
            df.to_csv(BLOCK_TRADES_CSV, mode="a", index=False, header=header_needed)
        except Exception as e:
            logger.error(f"❌ Failed to write to CSV: {e}")

    def _handle_quote_message(self, message: dict):
        """
        Process Level 1 quote data with CORRECT field mapping

        Schwab Level 1 Quote Fields:
        "1": Bid Price (float)
        "2": Bid Size (int, in 100s)
        "3": Last Price (float)
        "4": Ask Price (float)
        "5": Ask Size (int, in 100s)
        "7": Last Price (float, fallback)
        """
        try:
            content = message.get("content", [])
            if not content:
                return

            for tick in content:
                symbol = tick.get("key")
                if not symbol or symbol not in self.watchlist:
                    continue

                # Extract fields with correct mapping
                try:
                    # Bid/Ask sizes are in 100s, convert to shares
                    bid_size = int(tick.get("2", 0)) * 100
                    ask_size = int(tick.get("5", 0)) * 100
                    # Last price from field "3" or fallback to "7"
                    last_price = float(tick.get("3", tick.get("7", 0)))
                except (ValueError, TypeError):
                    continue

                if last_price <= 0:
                    continue

                # Get previous sizes (safe from KeyError due to defaultdict)
                prev_data = self.quote_history[symbol]
                prev_bid_size = prev_data["bid_size"]
                prev_ask_size = prev_data["ask_size"]

                # Update current state
                if bid_size > 0:
                    self.quote_history[symbol]["bid_size"] = bid_size
                if ask_size > 0:
                    self.quote_history[symbol]["ask_size"] = ask_size
                self.quote_history[symbol]["last_price"] = last_price

                detected_block = False
                block_type = ""
                detected_size = 0

                # Bid surge evaluation (safe from ZeroDivisionError)
                if prev_bid_size > 0 and bid_size >= self.min_shares:
                    bid_surge = bid_size / prev_bid_size
                    if bid_surge >= self.size_surge_threshold:
                        detected_block = True
                        block_type = "Bid Accumulation"
                        detected_size = bid_size

                # Ask surge evaluation (safe from ZeroDivisionError)
                if prev_ask_size > 0 and ask_size >= self.min_shares:
                    ask_surge = ask_size / prev_ask_size
                    if ask_surge >= self.size_surge_threshold:
                        detected_block = True
                        block_type = "Ask Distribution"
                        detected_size = ask_size

                # If we detected a block, log it
                if detected_block:
                    notional_value = last_price * detected_size

                    # Only log if meets minimum notional value
                    if notional_value >= self.min_value:
                        self.total_blocks_detected += 1
                        trade_dt = datetime.now(self.eastern).strftime("%Y-%m-%d %H:%M:%S")

                        logger.info(
                            f"🚨 BLOCK DETECTED #{self.total_blocks_detected:,} | "
                            f"{trade_dt} | {symbol:<6} | "
                            f"{detected_size:>9,} shares @ ${last_price:>8.2f} | "
                            f"${notional_value:>12,.0f} | {block_type}"
                        )

                        record = {
                            "timestamp": trade_dt,
                            "symbol": symbol,
                            "price": last_price,
                            "size": detected_size,
                            "notional_value": round(notional_value, 2),
                            "type": block_type
                        }
                        self._write_to_csv(record)

        except Exception as e:
            logger.debug(f"Error processing quote tick: {e}")

    async def run(self):
        """Main streaming loop (ASYNC)"""
        # Check if market is open
        now = datetime.now(self.eastern)
        if now.weekday() >= 5:  # Weekend
            logger.info("📅 Market closed (weekend). Exiting.")
            return

        if now.hour < 9 or (now.hour >= 16 and now.minute >= 5):
            logger.info(f"🕐 Outside market hours (9 AM - 4 PM EST). Current: {now.strftime('%I:%M %p')}")
            return

        self._init_clients()

        logger.info("📡 Logging into Schwab Stream...")
        try:
            await self.stream_client.login()
            logger.info("✅ Stream authenticated")
        except Exception as e:
            logger.error(f"❌ Stream login failed: {e}")
            return

        # CRITICAL: Register handler BEFORE subscribing
        self.stream_client.add_level_one_equity_handler(self._handle_quote_message)

        logger.info(f"📊 Subscribing to Level 1 quotes for {len(self.watchlist)} symbols...")
        try:
            await self.stream_client.level_one_equity_subs(self.watchlist)
            logger.info("✅ Subscriptions active")
        except Exception as e:
            logger.error(f"❌ Subscription failed: {e}")
            return

        logger.info("=" * 80)
        logger.info("🟢 BLOCK TRADE DETECTOR ACTIVE (Level 1 Mode - Fixed)")
        logger.info(f"   Monitoring: {len(self.watchlist)} symbols")
        logger.info(f"   Min Size: {self.min_shares:,} shares")
        logger.info(f"   Min Value: ${self.min_value:,}")
        logger.info(f"   Size Surge Threshold: {self.size_surge_threshold}x")
        logger.info(f"   Method: Bid/Ask Size Change Detection (Correct Field Mapping)")
        logger.info("=" * 80)

        # Stream event loop
        while True:
            # Check if market is still open
            now = datetime.now(self.eastern)
            if now.weekday() >= 5:  # Weekend
                logger.info("📅 Market closed (weekend). Stopping stream.")
                break

            if now.hour >= 16 and now.minute >= 5:  # After 4:05 PM
                logger.info("🌙 Market closed (4:05 PM EST). Stopping stream.")
                break

            try:
                await self.stream_client.handle_message()
            except asyncio.CancelledError:
                logger.info("⏸️ Stream cancelled by user")
                break
            except Exception as e:
                logger.error(f"Stream error: {e}")
                await asyncio.sleep(5)

# ============================================================================
# MAIN ENTRYPOINT
# ============================================================================

def main():
    logger.info("\n" + "=" * 80)
    logger.info("SCHWAB BLOCK TRADE DETECTOR - LEVEL 1 QUOTE MODE (FIXED)")
    logger.info("=" * 80)

    monitor = SchwabBlockTradeMonitor()

    try:
        asyncio.run(monitor.run())
    except KeyboardInterrupt:
        logger.info("\n⏹️ Stream stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)

    logger.info(f"📊 Total blocks detected: {monitor.total_blocks_detected:,}")
    logger.info(f"📁 Saved to: {BLOCK_TRADES_CSV.absolute()}")

if __name__ == "__main__":
    main()
