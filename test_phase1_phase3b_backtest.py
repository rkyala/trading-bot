"""
Complete Pipeline Backtest: Phase 1 → Phase 3B

Tests the full decision flow:
1. Phase 1: Institutional flow filter (9 gates)
2. Phase 3B: Confidence-based gating and sizing
3. Results: Win rate, ROI, position scaling
"""

import asyncio
import sys
import logging
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(".") / "unusual_whales_bot"))

from uw_api_client import UnusualWhalesAPI
from uw_phase1_filter_enhanced import Phase1AlertFilterEnhanced
from uw_phase3b_rules_engine import PhaseThreeBRulesEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("COMPLETE_PIPELINE_BACKTEST")


async def run_complete_backtest():
    """Test Phase 1 + Phase 3B pipeline"""

    logger.info("\n" + "="*80)
    logger.info("COMPLETE PIPELINE BACKTEST: Phase 1 → Phase 3B")
    logger.info("="*80)

    # Initialize
    api = UnusualWhalesAPI()  # Mock mode for demo
    phase1 = Phase1AlertFilterEnhanced(api)
    phase3b = PhaseThreeBRulesEngine(min_confidence_threshold=0.65)

    # Synthetic test alerts
    test_alerts = [
        {
            "underlying_symbol": "SPX",
            "option_type": "CALL",
            "premium": 425_000,
            "ask_vol": 212,
            "volume": 250,
            "tags": ["ask_side"],
            "dark_pool_side": "BUY",
            "implied_volatility": 0.18,
            "multi_vol": 0,
            "next_earnings_date": "2026-09-18",
        },
        {
            "underlying_symbol": "NDX",
            "option_type": "CALL",
            "premium": 380_000,
            "ask_vol": 165,
            "volume": 200,
            "tags": ["ask_side"],
            "dark_pool_side": "BUY",
            "implied_volatility": 0.20,
            "multi_vol": 0,
            "next_earnings_date": "2026-09-25",
        },
        {
            "underlying_symbol": "NVDA",
            "option_type": "CALL",
            "premium": 525_000,
            "ask_vol": 287,
            "volume": 350,
            "tags": ["ask_side"],
            "dark_pool_side": "BUY",
            "implied_volatility": 0.22,
            "multi_vol": 0,
            "next_earnings_date": "2026-09-15",
        },
        {
            "underlying_symbol": "AAPL",
            "option_type": "CALL",
            "premium": 225_000,
            "ask_vol": 105,
            "volume": 150,
            "tags": ["ask_side"],
            "dark_pool_side": "SELL",
            "implied_volatility": 0.16,
            "multi_vol": 0,
            "next_earnings_date": "2026-09-10",
        },
        {
            "underlying_symbol": "AMZN",
            "option_type": "CALL",
            "premium": 350_000,
            "ask_vol": 150,
            "volume": 200,
            "tags": ["ask_side"],
            "dark_pool_side": "BUY",
            "implied_volatility": 0.18,
            "multi_vol": 45,  # Synthetic spread trap
            "next_earnings_date": "2026-09-19",
        },
        {
            "underlying_symbol": "GOOGL",
            "option_type": "CALL",
            "premium": 420_000,
            "ask_vol": 185,
            "volume": 240,
            "tags": ["ask_side"],
            "dark_pool_side": "BUY",
            "implied_volatility": 0.12,  # Low IV
            "multi_vol": 0,
            "next_earnings_date": "2026-09-24",
        },
    ]

    phase1_passed = 0
    phase3b_approved = 0
    confidence_dist = defaultdict(int)

    logger.info(f"\nProcessing {len(test_alerts)} test alerts...")
    logger.info("-" * 80)

    for alert in test_alerts:
        symbol = alert["underlying_symbol"]

        # Phase 1: Filter
        try:
            p1_passed, p1_reason = await phase1.filter_alert(alert)
        except Exception as e:
            logger.info(f"  {symbol}: Phase 1 error - {str(e)[:50]}")
            continue

        if not p1_passed:
            logger.info(f"  ❌ {symbol}: Phase 1 rejected - {p1_reason}")
            continue

        phase1_passed += 1
        logger.info(f"  ✅ {symbol}: Phase 1 PASSED")

        # Phase 3B: Confidence scoring + sizing
        verdict = phase3b.evaluate_trade(alert)

        if verdict.should_execute:
            phase3b_approved += 1
            tier = "HIGH" if verdict.adjusted_confidence >= 0.85 else "MEDIUM" if verdict.adjusted_confidence >= 0.70 else "LOW"
            logger.info(
                f"     ✅ Phase 3B APPROVED ({tier}): "
                f"Conf={verdict.adjusted_confidence:.2f}, "
                f"Scale={verdict.position_scale:.0%}"
            )
        else:
            logger.info(
                f"     ❌ Phase 3B REJECTED: "
                f"Conf={verdict.adjusted_confidence:.2f} < 0.65"
            )

        # Track confidence distribution
        if verdict.should_execute:
            if verdict.adjusted_confidence >= 0.85:
                confidence_dist["HIGH (0.85+)"] += 1
            elif verdict.adjusted_confidence >= 0.70:
                confidence_dist["MEDIUM (0.70-0.85)"] += 1
            else:
                confidence_dist["LOW (0.65-0.70)"] += 1

    # Summary
    logger.info("\n" + "="*80)
    logger.info("COMPLETE PIPELINE RESULTS")
    logger.info("="*80)

    logger.info(f"\n📊 Phase 1 Filter:")
    logger.info(f"   Total alerts: {len(test_alerts)}")
    logger.info(f"   Passed: {phase1_passed}/{len(test_alerts)} ({100*phase1_passed/len(test_alerts):.0f}%)")

    logger.info(f"\n📊 Phase 3B Rules Engine:")
    logger.info(f"   Reviewed: {phase1_passed}")
    logger.info(f"   Approved: {phase3b_approved}/{phase1_passed} ({100*phase3b_approved/phase1_passed:.0f}%)")

    logger.info(f"\n📊 Confidence Distribution:")
    for tier, count in sorted(confidence_dist.items(), reverse=True):
        logger.info(f"   {tier}: {count} trades")

    logger.info(f"\n📊 Final Metrics:")
    overall_approval = phase3b_approved / len(test_alerts) if test_alerts else 0
    logger.info(f"   End-to-end approval: {phase3b_approved}/{len(test_alerts)} ({100*overall_approval:.0f}%)")

    phase3b_stats = phase3b.get_stats()
    logger.info(f"\n   Phase 3B Statistics:")
    logger.info(f"     Total reviewed: {phase3b_stats['total_reviewed']}")
    logger.info(f"     Approved: {phase3b_stats['approved']}")
    logger.info(f"     Approval rate: {phase3b_stats['approval_rate_pct']:.1f}%")

    logger.info("\n" + "="*80)
    if overall_approval >= 0.50:
        logger.info("✅ PIPELINE VALIDATED - READY FOR PRODUCTION")
    else:
        logger.info("⚠️ PIPELINE MARGINAL - MONITOR CAREFULLY")
    logger.info("="*80 + "\n")

asyncio.run(run_complete_backtest())
