#!/usr/bin/env python3
"""
Schwab Real-Time Block Trade Detector
Listens to Time & Sales WebSocket stream and logs institutional block trades
Runs continuously during market hours (9 AM - 3 PM CDT)
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytz

try:
    import schwab
    from schwab.streaming import StreamClient
except ImportError:
    print("ERROR: schwab-py not installed. Run: /opt/homebrew/bin/pip3.10 install schwab-py")
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

CONFIG_FILE = Path("config.json")
BLOCK_TRADES_CSV = Path("block_trades.csv")
CREDENTIALS_FILE = Path("schwab_credentials.json")
TOKEN_CACHE = Path("schwab_token.json")

# Default block trade thresholds
BLOCK_TRADE_CONFIG = {
    "min_shares": 10000,           # Minimum shares for block detection
    "min_notional_value": 200000,  # Minimum dollar value ($200K+)
    "watchlist": [
        "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "NFLX",
        "AMD", "INTC", "MU", "AVGO", "LRCX", "ASML", "CRM", "ADBE",
        "SHOP", "PYPL", "SQ", "CRWD", "NET", "OKTA", "DDOG", "ZM",
        "PLTR", "U", "COIN", "HOOD", "UPST", "RBLX", "DASH", "ABNB"
    ]
}

# ============================================================================
# BLOCK TRADE MONITOR
# ============================================================================

class SchwabBlockTradeMonitor:
    """Real-time block trade detector via Schwab WebSocket stream"""

    def __init__(self):
        self.config = self._load_config()
        self.min_shares = BLOCK_TRADE_CONFIG["min_shares"]
        self.min_value = BLOCK_TRADE_CONFIG["min_notional_value"]
        self.watchlist = BLOCK_TRADE_CONFIG["watchlist"]
        self.rest_client = None
        self.stream_client = None
        self.eastern = pytz.timezone("US/Eastern")
        self.total_blocks_detected = 0

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

            # Account ID from config (numeric)
            account_id = creds.get("account_number")
            if not account_id:
                logger.error("❌ account_number not in schwab_credentials.json")
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
            df.to_csv(
                BLOCK_TRADES_CSV,
                mode="a",
                index=False,
                header=header_needed
            )
        except Exception as e:
            logger.error(f"❌ Failed to write to CSV: {e}")

    def _handle_timesale_message(self, message: dict):
        """Process Time & Sales tick data from Schwab stream"""
        try:
            content = message.get("content", [])
            if not content:
                return

            for tick in content:
                symbol = tick.get("key")
                if not symbol or symbol not in self.watchlist:
                    continue

                # Schwab Time & Sales field mapping:
                # "1": timestamp (ms), "2": price, "3": size, "4": sequence
                try:
                    price = float(tick.get("2", 0))
                    size = int(tick.get("3", 0))
                    timestamp_ms = tick.get("1")
                except (ValueError, TypeError):
                    continue

                if price <= 0 or size <= 0:
                    continue

                notional_value = price * size

                # Check block trade criteria
                is_large_size = size >= self.min_shares
                is_large_value = notional_value >= self.min_value

                if is_large_size or is_large_value:
                    self.total_blocks_detected += 1

                    # Format timestamp
                    if timestamp_ms:
                        trade_dt = (
                            datetime.fromtimestamp(timestamp_ms / 1000.0, tz=pytz.UTC)
                            .astimezone(self.eastern)
                            .strftime("%Y-%m-%d %H:%M:%S")
                        )
                    else:
                        trade_dt = datetime.now(self.eastern).strftime("%Y-%m-%d %H:%M:%S")

                    # Log and save
                    logger.info(
                        f"🚨 BLOCK TRADE #{self.total_blocks_detected:,} | "
                        f"{trade_dt} | {symbol:<6} | "
                        f"{size:>9,} shares @ ${price:>8.2f} | "
                        f"${notional_value:>12,.0f}"
                    )

                    record = {
                        "timestamp": trade_dt,
                        "symbol": symbol,
                        "price": price,
                        "size": size,
                        "notional_value": round(notional_value, 2)
                    }
                    self._write_to_csv(record)

        except Exception as e:
            logger.debug(f"Error processing tick: {e}")

    async def run(self):
        """Main streaming loop"""
        # Check if market is open before attempting to connect
        now = datetime.now(self.eastern)
        if now.weekday() >= 5:  # Weekend
            logger.info("📅 Market closed (weekend). Exiting.")
            return

        if now.hour < 9 or (now.hour >= 16 and now.minute >= 5):
            logger.info(f"🕐 Outside market hours (9 AM - 4 PM EST). Current: {now.strftime('%I:%M %p')}")
            logger.info("ℹ️  StreamClient only works during market hours. Waiting...")
            return

        self._init_clients()

        logger.info("📡 Logging into Schwab Stream...")
        try:
            await self.stream_client.login()
            logger.info("✅ Stream authenticated")
        except Exception as e:
            logger.error(f"❌ Stream login failed: {e}")
            logger.info("ℹ️  Note: Streaming may only be available during market hours (9 AM - 4 PM EST)")
            return

        # Register handler BEFORE subscribing
        self.stream_client.add_timesale_equity_handler(self._handle_timesale_message)

        logger.info(f"📊 Subscribing to {len(self.watchlist)} symbols: {', '.join(self.watchlist[:5])}...")
        try:
            await self.stream_client.timesale_equity_subs(self.watchlist)
            logger.info("✅ Subscriptions active")
        except Exception as e:
            logger.error(f"❌ Subscription failed: {e}")
            return

        logger.info("=" * 80)
        logger.info("🟢 BLOCK TRADE STREAM ACTIVE")
        logger.info(f"   Monitoring: {len(self.watchlist)} symbols")
        logger.info(f"   Min Size: {self.min_shares:,} shares")
        logger.info(f"   Min Value: ${self.min_value:,}")
        logger.info("=" * 80)

        # Stream event loop
        while True:
            # Check if market is still open (before 4:05 PM EST/EDT)
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
                await asyncio.sleep(5)  # Retry after 5 seconds

# ============================================================================
# MAIN ENTRYPOINT
# ============================================================================

def main():
    logger.info("\n" + "=" * 80)
    logger.info("SCHWAB REAL-TIME BLOCK TRADE DETECTOR")
    logger.info("=" * 80)

    monitor = SchwabBlockTradeMonitor()

    try:
        asyncio.run(monitor.run())
    except KeyboardInterrupt:
        logger.info("\n⏹️ Stream stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)

    logger.info(f"📊 Total block trades detected: {monitor.total_blocks_detected:,}")
    logger.info(f"📁 Saved to: {BLOCK_TRADES_CSV.absolute()}")

if __name__ == "__main__":
    main()
