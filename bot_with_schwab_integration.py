#!/usr/bin/env python3
"""
Bot Integration Test: Using Schwab instead of yfinance
This demonstrates how to integrate Schwab into bot_production_final.py
Can be tested independently before full bot deployment
"""

import json
import logging
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, List

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)

# Import Schwab fetcher (instead of yfinance)
from schwab_marketdata_fetcher import SchwabMarketDataFetcher

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG_FILE = Path("config.json")
if not CONFIG_FILE.exists():
    logger.error("❌ config.json not found")
    sys.exit(1)

config = json.loads(CONFIG_FILE.read_text())

# ============================================================================
# TEST: Simulate Bot Entry Signal Generation with Schwab Data
# ============================================================================

class BotWithSchwabTest:
    """Test bot signal generation using Schwab data instead of yfinance"""

    def __init__(self):
        self.config = config
        self.entry_cfg = config["strategy"]["entry_criteria"]

    def check_entry_signal(self, symbol: str) -> Optional[Dict]:
        """
        Check if symbol meets entry criteria (same logic as bot)
        Uses Schwab technicals instead of yfinance
        """
        # Fetch technicals from Schwab (not yfinance!)
        technicals = SchwabMarketDataFetcher.get_technicals(symbol, use_cache=False)

        if not technicals:
            logger.debug(f"⏭️  [{symbol}] No technicals from Schwab")
            return None

        # Extract values
        adx = technicals.get("adx", 0)
        stoch_k = technicals.get("stoch_k", 100)
        stoch_d = technicals.get("stoch_d", 100)
        price = technicals.get("price", 0)

        # Entry criteria (same as bot)
        # 1. ADX must be > 20 (trending market)
        if adx < self.entry_cfg["min_adx"]:
            logger.debug(f"   ADX {adx:.1f} < {self.entry_cfg['min_adx']} - no signal")
            return None

        # 2. Stoch K must be < 30 (oversold) and below D (momentum reversal)
        if stoch_k > self.entry_cfg["stoch_oversold"] or stoch_k >= stoch_d:
            logger.debug(f"   Stoch {stoch_k:.1f} >= {self.entry_cfg['stoch_oversold']} or >= D - no signal")
            return None

        # Signal found!
        logger.info(f"🎯 ENTRY SIGNAL: {symbol}")
        logger.info(f"   Price: ${price:.2f}")
        logger.info(f"   ADX: {adx:.1f} (trending)")
        logger.info(f"   Stoch K: {stoch_k:.1f} (oversold)")
        logger.info(f"   Stoch D: {stoch_d:.1f}")

        return {
            "symbol": symbol,
            "price": price,
            "adx": adx,
            "stoch_k": stoch_k,
            "stoch_d": stoch_d
        }

    def run_scan(self, symbols: List[str]):
        """Scan symbols for entry signals using Schwab data"""
        logger.info("=" * 80)
        logger.info("BOT SIGNAL SCAN - USING SCHWAB DATA")
        logger.info("=" * 80)

        signals = []
        analyzed = 0
        skipped = 0

        for i, symbol in enumerate(symbols, 1):
            logger.info(f"\n[{i}/{len(symbols)}] Scanning {symbol}...")

            signal = self.check_entry_signal(symbol)

            if signal:
                signals.append(signal)
                analyzed += 1
            else:
                skipped += 1

        # Summary
        logger.info("\n" + "=" * 80)
        logger.info("SCAN SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Symbols scanned: {len(symbols)}")
        logger.info(f"Signals generated: {len(signals)}")
        logger.info(f"Success rate: {len(signals)/len(symbols)*100:.1f}%")

        if signals:
            logger.info("\n📊 Entry signals:")
            for sig in signals:
                logger.info(f"  • {sig['symbol']}: ${sig['price']:.2f} (ADX {sig['adx']:.1f}, Stoch {sig['stoch_k']:.1f})")

        return signals


def main():
    """Run bot test with Schwab data"""
    logger.info("\n")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║" + "  BOT INTEGRATION TEST: SCHWAB DATA".center(78) + "║")
    logger.info("║" + "  Using Schwab API instead of yfinance".center(78) + "║")
    logger.info("╚" + "=" * 78 + "╝")

    # Test symbols
    test_symbols = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
        "NVDA", "META", "NFLX", "ADBE", "PYPL"
    ]

    logger.info(f"\nTesting signal generation for {len(test_symbols)} symbols")
    logger.info("Data source: Charles Schwab API (not yfinance)")
    logger.info("Entry criteria: ADX > 20, Stoch < 30")

    bot = BotWithSchwabTest()
    signals = bot.run_scan(test_symbols)

    # Results
    logger.info("\n" + "=" * 80)
    logger.info("✅ TEST COMPLETE")
    logger.info("=" * 80)

    if signals:
        logger.info(f"\n✅ Generated {len(signals)} entry signals from Schwab data!")
        logger.info("   Ready to integrate Schwab into bot_production_final.py")
    else:
        logger.warning(f"\n⚠️  No signals generated (market conditions may not allow entries)")

    logger.info("\nNext steps:")
    logger.info("1. Review signals above")
    logger.info("2. Compare with yfinance version")
    logger.info("3. If signals match, integrate Schwab into bot_production_final.py")
    logger.info("4. Deploy to production")

    return 0


if __name__ == "__main__":
    exit(main())
