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
    "watchlist": [
        "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "NFLX",
        "AMD", "INTC", "MU", "AVGO", "LRCX", "ASML", "CRM", "ADBE",
        "SHOP", "PYPL", "SQ", "CRWD", "NET", "OKTA", "DDOG", "ZM",
        "PLTR", "U", "COIN", "HOOD", "UPST", "RBLX", "DASH", "ABNB"
    ],
    # Tiered detection parameters: OR logic (match EITHER shares OR notional)
    "tier_params": {
        "mega_cap": {  # AAPL, MSFT, NVDA, TSLA, AMZN, GOOGL, META, NFLX
            "symbols": ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "NFLX"],
            "min_shares": 2500,          # Lower for high-priced stocks
            "min_notional": 250000,
            "surge_threshold": 2.5
        },
        "high_beta": {  # PLTR, HOOD, COIN, UPST, RBLX, CRWD, NET, OKTA
            "symbols": ["PLTR", "HOOD", "COIN", "UPST", "RBLX", "CRWD", "NET", "OKTA"],
            "min_shares": 5000,
            "min_notional": 100000,
            "surge_threshold": 3.0
        },
        "mid_cap": {  # INTC, AMD, MU, AVGO, LRCX, ASML, CRM, ADBE, SHOP, PYPL, SQ, DDOG, ZM, U, DASH, ABNB
            "symbols": ["INTC", "AMD", "MU", "AVGO", "LRCX", "ASML", "CRM", "ADBE", "SHOP", "PYPL", "SQ", "DDOG", "ZM", "U", "DASH", "ABNB"],
            "min_shares": 7500,
            "min_notional": 75000,
            "surge_threshold": 3.5
        }
    }
}

# ============================================================================
# BLOCK TRADE MONITOR (FIXED FIELD MAPPING)
# ============================================================================

