#!/usr/bin/env python3
"""
Compare Schwab vs yfinance market data fetching
Verify both APIs return same technicals for bot compatibility
"""

import logging
import json
from datetime import datetime
from schwab_marketdata_fetcher import SchwabMarketDataFetcher

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)


def test_schwab_fetcher():
    """Test Schwab data fetcher"""
    logger.info("=" * 80)
    logger.info("SCHWAB DATA FETCHER TEST")
    logger.info("=" * 80)

    test_symbols = ["AAPL", "MSFT", "GOOGL", "TSLA", "AMZN"]
    results = {}

    for symbol in test_symbols:
        logger.info(f"\n📊 Testing {symbol}...")
        result = SchwabMarketDataFetcher.get_technicals(symbol, use_cache=False)

        if result:
            results[symbol] = result
            logger.info(f"✅ {symbol} SUCCESS")
            logger.info(f"   Price:   ${result['price']:.2f}")
            logger.info(f"   ADX:     {result['adx']:.2f}")
            logger.info(f"   Stoch K: {result['stoch_k']:.2f}")
            logger.info(f"   Stoch D: {result['stoch_d']:.2f}")
        else:
            logger.warning(f"⚠️  {symbol} FAILED")

    return results


def compare_with_yfinance(schwab_results):
    """Compare Schwab results with yfinance"""
    logger.info("\n" + "=" * 80)
    logger.info("COMPARISON: SCHWAB vs YFINANCE")
    logger.info("=" * 80)

    try:
        # Import yfinance fetcher
        import sys
        sys.path.insert(0, '/Users/ramayalala/trading_bot')
        from bot_production_final import MarketDataFetcher as YfinanceFetcher

        comparison_data = []

        for symbol in schwab_results.keys():
            logger.info(f"\n📊 {symbol}")

            # Get yfinance data
            yf_result = YfinanceFetcher.get_technicals(symbol, use_cache=False)

            if not yf_result:
                logger.warning(f"   YFINANCE: FAILED")
                continue

            schwab = schwab_results[symbol]
            yf = yf_result

            logger.info(f"   SCHWAB  | Price: ${schwab['price']:.2f} | ADX: {schwab['adx']:.1f} | Stoch: {schwab['stoch_k']:.1f}")
            logger.info(f"   YFINANCE| Price: ${yf['price']:.2f} | ADX: {yf['adx']:.1f} | Stoch: {yf['stoch_k']:.1f}")

            # Calculate differences
            price_diff = abs(schwab['price'] - yf['price'])
            adx_diff = abs(schwab['adx'] - yf['adx'])
            stoch_diff = abs(schwab['stoch_k'] - yf['stoch_k'])

            logger.info(f"   DIFF    | Price: ${price_diff:.2f} | ADX: {adx_diff:.1f} | Stoch: {stoch_diff:.1f}")

            comparison_data.append({
                'symbol': symbol,
                'price_diff': price_diff,
                'adx_diff': adx_diff,
                'stoch_diff': stoch_diff
            })

        # Summary
        if comparison_data:
            logger.info("\n" + "=" * 80)
            logger.info("SUMMARY")
            logger.info("=" * 80)

            avg_price_diff = sum(c['price_diff'] for c in comparison_data) / len(comparison_data)
            avg_adx_diff = sum(c['adx_diff'] for c in comparison_data) / len(comparison_data)
            avg_stoch_diff = sum(c['stoch_diff'] for c in comparison_data) / len(comparison_data)

            logger.info(f"Average differences across {len(comparison_data)} symbols:")
            logger.info(f"  Price:  ${avg_price_diff:.2f}")
            logger.info(f"  ADX:    {avg_adx_diff:.1f}")
            logger.info(f"  Stoch:  {avg_stoch_diff:.1f}")

            if avg_price_diff < 1.0 and avg_adx_diff < 5.0 and avg_stoch_diff < 5.0:
                logger.info("\n✅ COMPATIBILITY: Schwab data is compatible with bot!")
            else:
                logger.warning("\n⚠️  COMPATIBILITY: Some differences detected")

    except Exception as e:
        logger.error(f"Could not compare with yfinance: {e}")


def test_caching():
    """Test that caching works"""
    logger.info("\n" + "=" * 80)
    logger.info("CACHING TEST")
    logger.info("=" * 80)

    symbol = "AAPL"

    # Clear cache
    SchwabMarketDataFetcher._cache.clear()

    # First fetch (cache miss)
    import time
    start = time.time()
    result1 = SchwabMarketDataFetcher.get_technicals(symbol, use_cache=True)
    elapsed1 = time.time() - start

    # Second fetch (cache hit)
    start = time.time()
    result2 = SchwabMarketDataFetcher.get_technicals(symbol, use_cache=True)
    elapsed2 = time.time() - start

    if result1 and result2:
        speedup = elapsed1 / elapsed2 if elapsed2 > 0 else float('inf')
        logger.info(f"✅ First fetch:  {elapsed1:.3f}s (API call)")
        logger.info(f"✅ Second fetch: {elapsed2:.3f}s (cache hit)")
        logger.info(f"✅ Speedup: {speedup:.0f}x faster")

        if elapsed2 < elapsed1 * 0.5:
            logger.info("✅ CACHING WORKS!")


def main():
    """Run all tests"""
    logger.info("\n")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║" + "  SCHWAB vs YFINANCE COMPARISON TEST".center(78) + "║")
    logger.info("║" + "  Verify bot compatibility before integration".center(78) + "║")
    logger.info("╚" + "=" * 78 + "╝")

    # Test 1: Schwab fetcher
    schwab_results = test_schwab_fetcher()

    if not schwab_results:
        logger.error("\n❌ Schwab fetcher failed - cannot continue")
        return 1

    # Test 2: Compare with yfinance
    compare_with_yfinance(schwab_results)

    # Test 3: Caching
    test_caching()

    logger.info("\n" + "=" * 80)
    logger.info("✅ ALL TESTS COMPLETE")
    logger.info("=" * 80)
    logger.info("\nNext: Integrate Schwab into bot_production_final.py")
    logger.info("Then: Run bot cycles with Schwab data")

    return 0


if __name__ == "__main__":
    exit(main())
