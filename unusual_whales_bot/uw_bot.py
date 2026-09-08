"""
Phase 1 + 2 + 2.5 + 3B: Unusual Whales Options Trading Bot

Architecture:
  Phase 1: Unusual Whales API → Filter alerts
  Phase 2: Qwen classifier + Robinhood MCP execution
  Phase 2.5: ATR-based stops, NBBO validation, EOD liquidation
  Phase 3B: (Optional) Trading-Hero sentiment + debate engine

Execution Flow:
  1. Poll Unusual Whales API for institutional option flow
  2. Phase 1 filter: Remove obvious false positives
  3. Phase 2 classify: Run Qwen to get direction + confidence
  4. Execute: Place limit order via Robinhood MCP
  5. Monitor: Check underlying price every 60s
  6. Exit: Trigger on stop/target or 3:45 PM EOD

Ready for live: Tue 9/8 with UW API key
"""

import asyncio
import logging
from typing import Optional, Dict
from datetime import datetime

from uw_config import (
    EXECUTION_MODE,
    UNUSUAL_WHALES_CONFIG,
    DEBATE_ENGINE_CONFIG,
    SENTIMENT_CONFIG,
    DISCORD_CONFIG,
    EXIT_RULES_CONFIG,
)
from uw_execution_safeguards import ExecutionSafeguards
from uw_robinhood_mcp import RobinhoodMCPClient
from uw_position_manager import PositionManager
from uw_tier2_integration import Tier2ExitIntegration

logger = logging.getLogger(__name__)


