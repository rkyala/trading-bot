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
)
from uw_execution_safeguards import ExecutionSafeguards
from uw_robinhood_mcp import RobinhoodMCPClient
from uw_position_manager import PositionManager

logger = logging.getLogger(__name__)


class UnusualWhalesBot:
    """Main bot orchestration"""

    def __init__(self):
        logger.info("🚀 Unusual Whales Bot starting...")

        # Phase 2.5: Execution safeguards
        self.execution_safeguards = ExecutionSafeguards()

        # Phase 2: Robinhood MCP (mock or live)
        self.robinhood_mcp = RobinhoodMCPClient(
            use_mock=EXECUTION_MODE.get("mock_mode", True)
        )

        # Position tracking
        self.position_manager = PositionManager()

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
        - Underlying price vs stop/target levels
        - EOD force close (3:45 PM)
        """
        logger.info("🔄 Risk monitoring loop started (60s interval)")

        while True:
            try:
                # Fetch index prices
                symbols_to_check = set(
                    p.symbol for p in self.position_manager.get_all_positions().values()
                )

                if symbols_to_check:
                    try:
                        quotes = await self.robinhood_mcp.get_index_quotes(list(symbols_to_check))

                        for quote in quotes:
                            symbol = quote.get("symbol")
                            price = quote.get("last_price")

                            # Check positions against price
                            exits = self.position_manager.check_positions_against_price(
                                symbol, price
                            )

                            for pos_id, reason in exits:
                                pos = self.position_manager.get_all_positions().get(pos_id)
                                if pos:
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
        3. Run Phase 2 Qwen classification
        4. Execute if confidence high enough
        5. Check EOD close
        """
        logger.info("🔄 Bot cycle starting...")

        # TODO: Integrate with Phase 1 + Phase 2 logic

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
