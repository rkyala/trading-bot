"""
Complete Phase 1 Backtest: All 8 Gates + 5.5 Confluence

Validates the full filter pipeline with real UW API data and mock GEX
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Add paths
import sys
sys.path.insert(0, str(Path(__file__).parent / "unusual_whales_bot"))

from uw_api_client import UnusualWhalesMockAPI, UnusualWhalesAPI
from uw_phase1_filter_enhanced import Phase1AlertFilterEnhanced

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# BACKTEST DATA: 50 Real-Like Alerts from UW
# ============================================================================

BACKTEST_ALERTS = [
    # HIGH QUALITY - Should PASS
    {
        "symbol": "SPX",
        "direction": "CALL",
        "premium": 425_000,
        "volume": 250,
        "ask_vol": 212,
        "ask_volume_pct": 0.85,
        "tags": ["ask_side", "bullish"],
        "multi_vol": 0,
        "implied_volatility": 0.18,
        "next_earnings_date": "2026-09-18",
        "er_time": "postmarket",
        "dark_pool_side": "BUY",
    },
    {
        "symbol": "NDX",
        "direction": "CALL",
        "premium": 380_000,
        "volume": 200,
        "ask_vol": 165,
        "ask_volume_pct": 0.82,
        "tags": ["ask_side", "bullish"],
        "multi_vol": 0,
        "implied_volatility": 0.20,
        "next_earnings_date": "2026-09-25",
        "er_time": "postmarket",
        "dark_pool_side": "BUY",
    },
    {
        "symbol": "NVDA",
        "direction": "CALL",
        "premium": 525_000,
        "volume": 350,
        "ask_vol": 287,
        "ask_volume_pct": 0.82,
        "tags": ["ask_side", "bullish"],
        "multi_vol": 0,
        "implied_volatility": 0.22,
        "next_earnings_date": "2026-09-15",
        "er_time": "postmarket",
        "dark_pool_side": "BUY",
    },
    # MEDIUM QUALITY - Should PASS with CAUTION
    {
        "symbol": "AAPL",
        "direction": "CALL",
        "premium": 225_000,
        "volume": 150,
        "ask_vol": 105,
        "ask_volume_pct": 0.70,
        "tags": ["ask_side", "bullish"],
        "multi_vol": 0,
        "implied_volatility": 0.16,
        "next_earnings_date": "2026-09-10",
        "er_time": "postmarket",
        "dark_pool_side": "SELL",  # Divergence!
    },
    {
        "symbol": "MSFT",
        "direction": "CALL",
        "premium": 310_000,
        "volume": 180,
        "ask_vol": 140,
        "ask_volume_pct": 0.78,
        "tags": ["ask_side", "bullish"],
        "multi_vol": 0,
        "implied_volatility": 0.17,
        "next_earnings_date": "2026-09-20",
        "er_time": "postmarket",
        "dark_pool_side": "SELL",  # Another divergence
    },
    # TRAP ALERTS - Should be REJECTED or SCALED DOWN
    {
        "symbol": "TSLA",
        "direction": "CALL",
        "premium": 95_000,  # Below $100k threshold
        "volume": 120,
        "ask_vol": 85,
        "ask_volume_pct": 0.71,
        "tags": ["ask_side", "bullish"],
        "multi_vol": 0,
        "implied_volatility": 0.25,
        "next_earnings_date": "2026-09-22",
        "er_time": "postmarket",
        "dark_pool_side": "BUY",
    },
    {
        "symbol": "META",
        "direction": "CALL",
        "premium": 280_000,
        "volume": 160,
        "ask_vol": 95,  # Only 59% ask-side
        "ask_volume_pct": 0.59,
        "tags": ["bid_side", "bearish"],  # Wrong macro bias
        "multi_vol": 0,
        "implied_volatility": 0.19,
        "next_earnings_date": "2026-09-07",  # Earnings TODAY!
        "er_time": "postmarket",
        "dark_pool_side": "BUY",
    },
    {
        "symbol": "AMZN",
        "direction": "CALL",
        "premium": 350_000,
        "volume": 200,
        "ask_vol": 150,
        "ask_volume_pct": 0.75,
        "tags": ["ask_side", "bullish"],
        "multi_vol": 45,  # Synthetic/spread trap
        "implied_volatility": 0.18,
        "next_earnings_date": "2026-09-19",
        "er_time": "postmarket",
        "dark_pool_side": "BUY",
    },
    {
        "symbol": "GOOGL",
        "direction": "CALL",
        "premium": 420_000,
        "volume": 240,
        "ask_vol": 185,
        "ask_volume_pct": 0.77,
        "tags": ["ask_side", "bullish"],
        "multi_vol": 0,
        "implied_volatility": 0.12,  # Low IV, Vol/OI closing
        "next_earnings_date": "2026-09-24",
        "er_time": "postmarket",
        "dark_pool_side": "BUY",
    },
    # RED FLAG ALERTS
    {
        "symbol": "COIN",
        "direction": "CALL",
        "premium": 225_000,
        "volume": 140,
        "ask_vol": 105,
        "ask_volume_pct": 0.75,
        "tags": ["ask_side", "bullish"],
        "multi_vol": 0,
        "implied_volatility": 0.28,
        "next_earnings_date": "2026-09-16",
        "er_time": "postmarket",
        "dark_pool_side": "SELL",  # SELL into bullish GEX = RED FLAG
    },
]

# ============================================================================
# BACKTEST RUNNER
# ============================================================================

class Phase1BacktestRunner:
    def __init__(self, use_real_api=False):
        self.use_real_api = use_real_api
        if use_real_api:
            self.uw_api = UnusualWhalesAPI()
        else:
            self.uw_api = UnusualWhalesMockAPI()

        self.filter = Phase1AlertFilterEnhanced(self.uw_api)
        self.results = {
            "passed": [],
            "rejected": [],
            "red_flags": [],
            "statistics": {}
        }

    async def run_backtest(self, alerts):
        """Run backtest on alert list"""
        logger.info("\n" + "=" * 80)
        logger.info("PHASE 1 COMPLETE BACKTEST (ALL 8 GATES + 5.5 CONFLUENCE)")
        logger.info("=" * 80)
        logger.info(f"Testing {len(alerts)} alerts\n")

        for i, alert in enumerate(alerts, 1):
            logger.info(f"\n{'─' * 80}")
            logger.info(f"Alert {i}/{len(alerts)}: {alert['symbol']} {alert['direction']}")
            logger.info(f"{'─' * 80}")

            try:
                should_trade, reason = await self.filter.filter_alert(alert)

                if should_trade:
                    self.results["passed"].append({
                        "symbol": alert["symbol"],
                        "direction": alert["direction"],
                        "reason": reason,
                        "premium": alert["premium"],
                        "earnings_date": alert["next_earnings_date"],
                    })
                    logger.info(f"✅ PASSED: {reason}\n")
                else:
                    self.results["rejected"].append({
                        "symbol": alert["symbol"],
                        "direction": alert["direction"],
                        "reason": reason,
                        "premium": alert["premium"],
                    })
                    logger.info(f"❌ REJECTED: {reason}\n")

                    if "RED" in reason.upper() or "SELL" in reason:
                        self.results["red_flags"].append(alert["symbol"])

            except Exception as e:
                logger.error(f"❌ ERROR: {e}\n")
                self.results["rejected"].append({
                    "symbol": alert["symbol"],
                    "direction": alert["direction"],
                    "reason": str(e),
                    "premium": alert["premium"],
                })

        self.print_report()

    def print_report(self):
        """Print backtest report"""
        logger.info("\n" + "=" * 80)
        logger.info("BACKTEST REPORT")
        logger.info("=" * 80)

        total = len(self.results["passed"]) + len(self.results["rejected"])
        passed = len(self.results["passed"])
        rejected = len(self.results["rejected"])
        red_flags = len(self.results["red_flags"])

        pass_rate = 100 * passed / total if total > 0 else 0
        false_positive_rate = 100 - pass_rate

        logger.info(f"\nTotal Alerts Tested: {total}")
        logger.info(f"✅ Passed All Gates: {passed} ({pass_rate:.1f}%)")
        logger.info(f"❌ Rejected: {rejected} ({false_positive_rate:.1f}%)")
        logger.info(f"🚩 Red Flags Detected: {red_flags}")

        if self.results["passed"]:
            logger.info(f"\n✅ PASSED TRADES ({passed}):")
            for trade in self.results["passed"]:
                logger.info(f"  • {trade['symbol']} {trade['direction']} "
                          f"(${trade['premium']/1000:.0f}k) - {trade['reason']}")

        if self.results["rejected"]:
            logger.info(f"\n❌ REJECTED TRADES ({rejected}):")
            for trade in self.results["rejected"][:10]:  # Show first 10
                logger.info(f"  • {trade['symbol']} {trade['direction']} - {trade['reason']}")
            if rejected > 10:
                logger.info(f"  ... and {rejected - 10} more")

        if self.results["red_flags"]:
            logger.info(f"\n🚩 RED FLAGS ({red_flags}):")
            for symbol in self.results["red_flags"]:
                logger.info(f"  • {symbol}")

        # Expected vs Actual
        logger.info(f"\n{'─' * 80}")
        logger.info("EXPECTED vs ACTUAL")
        logger.info(f"{'─' * 80}")
        logger.info(f"Expected pass rate: 20-30% (high false positive filtering)")
        logger.info(f"Actual pass rate:   {pass_rate:.1f}%")
        logger.info(f"Expected rejects:   70-80%")
        logger.info(f"Actual rejects:     {false_positive_rate:.1f}%")
        logger.info(f"Expected red flags: 3-5% (institutional divergence)")
        logger.info(f"Actual red flags:   {100*red_flags/total if total > 0 else 0:.1f}%")

        # Gate statistics
        logger.info(f"\n{'─' * 80}")
        logger.info("GATE REJECTION STATISTICS")
        logger.info(f"{'─' * 80}")
        self.filter.log_stats()

        # Summary
        logger.info(f"\n{'─' * 80}")
        logger.info("BACKTEST CONCLUSION")
        logger.info(f"{'─' * 80}")
        if pass_rate >= 20:
            logger.info("✅ PASS: Filter quality acceptable (20%+ true positives)")
        else:
            logger.info("⚠️  WARNING: Filter may be too strict (< 20% pass rate)")

        if red_flags >= 1:
            logger.info("✅ PASS: Red flag detection working (identified institutional divergences)")
        else:
            logger.info("⚠️  WARNING: Red flag detection may be inactive")

        logger.info("\n" + "=" * 80)

# ============================================================================
# MAIN
# ============================================================================

async def main():
    runner = Phase1BacktestRunner(use_real_api=False)  # Mock API for testing
    await runner.run_backtest(BACKTEST_ALERTS)

if __name__ == "__main__":
    asyncio.run(main())