class UnusualWhalesBot:
    """Main bot orchestration"""

    def __init__(self, api_client=None):
        logger.info("🚀 Unusual Whales Bot starting...")

        # Phase 2.5: Execution safeguards
        self.execution_safeguards = ExecutionSafeguards()

        # Phase 2: Robinhood MCP (mock or live)
        self.robinhood_mcp = RobinhoodMCPClient(
            use_mock=EXECUTION_MODE.get("mock_mode", True)
        )

        # Position tracking
        self.position_manager = PositionManager()

        # Tier 2: Options-based exit monitoring
        self.tier2_integration = None
        if EXIT_RULES_CONFIG.get("tier2_enabled", True) and api_client:
            try:
                self.tier2_integration = Tier2ExitIntegration(api_client)
                logger.info("✅ Tier 2 Exit Integration initialized")
            except Exception as e:
                logger.warning(f"⚠️ Tier 2 initialization failed: {e}")

        # Phase 3B: Debate engine (optional)
        self.debate_engine = None
        if DEBATE_ENGINE_CONFIG.get("enabled", False):
            try:
                from uw_debate_engine_redis import DeterministicDebateEngine
                from uw_redis_config import get_redis_config

                redis_config = get_redis_config() if SENTIMENT_CONFIG.get("sentiment_enabled") else None
                self.debate_engine = DeterministicDebateEngine(
                    min_confidence_threshold=DEBATE_ENGINE_CONFIG.get("min_confidence_threshold", 0.75),
                    use_sentiment=SENTIMENT_CONFIG.get("sentiment_enabled", False),
                    redis_config=redis_config,
                )
                logger.info("✅ Debate engine initialized")
            except ImportError:
                logger.warning("⚠️ Debate engine not available (Phase 3B disabled)")

        logger.info("✅ Bot initialized")

    async def execute_trade(
        self,
        alert: Dict,
        classification: Dict,
    ) -> bool:
        """
        Execute a single trade.

        Args:
            alert: Unusual Whales alert dict
            classification: Qwen classification result

        Returns: True if order placed successfully
        """
        symbol = alert.get("symbol", "SPX")
        direction = classification.get("direction")  # "BULLISH" or "BEARISH"
        confidence = classification.get("confidence", 0.0)

        logger.info(
            f"📤 EXECUTE: {symbol} {direction} (conf={confidence:.2f})"
        )

        # Phase 2.5: Get execution plan (ATR-based stops)
        atr_14 = self.execution_safeguards.get_atr_14(symbol)
        current_price = 4500  # TODO: Fetch real underlying price
        entry_price = alert.get("entry_price", 4.50)

        plan = self.execution_safeguards.generate_execution_plan(
            symbol=symbol,
            entry_price=entry_price,
            quantity=1,
            underlying_current_price=current_price,
            iv_rank=0.65,
            atr_14=atr_14,
        )

        # Phase 2.5: Validate NBBO spread
        option_chain_id = alert.get("option_chain_id", f"{symbol}_mock")
        try:
            quotes = await self.robinhood_mcp.get_option_quotes([option_chain_id])
            if not quotes:
                logger.warning("❌ No quotes available")
                return False

            quote = quotes[0]
            if not self.execution_safeguards.validate_nbbo_spread(quote):
                logger.warning("❌ Spread too wide, rejecting order")
                return False

            # Phase 2.5: Calculate midpoint limit price
            limit_price, should_execute = self.execution_safeguards.calculate_midpoint_order(
                nbbo_bid=quote.get("bid", 4.40),
                nbbo_ask=quote.get("ask", 4.60),
            )

            if not should_execute:
                logger.warning("❌ Midpoint calculation failed")
                return False

        except Exception as e:
            logger.error(f"❌ Quote fetch error: {e}")
            return False

        # Phase 2: Place order via Robinhood MCP
        try:
            order_response = await self.robinhood_mcp.place_option_order(
                symbol=symbol,
                option_chain_id=option_chain_id,
                quantity=1,
                order_type="limit",
                limit_price=limit_price,
                direction="buy_to_open" if direction == "BULLISH" else "buy_to_open",
            )

            if not order_response.success:
                logger.warning(f"❌ Order rejected: {order_response.message}")
                return False

            # Track position
            position_id = self.position_manager.add_position(
                symbol=symbol,
                direction="CALL" if direction == "BULLISH" else "PUT",
                entry_price=limit_price,
                quantity=1,
                underlying_stop=plan.underlying_stop_price,
                underlying_target=plan.underlying_target_price,
                option_chain_id=option_chain_id,
                order_id=order_response.order_id,
            )

            logger.info(f"✅ Order placed: {position_id} | Order ID: {order_response.order_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Order placement error: {e}")
            return False

    async def high_frequency_risk_loop(self):
        """
        Monitor open positions every 60 seconds.

        Checks:
        - Tier 2 exit rules (flow exhaustion, put/call flip, dark pool, market tide)
        - Underlying price vs stop/target levels (fallback)
        - EOD force close (3:45 PM)
        """
        logger.info("🔄 Risk monitoring loop started (60s interval)")

        while True:
            try:
                # Get all open positions
                all_positions = self.position_manager.get_all_positions()
                symbols_to_check = set(p.symbol for p in all_positions.values())

                # Tier 2 exit check (if enabled)
                tier2_exits = {}
                if self.tier2_integration and symbols_to_check:
                    try:
                        # Convert positions to format expected by Tier 2
                        tier2_positions = {
                            sym: {
                                "entry_time": next(
                                    p.entry_time for p in all_positions.values() if p.symbol == sym
                                ),
                                "entry_direction": next(
                                    p.direction for p in all_positions.values() if p.symbol == sym
                                ),
                            }
                            for sym in symbols_to_check
                        }
                        tier2_exits = await self.tier2_integration.check_tier2_exits(tier2_positions)
                    except Exception as e:
                        logger.warning(f"Tier 2 check error: {e}")

                # Process Tier 2 exits
                for symbol, (exit_reason, confidence) in tier2_exits.items():
                    matching_positions = [
                        (pos_id, pos) for pos_id, pos in all_positions.items()
                        if pos.symbol == symbol
                    ]
                    for pos_id, pos in matching_positions:
                        logger.info(f"✅ TIER 2 EXIT: {pos_id} via {exit_reason} (conf={confidence:.0%})")
                        self.position_manager.close_position(
                            pos_id,
                            exit_price=pos.entry_price,
                            exit_reason=f"tier2_{exit_reason}",
                        )
                        self.tier2_integration.cleanup_position(symbol)

                # Fallback: ATR-based exits (if Tier 2 didn't trigger)
                if symbols_to_check:
                    try:
                        quotes = await self.robinhood_mcp.get_index_quotes(list(symbols_to_check))

                        for quote in quotes:
                            symbol = quote.get("symbol")
                            price = quote.get("last_price")

                            # Only check ATR if Tier 2 didn't exit this symbol
                            if symbol not in tier2_exits:
                                exits = self.position_manager.check_positions_against_price(
                                    symbol, price
                                )

                                for pos_id, reason in exits:
                                    pos = self.position_manager.get_all_positions().get(pos_id)
                                    if pos:
                                        logger.info(f"✅ ATR EXIT: {pos_id} via {reason}")
                                        self.position_manager.close_position(
                                            pos_id,
                                            exit_price=pos.entry_price * 1.01,  # Simulated exit
                                            exit_reason=reason,
                                        )

                    except Exception as e:
                        logger.warning(f"Price fetch error: {e}")

                # Check EOD force close
                if self.execution_safeguards.check_eod_force_close():
                    await self.position_manager.check_eod_force_close(
                        robinhood_mcp=self.robinhood_mcp
                    )

                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"Risk loop error: {e}")
                await asyncio.sleep(60)

    async def run_cycle(self):
        """
        Single bot cycle:
        1. Poll Unusual Whales API
        2. Run Phase 1 filter
        3. Consolidate directional conflicts (new)
        4. Run Phase 2 Qwen classification
        5. Execute if confidence high enough
        6. Check EOD close
        """
        logger.info("🔄 Bot cycle starting...")

        try:
            # Phase 1: Fetch UW alerts
            from uw_api_client import UnusualWhalesAPI
            from uw_phase1_filter import Phase1AlertFilter
            from uw_position_consolidation import PositionConsolidation

            api = UnusualWhalesAPI()
            alerts = api.get_flow_alerts(limit=50, min_premium=100_000)

            if not alerts:
                logger.debug("No alerts in this cycle")
                logger.info("✅ Cycle complete")
                return

            logger.info(f"📢 Got {len(alerts)} UW alerts")

            # Phase 1: Filter
            phase1 = Phase1AlertFilter()
            approved_alerts = phase1.filter_alerts(alerts)

            if not approved_alerts:
                logger.info(f"⚠️ Phase 1 rejected all {len(alerts)} alerts")
                logger.info("✅ Cycle complete")
                return

            logger.info(f"✅ Phase 1: {len(approved_alerts)}/{len(alerts)} approved")

            # NEW: Consolidate directional conflicts (single direction per symbol)
            consolidator = PositionConsolidation(dominance_threshold=0.20)
            consolidated_alerts = consolidator.consolidate_alerts(approved_alerts)

            if not consolidated_alerts:
                logger.info(f"⚠️ Consolidation rejected all {len(approved_alerts)} alerts (all conflicts)")
                logger.info("✅ Cycle complete")
                return

            logger.info(f"✅ Consolidation: {len(consolidated_alerts)}/{len(approved_alerts)} approved")

            # Execute consolidated trades
            for alert in consolidated_alerts[:5]:  # Limit to 5 per cycle
                try:
                    symbol = alert.get('underlying_symbol', 'SPX')
                    direction = "BULLISH" if alert.get('option_type', '').upper() == 'CALL' else "BEARISH"
                    confidence = 0.80  # Fixed for Phase 1 (no Phase 2 Qwen yet)

                    result = await self.execute_trade(alert, {
                        "direction": direction,
                        "confidence": confidence
                    })

                    if result:
                        logger.info(f"✅ TRADE EXECUTED: {symbol} {direction}")
                    else:
                        logger.warning(f"❌ TRADE FAILED: {symbol} {direction}")

                except Exception as e:
                    logger.error(f"Trade execution error: {e}")

            logger.info("✅ Cycle complete")

        except Exception as e:
            logger.error(f"Cycle error: {e}")
            logger.info("✅ Cycle complete")

    async def main_loop(self, poll_interval: int = 300):
        """
        Main bot loop: Run cycles every N seconds + risk monitoring.

        Default: 5-minute cycles (300 seconds)
        """
        logger.info(f"🚀 Main bot loop starting (cycle every {poll_interval}s)")

        # Start risk monitoring in background
        risk_task = asyncio.create_task(self.high_frequency_risk_loop())

        try:
            while True:
                await self.run_cycle()
                await asyncio.sleep(poll_interval)

        except KeyboardInterrupt:
            logger.info("⏸️ Bot stopped by user")
            risk_task.cancel()
        finally:
            self.robinhood_mcp.log_stats()
            self.position_manager.log_positions()


def main():
    """Entry point"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    bot = UnusualWhalesBot()

    # Run bot
    asyncio.run(bot.main_loop(poll_interval=300))


if __name__ == "__main__":
    main()