class SchwabBlockTradeMonitor:
    """Block trade detector using Level 1 quote bid/ask size changes"""

    def __init__(self):
        self.config = self._load_config()
        self.watchlist = BLOCK_TRADE_CONFIG["watchlist"]
        self.rest_client = None
        self.stream_client = None
        self.eastern = pytz.timezone("US/Eastern")
        self.total_blocks_detected = 0

        # Build symbol-to-tier mapping for quick lookups
        self.symbol_tier = {}
        for tier_name, tier_config in BLOCK_TRADE_CONFIG["tier_params"].items():
            for symbol in tier_config["symbols"]:
                self.symbol_tier[symbol] = tier_name

        # Track previous bid/ask sizes to detect changes
        self.quote_history = defaultdict(lambda: {"bid_size": 0, "ask_size": 0, "last_price": 0.0})

    def _get_tier_params(self, symbol: str):
        """Get detection parameters for a specific symbol (tier-based)"""
        tier_name = self.symbol_tier.get(symbol, "mid_cap")  # Default to mid_cap
        return BLOCK_TRADE_CONFIG["tier_params"][tier_name]

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
        Process Level 1 quote data with TIERED OR-BASED detection

        Schwab Level 1 Quote Fields:
        "1": Bid Price (float)
        "2": Bid Size (int, in 100s)
        "3": Last Price (float)
        "4": Ask Price (float)
        "5": Ask Size (int, in 100s)
        "7": Last Price (float, fallback)

        Detection Logic: OR-based (match EITHER shares OR notional)
        - Bid Accumulation: size surge + (min_shares OR min_notional)
        - Ask Distribution: size surge + (min_shares OR min_notional)
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

                # Get tier-specific parameters
                tier_params = self._get_tier_params(symbol)
                min_shares = tier_params["min_shares"]
                min_notional = tier_params["min_notional"]
                surge_threshold = tier_params["surge_threshold"]

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

                # Bid surge evaluation: surge + (shares OR notional) ✅ OR LOGIC
                if prev_bid_size > 0:
                    bid_surge = bid_size / prev_bid_size
                    bid_notional = bid_size * last_price
                    is_surge = bid_surge >= surge_threshold
                    is_large_shares = bid_size >= min_shares
                    is_large_notional = bid_notional >= min_notional

                    if is_surge and (is_large_shares or is_large_notional):
                        detected_block = True
                        block_type = "Bid Accumulation"
                        detected_size = bid_size

                # Ask surge evaluation: surge + (shares OR notional) ✅ OR LOGIC
                if prev_ask_size > 0 and not detected_block:  # Avoid double-reporting same tick
                    ask_surge = ask_size / prev_ask_size
                    ask_notional = ask_size * last_price
                    is_surge = ask_surge >= surge_threshold
                    is_large_shares = ask_size >= min_shares
                    is_large_notional = ask_notional >= min_notional

                    if is_surge and (is_large_shares or is_large_notional):
                        detected_block = True
                        block_type = "Ask Distribution"
                        detected_size = ask_size

                # If we detected a block, log it with tier information
                if detected_block:
                    notional_value = last_price * detected_size
                    self.total_blocks_detected += 1
                    trade_dt = datetime.now(self.eastern).strftime("%Y-%m-%d %H:%M:%S")
                    tier_name = self.symbol_tier.get(symbol, "unknown")

                    logger.info(
                        f"🚨 BLOCK DETECTED #{self.total_blocks_detected:,} | "
                        f"{trade_dt} | {symbol:<6} [{tier_name}] | "
                        f"{detected_size:>9,} shares @ ${last_price:>8.2f} | "
                        f"${notional_value:>12,.0f} | {block_type}"
                    )

                    record = {
                        "timestamp": trade_dt,
                        "symbol": symbol,
                        "price": last_price,
                        "size": detected_size,
                        "notional_value": round(notional_value, 2),
                        "type": block_type,
                        "tier": tier_name
                    }
                    self._write_to_csv(record)

        except Exception as e:
            logger.debug(f"Error processing quote tick: {e}")

    async def run(self):
        """Main streaming loop with WebSocket resilience (FIXED)"""
        # Check if market is open
        now = datetime.now(self.eastern)
        if now.weekday() >= 5:  # Weekend
            logger.info("📅 Market closed (weekend). Exiting.")
            return

        if now.hour < 9 or (now.hour >= 16 and now.minute >= 5):
            logger.info(f"🕐 Outside market hours (9 AM - 4 PM EST). Current: {now.strftime('%I:%M %p')}")
            return

        reconnect_attempts = 0
        max_reconnect_attempts = 3
        backoff_seconds = 2

        while reconnect_attempts < max_reconnect_attempts:
            try:
                self._init_clients()

                logger.info("📡 Logging into Schwab Stream...")
                await self.stream_client.login()
                logger.info("✅ Stream authenticated")
                reconnect_attempts = 0  # Reset on successful connection

                # CRITICAL: Register handler BEFORE subscribing
                self.stream_client.add_level_one_equity_handler(self._handle_quote_message)

                logger.info(f"📊 Subscribing to Level 1 quotes for {len(self.watchlist)} symbols...")
                await self.stream_client.level_one_equity_subs(self.watchlist)
                logger.info("✅ Subscriptions active")

                logger.info("=" * 80)
                logger.info("🟢 BLOCK TRADE DETECTOR ACTIVE (Level 1 Mode - Tiered OR Detection)")
                logger.info(f"   Monitoring: {len(self.watchlist)} symbols across 3 liquidity tiers")
                logger.info("   Detection Logic: Surge + (Min Shares OR Min Notional) per tier")
                logger.info("")
                for tier_name, tier_config in BLOCK_TRADE_CONFIG["tier_params"].items():
                    symbols = ", ".join(tier_config["symbols"][:3]) + ("..." if len(tier_config["symbols"]) > 3 else "")
                    logger.info(f"   📊 {tier_name.upper():12s}: Min {tier_config['min_shares']:>5,} sh | ${tier_config['min_notional']:>7,} | {tier_config['surge_threshold']}x surge | ({symbols})")
                logger.info("=" * 80)

                # Stream event loop - with WebSocket keep-alive
                message_count = 0
                last_heartbeat = datetime.now()

                while True:
                    # Check if market is still open
                    now = datetime.now(self.eastern)
                    if now.weekday() >= 5:  # Weekend
                        logger.info("📅 Market closed (weekend). Stopping stream.")
                        return

                    if now.hour >= 16 and now.minute >= 5:  # After 4:05 PM
                        logger.info("🌙 Market closed (4:05 PM EST). Stopping stream.")
                        return

                    try:
                        # Handle message with timeout to detect dead connections
                        await asyncio.wait_for(self.stream_client.handle_message(), timeout=30.0)
                        message_count += 1

                        # Heartbeat every 30 seconds to keep connection alive
                        if (datetime.now() - last_heartbeat).total_seconds() > 30:
                            logger.debug(f"💓 [Heartbeat] Received {message_count} messages in last 30s")
                            message_count = 0
                            last_heartbeat = datetime.now()

                    except asyncio.TimeoutError:
                        # Connection likely dead - no message in 30 seconds
                        logger.warning("⚠️  Stream timeout (30s no message) - reconnecting...")
                        reconnect_attempts += 1
                        break  # Break inner loop, try to reconnect

                    except asyncio.CancelledError:
                        logger.info("⏸️ Stream cancelled by user")
                        return

                    except Exception as e:
                        error_str = str(e)
                        # Classify error: recoverable vs fatal
                        if "1000" in error_str or "close frame" in error_str.lower():
                            # Normal WebSocket close - recoverable
                            logger.debug(f"📊 WebSocket keep-alive event: {e}")
                            reconnect_attempts += 1
                            break  # Reconnect
                        else:
                            # Unexpected error
                            logger.error(f"❌ Stream error: {e}")
                            reconnect_attempts += 1
                            break  # Try to reconnect

            except Exception as e:
                logger.error(f"❌ Connection initialization failed: {e}")
                reconnect_attempts += 1

            # Exponential backoff before reconnect
            if reconnect_attempts < max_reconnect_attempts:
                wait_time = backoff_seconds * (2 ** (reconnect_attempts - 1))
                logger.warning(f"⏳ Reconnecting in {wait_time}s (attempt {reconnect_attempts}/{max_reconnect_attempts})")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"❌ Max reconnection attempts ({max_reconnect_attempts}) exceeded. Stopping detector.")
                break

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
