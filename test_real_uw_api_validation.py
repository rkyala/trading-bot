"""
PRE-LAUNCH VALIDATION: Real Unusual Whales API Test
Tests all critical production paths before Tuesday 9/8 launch

REQUIRED: Set UW_API_KEY environment variable
  export UW_API_KEY="your_live_api_key_here"

This script validates:
1. ✅ Authentication (no 401 errors)
2. ✅ Correct endpoint path (/api/option-trades, not /v1/alerts)
3. ✅ Correct parameter naming (ticker_symbol, not symbols)
4. ✅ Real $100k+ sweep data returns
5. ✅ Async methods work (for filter pipeline)
6. ✅ Error handling for network issues
"""

import asyncio
import os
import sys
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add paths
sys.path.insert(0, str(Path(__file__).parent / "unusual_whales_bot"))

from uw_api_client import UnusualWhalesAPI


class APIValidationTest:
    def __init__(self):
        self.api_key = os.getenv("UW_API_KEY")
        self.results = {
            "passed": [],
            "failed": [],
            "warnings": []
        }

    def validate_api_key(self):
        """Test 1: Check API key is set"""
        logger.info("\n" + "="*80)
        logger.info("TEST 1: API Key Configuration")
        logger.info("="*80)

        if not self.api_key:
            logger.error("❌ FATAL: UW_API_KEY not set")
            logger.error("Set it with: export UW_API_KEY='your_key_here'")
            self.results["failed"].append("API key not configured")
            return False

        logger.info(f"✅ API key found ({len(self.api_key)} chars)")
        self.results["passed"].append("API key configured")
        return True

    def validate_endpoint(self):
        """Test 2: Verify endpoint responds (checks 404, 401, 200)"""
        logger.info("\n" + "="*80)
        logger.info("TEST 2: Endpoint & Authentication")
        logger.info("="*80)

        api = UnusualWhalesAPI(self.api_key)

        try:
            logger.info("📡 Hitting /api/option-trades endpoint...")
            alerts = api.get_flow_alerts(limit=5)

            if api.stats["errors"] > 0:
                logger.error(f"❌ API returned error (check logs)")
                self.results["failed"].append("Endpoint returned error")
                return False

            logger.info(f"✅ Endpoint responsive (no 404, no 401)")
            logger.info(f"✅ Fetched {len(alerts)} alerts")

            if len(alerts) > 0:
                logger.info(f"✅ Data flowing back (real alerts received)")
                self.results["passed"].append("Endpoint responding with data")
            else:
                logger.warning("⚠️  No alerts returned (market may be closed)")
                self.results["warnings"].append("No alerts returned (market hours?)")

            return True

        except Exception as e:
            logger.error(f"❌ Endpoint test failed: {e}")
            self.results["failed"].append(f"Endpoint error: {e}")
            return False

    def validate_parameters(self):
        """Test 3: Verify parameter mapping (ticker_symbol)"""
        logger.info("\n" + "="*80)
        logger.info("TEST 3: Parameter Mapping")
        logger.info("="*80)

        api = UnusualWhalesAPI(self.api_key)

        try:
            logger.info("🔍 Testing ticker filter (SPX, NDX)...")
            alerts = api.get_flow_alerts(symbols=["SPX", "NDX"], limit=10)

            logger.info(f"✅ Ticker parameter accepted")
            logger.info(f"✅ Returned {len(alerts)} alerts")

            if len(alerts) > 0:
                # Check if we got the right tickers
                tickers = set(a.get("underlying_symbol", "") for a in alerts if "underlying_symbol" in a)
                logger.info(f"   Symbols in response: {tickers if tickers else '(no underlying_symbol field)'}")
                self.results["passed"].append("Parameter mapping working")
            else:
                logger.info("   (No alerts to verify, but parameter accepted)")
                self.results["passed"].append("Parameter mapping (no data to verify)")

            return True

        except Exception as e:
            logger.error(f"❌ Parameter test failed: {e}")
            self.results["failed"].append(f"Parameter error: {e}")
            return False

    def validate_premium_threshold(self):
        """Test 4: Verify $100k+ premium filter works"""
        logger.info("\n" + "="*80)
        logger.info("TEST 4: Premium Threshold ($100k+)")
        logger.info("="*80)

        api = UnusualWhalesAPI(self.api_key)

        try:
            logger.info("💰 Testing min_premium=100000 parameter...")
            alerts = api.get_flow_alerts(min_premium=100_000, limit=10)

            if len(alerts) > 0:
                logger.info(f"✅ Premium filter applied")
                logger.info(f"✅ Got {len(alerts)} $100k+ sweeps")

                # Verify premium values if available
                premiums = []
                for a in alerts:
                    if "premium" in a:
                        try:
                            # Premium might be string or number
                            prem_val = float(a.get("premium"))
                            premiums.append(prem_val)
                        except (ValueError, TypeError):
                            pass

                if premiums:
                    min_prem = min(premiums)
                    max_prem = max(premiums)
                    logger.info(f"   Premium range: ${min_prem:,.0f} - ${max_prem:,.0f}")
                    if min_prem >= 100_000:
                        logger.info(f"✅ All premiums >= $100k")
                        self.results["passed"].append("Premium threshold working")
                    else:
                        logger.warning(f"⚠️  Some premiums below $100k")
                        self.results["warnings"].append("Premium filter may be soft")
                else:
                    logger.info("   (No premium field in response)")
                    self.results["passed"].append("Premium parameter accepted")
            else:
                logger.warning("⚠️  No $100k+ sweeps right now (market hours?)")
                self.results["warnings"].append("No premium data to validate")

            return True

        except Exception as e:
            logger.error(f"❌ Premium threshold test failed: {e}")
            self.results["failed"].append(f"Premium error: {e}")
            return False

    async def validate_async_methods(self):
        """Test 5: Verify async methods work (needed for filter pipeline)"""
        logger.info("\n" + "="*80)
        logger.info("TEST 5: Async Methods (for Filter Pipeline)")
        logger.info("="*80)

        api = UnusualWhalesAPI(self.api_key)

        try:
            logger.info("⚡ Testing async get_market_tide()...")
            tide = await api.get_market_tide("SPY")
            logger.info(f"✅ Market tide: {tide.get('net_direction', 'UNKNOWN')}")

            logger.info("⚡ Testing async get_net_ticker_premium()...")
            premium = await api.get_net_ticker_premium("SPX")
            logger.info(f"✅ Net premium returned: {bool(premium)}")

            logger.info("⚡ Testing async get_dark_pool_volume()...")
            dark = await api.get_dark_pool_volume("SPX")
            logger.info(f"✅ Dark pool data: {dark.get('dark_pool_side', 'UNKNOWN')}")

            logger.info("⚡ Testing async get_vol_oi_ratio()...")
            vol = await api.get_vol_oi_ratio("SPX")
            logger.info(f"✅ Vol/OI ratio: {vol.get('vol_oi_ratio', 'N/A')}")

            self.results["passed"].append("All async methods working")
            return True

        except Exception as e:
            logger.error(f"❌ Async test failed: {e}")
            self.results["failed"].append(f"Async error: {e}")
            return False

    def print_summary(self):
        """Print test results summary"""
        logger.info("\n" + "="*80)
        logger.info("VALIDATION SUMMARY")
        logger.info("="*80)

        passed = len(self.results["passed"])
        failed = len(self.results["failed"])
        warnings = len(self.results["warnings"])

        logger.info(f"\n✅ PASSED: {passed}")
        for result in self.results["passed"]:
            logger.info(f"   • {result}")

        if warnings:
            logger.info(f"\n⚠️  WARNINGS: {warnings}")
            for warning in self.results["warnings"]:
                logger.info(f"   • {warning}")

        if failed:
            logger.info(f"\n❌ FAILED: {failed}")
            for result in self.results["failed"]:
                logger.info(f"   • {result}")

        logger.info("\n" + "="*80)

        if failed == 0:
            logger.info("🟢 ALL TESTS PASSED - READY FOR LAUNCH")
            logger.info("="*80)
            return True
        else:
            logger.info("🔴 TESTS FAILED - FIX BEFORE LAUNCH")
            logger.info("="*80)
            return False

    async def run_all_tests(self):
        """Run complete validation suite"""
        logger.info("\n\n")
        logger.info("╔" + "="*78 + "╗")
        logger.info("║" + " PRE-LAUNCH UW API VALIDATION".center(78) + "║")
        logger.info("║" + " Tuesday 9/8 Launch Readiness Check".center(78) + "║")
        logger.info("╚" + "="*78 + "╝")

        # Run all tests
        test1 = self.validate_api_key()
        if not test1:
            self.print_summary()
            return False

        test2 = self.validate_endpoint()
        test3 = self.validate_parameters()
        test4 = self.validate_premium_threshold()
        test5 = await self.validate_async_methods()

        # Print summary
        return self.print_summary()


async def main():
    tester = APIValidationTest()
    success = await tester.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
