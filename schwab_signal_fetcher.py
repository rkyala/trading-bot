#!/usr/bin/env python3
"""
Schwab Signal Fetcher - Runs every 10 minutes
Fetches live market data, calculates technicals, detects entry signals
Stores all results in schwab_signals.json for bot to consume

This decouples data fetching from trading execution:
- Fetcher runs frequently (every 10 min) to catch all opportunities
- Bot runs every 30 min and uses cached data
- No yfinance needed in bot
- Bot is fast & reliable (just reads cached file)
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('schwab_signal_fetcher.log')
    ]
)
logger = logging.getLogger(__name__)

# Import Schwab fetcher
from schwab_marketdata_fetcher import SchwabMarketDataFetcher

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG_FILE = Path("config.json")
SIGNALS_FILE = Path("schwab_signals.json")

if not CONFIG_FILE.exists():
    logger.error("❌ config.json not found")
    sys.exit(1)

config = json.loads(CONFIG_FILE.read_text())
entry_cfg = config["strategy"]["entry_criteria"]

# ============================================================================
# SCHWAB SIGNAL FETCHER
# ============================================================================

class SchwabSignalFetcher:
    """
    Fetches live data from Schwab, calculates technicals, detects signals
    Stores results in JSON file for bot to use
    """

    def __init__(self):
        self.config = config
        self.entry_cfg = entry_cfg
        self.signals = []
        self.analyzed = 0

    def get_symbols_to_scan(self) -> List[str]:
        """Get list of symbols to scan (dynamic top 50)"""
        # Check if cached symbol list exists
        cached_symbols_file = Path("symbols_cache.json")

        if cached_symbols_file.exists():
            try:
                cached = json.loads(cached_symbols_file.read_text())
                symbols = cached.get("symbols", [])
                if symbols:
                    logger.info(f"📊 Loaded {len(symbols)} cached symbols")
                    return symbols[:50]  # Limit to first 50
            except Exception as e:
                logger.warning(f"⚠️  Could not load cached symbols: {e}")

        # Try dynamic fetcher (might fail if yfinance not available)
        try:
            from symbol_fetcher import DynamicSymbolFetcher

            fetcher = DynamicSymbolFetcher(self.config)
            symbols = fetcher.fetch_and_cache()

            if not symbols:
                logger.warning("⚠️  No symbols from DynamicSymbolFetcher")
                return self._get_default_symbols()

            logger.info(f"📊 Loaded {len(symbols)} dynamic symbols")
            return symbols[:50]  # Limit to first 50

        except Exception as e:
            logger.warning(f"⚠️  DynamicSymbolFetcher failed: {e}")
            return self._get_default_symbols()

    @staticmethod
    def _get_default_symbols() -> List[str]:
        """Fallback: Top stocks if dynamic fetcher unavailable"""
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "NFLX",
            "ADBE", "PYPL", "CRM", "INTC", "AMD", "MU", "AVGO", "LRCX",
            "ASML", "QCOM", "CSCO", "INTU", "IBM", "ORCL", "SAP", "ACHR",
            "KEYS", "U", "SQ", "ROKU", "SHOP", "COIN", "HOOD", "RBLX"
        ]

    def check_signal(self, symbol: str) -> Optional[Dict]:
        """
        Check if symbol meets entry criteria
        Returns signal dict if criteria met, None otherwise
        """
        try:
            # Fetch technicals from Schwab
            technicals = SchwabMarketDataFetcher.get_technicals(symbol, use_cache=False)

            if not technicals:
                logger.debug(f"⏭️  [{symbol}] No technicals from Schwab")
                return None

            # Extract values
            adx = technicals.get("adx", 0)
            stoch_k = technicals.get("stoch_k", 100)
            stoch_d = technicals.get("stoch_d", 100)
            price = technicals.get("price", 0)

            # Check entry criteria
            # 1. ADX must be > 20 (trending)
            if adx < self.entry_cfg["min_adx"]:
                logger.debug(f"   ADX {adx:.1f} < {self.entry_cfg['min_adx']} - no signal")
                return None

            # 2. Stoch K < 30 (oversold) AND K < D (reversal)
            if stoch_k > self.entry_cfg["stoch_oversold"] or stoch_k >= stoch_d:
                logger.debug(f"   Stoch {stoch_k:.1f} >= {self.entry_cfg['stoch_oversold']} or >= D - no signal")
                return None

            # Signal detected!
            logger.info(f"🎯 SIGNAL: {symbol} | Price: ${price:.2f} | ADX: {adx:.1f} | Stoch: {stoch_k:.1f}")

            return {
                "symbol": symbol,
                "price": float(price),
                "adx": float(adx),
                "stoch_k": float(stoch_k),
                "stoch_d": float(stoch_d),
                "high_14": float(technicals.get("high_14", 0)),
                "low_14": float(technicals.get("low_14", 0))
            }

        except Exception as e:
            logger.debug(f"⏭️  [{symbol}] Error checking signal: {e}")
            return None

    def scan_symbols(self, symbols: List[str]):
        """Scan all symbols for entry signals"""
        logger.info("=" * 80)
        logger.info("SCHWAB SIGNAL FETCHER")
        logger.info("=" * 80)
        logger.info(f"Scanning {len(symbols)} symbols for entry signals...")

        self.signals = []
        self.analyzed = 0

        for i, symbol in enumerate(symbols, 1):
            signal = self.check_signal(symbol)

            if signal:
                self.signals.append(signal)
                logger.info(f"[{i}/{len(symbols)}] {symbol} ✅ SIGNAL")

            self.analyzed += 1

        logger.info("=" * 80)

    def save_signals(self):
        """Save signals to JSON file for bot to consume"""
        signal_data = {
            "timestamp": datetime.now().isoformat(),
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_scanned": self.analyzed,
            "signals_found": len(self.signals),
            "signals": self.signals
        }

        try:
            SIGNALS_FILE.write_text(json.dumps(signal_data, indent=2))
            logger.info(f"💾 Saved {len(self.signals)} signals to {SIGNALS_FILE}")
            logger.info(f"   Signals: {', '.join(s['symbol'] for s in self.signals) if self.signals else 'None'}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to save signals: {e}")
            return False


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Fetch signals and save to file"""
    logger.info("\n")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║" + "  SCHWAB SIGNAL FETCHER (Runs every 10 minutes)".center(78) + "║")
    logger.info("║" + "  Stores signals in schwab_signals.json for bot to use".center(78) + "║")
    logger.info("╚" + "=" * 78 + "╝")

    try:
        fetcher = SchwabSignalFetcher()

        # Get symbols to scan
        symbols = fetcher.get_symbols_to_scan()

        if not symbols:
            logger.error("❌ No symbols to scan")
            return 1

        # Scan for signals
        fetcher.scan_symbols(symbols)

        # Save signals
        if fetcher.save_signals():
            logger.info("\n✅ Fetch complete!")
            logger.info(f"   Scanned: {fetcher.analyzed} symbols")
            logger.info(f"   Signals: {len(fetcher.signals)} entry opportunities")
            logger.info(f"   File: {SIGNALS_FILE}")
            return 0
        else:
            logger.error("❌ Failed to save signals")
            return 1

    except KeyboardInterrupt:
        logger.info("\n⏸️  Interrupted by user")
        return 0

    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit(main())
