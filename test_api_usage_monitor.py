"""
Test: API Usage Monitoring Integration

Validates that:
1. API usage is tracked from response headers
2. Quota alerts are triggered at 75% and 95%
3. Status reporting works correctly
"""

import asyncio
import logging
from pathlib import Path
import sys

# Add paths
sys.path.insert(0, str(Path(__file__).parent / "unusual_whales_bot"))

from uw_api_usage_monitor import APIUsageMonitor, APIUsageSnapshot
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TestAPIUsageMonitor:
    """Test API usage monitoring"""

    def __init__(self):
        self.monitor = APIUsageMonitor()

    def test_basic_tracking(self):
        """Test basic usage tracking from headers"""
        logger.info("\n" + "="*80)
        logger.info("TEST 1: Basic Usage Tracking")
        logger.info("="*80)

        # Simulate API response headers
        mock_headers = {
            "x-uw-daily-req-count": "50",
            "x-uw-token-req-limit": "15000",
            "x-uw-minute-req-counter": "3",
            "x-uw-req-per-minute-remaining": "117",
            "x-uw-req-per-minute-reset": "45000",
        }

        snapshot = self.monitor.process_response_headers(mock_headers)

        logger.info(f"✅ Snapshot captured: {snapshot}")
        logger.info(f"   Daily: {snapshot.daily_hits}/{snapshot.daily_limit} ({snapshot.daily_percent_used:.1f}%)")
        logger.info(f"   Minute: {snapshot.minute_hits} hits, {snapshot.minute_remaining} remaining")
        logger.info(f"   Status: {self.monitor.get_status_summary()}")

        assert snapshot.daily_hits == 50
        assert snapshot.daily_limit == 15000
        assert snapshot.daily_percent_used == 50/15000*100
        logger.info("✅ PASSED\n")

    def test_warning_threshold(self):
        """Test warning alert at 75% usage"""
        logger.info("="*80)
        logger.info("TEST 2: Warning Threshold (75%)")
        logger.info("="*80)

        # Reset monitor
        self.monitor = APIUsageMonitor()

        # Simulate 75% usage
        mock_headers = {
            "x-uw-daily-req-count": "11250",  # 75% of 15000
            "x-uw-token-req-limit": "15000",
            "x-uw-minute-req-counter": "0",
            "x-uw-req-per-minute-remaining": "120",
            "x-uw-req-per-minute-reset": "60000",
        }

        snapshot = self.monitor.process_response_headers(mock_headers)

        logger.info(f"Daily usage: {snapshot.daily_percent_used:.1f}%")
        logger.info(f"Is warning: {snapshot.is_quota_warning}")
        logger.info(f"Is critical: {snapshot.is_quota_critical}")
        logger.info(f"Remaining hits: {snapshot.daily_limit - snapshot.daily_hits}")

        assert snapshot.is_quota_warning
        assert not snapshot.is_quota_critical
        logger.info("✅ PASSED (Warning correctly triggered)\n")

    def test_critical_threshold(self):
        """Test critical alert at 95% usage"""
        logger.info("="*80)
        logger.info("TEST 3: Critical Threshold (95%)")
        logger.info("="*80)

        # Reset monitor
        self.monitor = APIUsageMonitor()

        # Simulate 95% usage
        mock_headers = {
            "x-uw-daily-req-count": "14250",  # 95% of 15000
            "x-uw-token-req-limit": "15000",
            "x-uw-minute-req-counter": "0",
            "x-uw-req-per-minute-remaining": "120",
            "x-uw-req-per-minute-reset": "60000",
        }

        snapshot = self.monitor.process_response_headers(mock_headers)

        logger.info(f"Daily usage: {snapshot.daily_percent_used:.1f}%")
        logger.info(f"Is warning: {snapshot.is_quota_warning}")
        logger.info(f"Is critical: {snapshot.is_quota_critical}")
        logger.info(f"Remaining hits: {snapshot.daily_limit - snapshot.daily_hits}")

        assert snapshot.is_quota_critical
        assert snapshot.is_quota_warning  # Critical also triggers warning
        logger.info("✅ PASSED (Critical alert correctly triggered)\n")

    def test_halt_on_exhausted(self):
        """Test halt decision when quota exhausted"""
        logger.info("="*80)
        logger.info("TEST 4: Halt on Exhausted Quota")
        logger.info("="*80)

        # Reset monitor
        self.monitor = APIUsageMonitor()

        # Simulate 100% usage
        mock_headers = {
            "x-uw-daily-req-count": "15000",  # 100% of 15000
            "x-uw-token-req-limit": "15000",
            "x-uw-minute-req-counter": "0",
            "x-uw-req-per-minute-remaining": "120",
            "x-uw-req-per-minute-reset": "60000",
        }

        snapshot = self.monitor.process_response_headers(mock_headers)
        should_halt = self.monitor.should_halt_on_quota()

        logger.info(f"Daily usage: {snapshot.daily_percent_used:.1f}%")
        logger.info(f"Should halt: {should_halt}")
        logger.info(f"Remaining hits: {snapshot.daily_limit - snapshot.daily_hits}")

        assert should_halt
        logger.info("✅ PASSED (Bot correctly halts when quota exhausted)\n")

    def test_green_status(self):
        """Test green status under 25% usage"""
        logger.info("="*80)
        logger.info("TEST 5: Green Status (<25% usage)")
        logger.info("="*80)

        # Reset monitor
        self.monitor = APIUsageMonitor()

        # Simulate low usage
        mock_headers = {
            "x-uw-daily-req-count": "100",  # <1% of 15000
            "x-uw-token-req-limit": "15000",
            "x-uw-minute-req-counter": "2",
            "x-uw-req-per-minute-remaining": "118",
            "x-uw-req-per-minute-reset": "58000",
        }

        snapshot = self.monitor.process_response_headers(mock_headers)
        status = self.monitor.get_status_summary()

        logger.info(f"Status: {status}")
        logger.info(f"Daily: {snapshot.daily_hits}/{snapshot.daily_limit} ({snapshot.daily_percent_used:.1f}%)")
        logger.info(f"Minute: {snapshot.minute_remaining} remaining")

        assert not snapshot.is_quota_warning
        assert "🟢" in status
        logger.info("✅ PASSED (Status shows green)\n")

    def test_yellow_status(self):
        """Test yellow status at 75% usage"""
        logger.info("="*80)
        logger.info("TEST 6: Yellow Status (75% usage)")
        logger.info("="*80)

        # Reset monitor
        self.monitor = APIUsageMonitor()

        # Simulate warning level usage
        mock_headers = {
            "x-uw-daily-req-count": "11250",  # 75% of 15000
            "x-uw-token-req-limit": "15000",
            "x-uw-minute-req-counter": "0",
            "x-uw-req-per-minute-remaining": "120",
            "x-uw-req-per-minute-reset": "60000",
        }

        snapshot = self.monitor.process_response_headers(mock_headers)
        status = self.monitor.get_status_summary()

        logger.info(f"Status: {status}")
        logger.info(f"Daily: {snapshot.daily_hits}/{snapshot.daily_limit} ({snapshot.daily_percent_used:.1f}%)")

        assert "🟡" in status
        logger.info("✅ PASSED (Status shows yellow/warning)\n")

    def test_red_status(self):
        """Test red status at 95%+ usage"""
        logger.info("="*80)
        logger.info("TEST 7: Red Status (95%+ usage)")
        logger.info("="*80)

        # Reset monitor
        self.monitor = APIUsageMonitor()

        # Simulate critical usage
        mock_headers = {
            "x-uw-daily-req-count": "14250",  # 95% of 15000
            "x-uw-token-req-limit": "15000",
            "x-uw-minute-req-counter": "0",
            "x-uw-req-per-minute-remaining": "120",
            "x-uw-req-per-minute-reset": "60000",
        }

        snapshot = self.monitor.process_response_headers(mock_headers)
        status = self.monitor.get_status_summary()

        logger.info(f"Status: {status}")
        logger.info(f"Daily: {snapshot.daily_hits}/{snapshot.daily_limit} ({snapshot.daily_percent_used:.1f}%)")

        assert "🔴" in status
        logger.info("✅ PASSED (Status shows red/critical)\n")

    def test_expected_tuesday_usage(self):
        """Simulate expected Tuesday usage pattern"""
        logger.info("="*80)
        logger.info("TEST 8: Expected Tuesday Usage Pattern")
        logger.info("="*80)

        self.monitor = APIUsageMonitor()

        # Morning: 2 alerts × 4 calls = 8 hits
        logger.info("Morning (9:35-10:00): 2 alerts × 4 calls = 8 hits")
        headers_8 = {
            "x-uw-daily-req-count": "8",
            "x-uw-token-req-limit": "15000",
            "x-uw-minute-req-counter": "2",
            "x-uw-req-per-minute-remaining": "118",
            "x-uw-req-per-minute-reset": "58000",
        }
        self.monitor.process_response_headers(headers_8)
        logger.info(f"  Status: {self.monitor.get_status_summary()}")

        # Midday: 8 alerts × 4 calls = 32 hits (total: 40)
        logger.info("\nMidday (10:00-3:30): 8 alerts × 4 calls = 32 hits")
        headers_40 = {
            "x-uw-daily-req-count": "40",
            "x-uw-token-req-limit": "15000",
            "x-uw-minute-req-counter": "1",
            "x-uw-req-per-minute-remaining": "119",
            "x-uw-req-per-minute-reset": "59000",
        }
        self.monitor.process_response_headers(headers_40)
        logger.info(f"  Status: {self.monitor.get_status_summary()}")

        # Afternoon: 3 alerts × 4 calls = 12 hits (total: 52)
        logger.info("\nAfternoon (3:30-4:00): 3 alerts × 4 calls = 12 hits")
        headers_52 = {
            "x-uw-daily-req-count": "52",
            "x-uw-token-req-limit": "15000",
            "x-uw-minute-req-counter": "0",
            "x-uw-req-per-minute-remaining": "120",
            "x-uw-req-per-minute-reset": "60000",
        }
        self.monitor.process_response_headers(headers_52)
        status_final = self.monitor.get_status_summary()
        logger.info(f"  Status: {status_final}")

        remaining = self.monitor.get_daily_hits_remaining()
        logger.info(f"\nDaily Summary:")
        logger.info(f"  Total hits: 52/15000")
        logger.info(f"  Remaining: {remaining} hits")
        logger.info(f"  Safety margin: 99.65%")

        assert remaining == 14948
        assert not self.monitor.should_halt_on_quota()
        logger.info("✅ PASSED (Tuesday pattern has 99.65% safety margin)\n")

    def run_all_tests(self):
        """Run complete test suite"""
        logger.info("\n\n")
        logger.info("╔" + "="*78 + "╗")
        logger.info("║" + " API USAGE MONITOR TEST SUITE".center(78) + "║")
        logger.info("║" + " Tuesday Launch Readiness".center(78) + "║")
        logger.info("╚" + "="*78 + "╝")

        try:
            self.test_basic_tracking()
            self.test_warning_threshold()
            self.test_critical_threshold()
            self.test_halt_on_exhausted()
            self.test_green_status()
            self.test_yellow_status()
            self.test_red_status()
            self.test_expected_tuesday_usage()

            logger.info("\n" + "="*80)
            logger.info("🟢 ALL TESTS PASSED")
            logger.info("="*80)
            logger.info("✅ API usage monitoring ready for Tuesday launch")
            logger.info("✅ Quota tracking: WORKING")
            logger.info("✅ Alert thresholds: WORKING")
            logger.info("✅ Status reporting: WORKING")
            logger.info("="*80 + "\n")

            return True

        except AssertionError as e:
            logger.error(f"\n❌ TEST FAILED: {e}")
            return False


if __name__ == "__main__":
    tester = TestAPIUsageMonitor()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)
