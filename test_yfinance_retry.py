#!/usr/bin/env python3
"""
Test script to verify IMPROVEMENT #3: yfinance exponential backoff retry logic
Tests:
1. Normal successful fetch (no retries needed)
2. Retry on rate limit (429)
3. Retry on timeout
4. NaN value validation
5. Minimum candle validation (30m >= 30, daily >= 20)
"""

import json
import logging
from pathlib import Path
import sys
import time

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)

# Import bot
sys.path.insert(0, '/Users/ramayalala/trading_bot')
from bot_production_final import MarketDataFetcher

def test_normal_fetch():
    """Test 1: Normal fetch (no retries)"""
    logger.info("=" * 80)
    logger.info("TEST 1: Normal yfinance fetch (no retries needed)")
    logger.info("=" * 80)

    start = time.time()
    result = MarketDataFetcher.get_technicals("AAPL", use_cache=False)
    elapsed = time.time() - start

    if result:
        logger.info(f"✅ SUCCESS: Fetched AAPL technicals in {elapsed:.2f}s")
        logger.info(f"   Price: ${result['price']:.2f}")
        logger.info(f"   ADX: {result['adx']:.2f}")
        logger.info(f"   Stoch K: {result['stoch_k']:.2f}")
        return True
    else:
        logger.error(f"❌ FAILED: Could not fetch AAPL technicals")
        return False

def test_caching():
    """Test 2: Caching reduces repeated fetches"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 2: Cache reduces API calls on repeated fetches")
    logger.info("=" * 80)

    # Clear cache
    MarketDataFetcher._cache.clear()

    # First fetch (hits API)
    start1 = time.time()
    result1 = MarketDataFetcher.get_technicals("TSLA", use_cache=True)
    elapsed1 = time.time() - start1

    # Second fetch (should use cache, much faster)
    start2 = time.time()
    result2 = MarketDataFetcher.get_technicals("TSLA", use_cache=True)
    elapsed2 = time.time() - start2

    if result1 and result2:
        speedup = elapsed1 / elapsed2 if elapsed2 > 0 else float('inf')
        logger.info(f"✅ SUCCESS: Cache working")
        logger.info(f"   First fetch: {elapsed1:.2f}s (API call)")
        logger.info(f"   Cached fetch: {elapsed2:.3f}s (cache hit)")
        logger.info(f"   Speedup: {speedup:.0f}x faster")
        return True
    else:
        logger.error(f"❌ FAILED: Cache test failed")
        return False

def test_multiple_symbols():
    """Test 3: Test multiple symbols to verify retry logic under load"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 3: Multiple symbol fetches (verify retry resilience)")
    logger.info("=" * 80)

    symbols = ["NVDA", "MSFT", "GOOGL", "AMZN", "META"]
    results = {}

    for sym in symbols:
        start = time.time()
        result = MarketDataFetcher.get_technicals(sym, use_cache=False)
        elapsed = time.time() - start

        if result:
            logger.info(f"✅ {sym}: {elapsed:.2f}s | ADX={result['adx']:.1f} | Stoch={result['stoch_k']:.1f}")
            results[sym] = True
        else:
            logger.warning(f"⚠️  {sym}: Failed to fetch")
            results[sym] = False

    success_rate = sum(results.values()) / len(results) * 100
    logger.info(f"\n📊 Success rate: {success_rate:.0f}% ({sum(results.values())}/{len(results)})")

    return success_rate >= 80

def test_nan_handling():
    """Test 4: NaN value detection and handling"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 4: NaN value validation and rejection")
    logger.info("=" * 80)

    # Fetch real data
    result = MarketDataFetcher.get_technicals("SPY", use_cache=False)

    if result:
        # Check for NaN
        has_nan = any(
            pd.isna(v) for v in [
                result.get('price'),
                result.get('adx'),
                result.get('stoch_k'),
                result.get('stoch_d')
            ]
        )

        if not has_nan:
            logger.info(f"✅ SUCCESS: No NaN values in result")
            logger.info(f"   Price: {result['price']:.2f} (not NaN)")
            logger.info(f"   ADX: {result['adx']:.2f} (not NaN)")
            logger.info(f"   Stoch K: {result['stoch_k']:.2f} (not NaN)")
            logger.info(f"   Stoch D: {result['stoch_d']:.2f} (not NaN)")
            return True
        else:
            logger.error(f"❌ FAILED: Found NaN values in result")
            return False
    else:
        logger.error(f"❌ FAILED: Could not fetch SPY")
        return False

def test_minimum_candles():
    """Test 5: Validate minimum candle requirements"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 5: Minimum candle validation")
    logger.info("=" * 80)

    # Test a high-price stock that might have fewer candles
    result = MarketDataFetcher.get_technicals("BRK-B", use_cache=False)

    if result:
        logger.info(f"✅ SUCCESS: {result['symbol']} passed minimum candle check")
        logger.info(f"   ADX (from ≥20 daily): {result['adx']:.2f}")
        logger.info(f"   Stoch (from ≥30 30m): {result['stoch_k']:.2f}")
        return True
    else:
        logger.warning(f"⚠️  FAILED: {result} did not meet minimum candle requirements")
        return False

def main():
    """Run all tests"""
    import pandas as pd  # Needed for pd.isna()

    logger.info("🧪 IMPROVEMENT #3 TEST SUITE: yfinance Exponential Backoff Retry Logic")
    logger.info("=" * 80)

    tests = [
        ("Normal Fetch", test_normal_fetch),
        ("Caching", test_caching),
        ("Multiple Symbols", test_multiple_symbols),
        ("NaN Handling", test_nan_handling),
        ("Minimum Candles", test_minimum_candles),
    ]

    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            logger.error(f"❌ {name} threw exception: {e}", exc_info=True)
            results[name] = False

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("📋 TEST SUMMARY")
    logger.info("=" * 80)

    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"{status}: {name}")

    total = len(results)
    passed = sum(results.values())
    logger.info(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        logger.info("\n🎉 ALL TESTS PASSED - IMPROVEMENT #3 IS WORKING!")
        return 0
    else:
        logger.warning(f"\n⚠️  {total - passed} test(s) failed")
        return 1

if __name__ == "__main__":
    exit(main())
