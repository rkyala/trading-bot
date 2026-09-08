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
    TECHNICAL_GATES_CONFIG,
    EXECUTION_SAFEGUARDS_CONFIG,
    INSTRUMENT_CONFIG,
    MAX_OPEN_POSITIONS,
    MAX_DAILY_LOSS_PCT,
)
from uw_execution_safeguards import ExecutionSafeguards
from uw_robinhood_mcp import RobinhoodMCPClient
from uw_position_manager import PositionManager
from uw_tier2_integration import Tier2ExitIntegration
from uw_market_data import get_market_data

logger = logging.getLogger(__name__)


class UnusualWhalesBot:
    """Main bot orchestration"""

    def __init__(self, api_client=None):
        logger.info("🚀 Unusual Whales Bot starting...")

        # Phase 2.5: Execution safeguards (spread threshold from config so
        # Phase 1 and execution cannot disagree — see uw_config alignment note)
        self.execution_safeguards = ExecutionSafeguards(
            max_bid_ask_spread_pct=EXECUTION_SAFEGUARDS_CONFIG.get("max_bid_ask_spread_pct", 0.15)
        )

        # ---------------------------------------------------------------
        # BLOCKER FIX #4: paper_trading is now actually routed. Previously
        # this flag was read nowhere, so `mock_mode: False` fell through to a
        # stub LIVE path where every order returned success=False.
        # ---------------------------------------------------------------
        self.robinhood_mcp = RobinhoodMCPClient(
            use_mock=EXECUTION_MODE.get("mock_mode", False),
            paper_trading=EXECUTION_MODE.get("paper_trading", True),
        )

        # Position tracking
        self.position_manager = PositionManager()

        # Circuit-breaker state (BLOCKER FIX #9)
        self.halted = False
        self.session_realized_pnl = 0.0
        self.session_start_equity = float(EXECUTION_MODE.get("session_equity", 25000.0))

        # ---------------------------------------------------------------
        # BLOCKER FIX #6: Tier 2 required an api_client that main() never
        # passed, so all four exit rules silently never initialized. The bot
        # now builds its own client when one is not supplied.
        # ---------------------------------------------------------------
        if api_client is None:
            try:
                from uw_api_client import UnusualWhalesAPI
                api_client = UnusualWhalesAPI()
            except Exception as e:
                logger.warning(f"⚠️ Could not construct UW API client: {e}")

        self.api_client = api_client

        self.tier2_integration = None
        if EXIT_RULES_CONFIG.get("tier2_enabled", True) and api_client:
            try:
                self.tier2_integration = Tier2ExitIntegration(api_client)
                logger.info("✅ Tier 2 Exit Integration initialized")
            except Exception as e:
                logger.warning(f"⚠️ Tier 2 initialization failed: {e}")
        else:
            logger.warning("⚠️ Tier 2 exit monitoring is NOT active")

        # ---------------------------------------------------------------
        # BLOCKER FIX #7: wire Technical Gates 9-11. They were fully built
        # but imported nowhere, and would have crashed if they had been
        # (they call get_historical_candles / get_intraday_ticks, which did
        # not exist on any client until uw_market_data.py was added).
        # ---------------------------------------------------------------
        self.technical_gates = None
        if TECHNICAL_GATES_CONFIG.get("enabled", True):
            try:
                from uw_technical_gates import TechnicalGates
                from uw_market_data import get_async_market_data
                self.technical_gates = TechnicalGates(get_async_market_data())
                logger.info("✅ Technical Gates 9-11 initialized")
            except Exception as e:
                logger.warning(f"⚠️ Technical gates unavailable: {e}")

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

    @staticmethod
    def classify_alert(alert: Dict) -> Optional[Dict]:
        """
        Derive directional intent from the alert's own UW tags.

        BLOCKER FIX: the previous mapping was `CALL -> BULLISH` from
        option_type alone. That is wrong for seller-initiated flow: a CALL hit
        on the BID is someone SELLING calls — bearish exposure — and UW tags it
        `["bid_side", "bearish"]`. Roughly 40% of live alerts are bid_side, so
        that mapping inverted a large share of signals.

        Policy: follow the BUYERS. Only `ask_side` flow is actionable, because
        buying the same contract expresses the same view as the institution
        that initiated it. bid_side / mid_side / no_side are skipped.

        Returns None when the alert is not actionable.
        """
        tags = {str(t).lower() for t in (alert.get("tags") or [])}
        option_type = str(alert.get("option_type", "")).upper()

        if "ask_side" not in tags:
            return None  # seller-initiated or unsided: not a follow-the-buyer signal

        if "bullish" in tags:
            bias = "BULLISH"
        elif "bearish" in tags:
            bias = "BEARISH"
        else:
            return None  # neutral

        direction = "CALL" if option_type == "CALL" else "PUT"

        # Buying a call should be bullish and buying a put bearish. If the tag
        # disagrees with the contract, the trade would not express the view.
        expected = "BULLISH" if direction == "CALL" else "BEARISH"
        if bias != expected:
            return None

        return {"direction": direction, "bias": bias}

    async def execute_trade(
        self,
        alert: Dict,
        classification: Dict,
    ) -> bool:
        """
        Execute a single trade.

        Returns: True if order placed successfully
        """
        # ---------------------------------------------------------------
        # BLOCKER FIX #1: read `underlying_symbol`. The old code read
        # alert.get("symbol", "SPX") — a key the UW API never returns — so
        # EVERY order defaulted to SPX regardless of the actual signal.
        # ---------------------------------------------------------------
        symbol = alert.get("underlying_symbol") or alert.get("symbol")
        if not symbol:
            logger.error("❌ Alert has no underlying symbol; skipping")
            return False

        direction = classification.get("direction", "CALL")  # "CALL" | "PUT"
        confidence = float(classification.get("confidence", 0.0))
        is_bearish = str(direction).upper().startswith("P")

        if self.halted:
            logger.warning("🛑 Trading halted by circuit breaker; skipping")
            return False

        # ---------------------------------------------------------------
        # EQUITY MODE: long-only.
        # Bearish option flow on a name we HOLD is an exit signal. Bearish
        # flow on a name we do not hold is skipped rather than shorted —
        # shorting needs margin and is restricted on retail Robinhood.
        # ---------------------------------------------------------------
        if is_bearish and not INSTRUMENT_CONFIG.get("allow_short", False):
            if self.position_manager.has_open_position(symbol):
                logger.info(f"📉 {symbol}: bearish flow on a held name → exiting")
                return await self._exit_symbol(symbol, "bearish_flow")
            logger.info(f"⏭️  {symbol}: bearish flow, not held, shorting disabled → skip")
            return False

        # ---------------------------------------------------------------
        # BLOCKER FIX #9: enforce risk limits that were defined in config
        # but referenced nowhere in the execution path.
        # ---------------------------------------------------------------
        open_count = self.position_manager.total_open_positions()
        if open_count >= MAX_OPEN_POSITIONS:
            logger.warning(f"🛑 Position cap reached ({open_count}/{MAX_OPEN_POSITIONS}); skipping {symbol}")
            return False

        # ---------------------------------------------------------------
        # BLOCKER FIX #10: do not re-enter a symbol we already hold.
        # ---------------------------------------------------------------
        if self.position_manager.has_open_position(symbol):
            logger.info(f"⏭️  {symbol}: position already open, skipping duplicate entry")
            return False

        # ---------------------------------------------------------------
        # BLOCKER FIX #2: use the REAL underlying price. The alert carries
        # `underlying_price`; fall back to live market data. Never 4500.
        # ---------------------------------------------------------------
        try:
            underlying_price = float(alert.get("underlying_price") or 0)
        except (TypeError, ValueError):
            underlying_price = 0.0

        if underlying_price <= 0:
            underlying_price = get_market_data().get_underlying_price(symbol) or 0.0

        if underlying_price <= 0:
            logger.warning(f"❌ {symbol}: no underlying price available; skipping (no placeholder)")
            return False

        # ---------------------------------------------------------------
        # EQUITY MODE: we trade the SHARES, so the entry price is the stock
        # price. The option NBBO on the alert describes the contract the
        # institution bought — it is signal metadata, not our fill price.
        # ---------------------------------------------------------------
        limit_price = underlying_price

        # ---------------------------------------------------------------
        # BLOCKER FIX #3: direction-aware execution plan (real ATR).
        # ---------------------------------------------------------------
        plan = self.execution_safeguards.generate_execution_plan(
            symbol=symbol,
            entry_price=limit_price,
            quantity=1,
            underlying_current_price=underlying_price,
            atr_14=None,
            direction=direction,
        )
        if plan is None:
            logger.warning(f"❌ {symbol}: could not build a safe execution plan; skipping")
            return False

        # ---------------------------------------------------------------
        # Dollar-notional sizing, scaled by confidence. Shares are derived
        # from the live price rather than a fixed contract count, so a $19
        # stock and a $1,700 stock take comparable risk.
        # ---------------------------------------------------------------
        conf_mult = self._size_multiplier(confidence)
        if conf_mult <= 0:
            logger.info(f"⏭️  {symbol}: confidence {confidence:.0%} below trade threshold")
            return False

        target_dollars = INSTRUMENT_CONFIG.get("position_dollars", 500.0) * conf_mult
        target_dollars = min(target_dollars, INSTRUMENT_CONFIG.get("max_dollars_per_symbol", 1500.0))
        quantity = int(target_dollars // limit_price)

        if quantity < 1:
            logger.info(
                f"⏭️  {symbol}: ${target_dollars:.0f} buys 0 shares at ${limit_price:.2f}; skipping"
            )
            return False

        logger.info(
            f"📤 EXECUTE: {symbol} BUY {quantity}sh @ ${limit_price:.2f} "
            f"(${quantity * limit_price:,.0f} notional, conf {confidence:.0%}) "
            f"[signal: {alert.get('option_chain_id', 'n/a')}]"
        )

        try:
            order_response = await self.robinhood_mcp.place_equity_order(
                symbol=symbol,
                quantity=quantity,
                side="buy",
                order_type="limit",
                limit_price=limit_price,
            )

            if not order_response.success:
                logger.warning(f"❌ Order rejected: {order_response.message}")
                return False

            fill = order_response.fill_price or limit_price

            position_id = self.position_manager.add_position(
                symbol=symbol,
                direction=direction,
                entry_price=fill,
                quantity=quantity,
                underlying_stop=plan.underlying_stop_price,
                underlying_target=plan.underlying_target_price,
                option_chain_id=alert.get("option_chain_id", ""),  # signal provenance
                order_id=order_response.order_id,
                entry_underlying=underlying_price,
                delta=self._safe_float(alert.get("delta"), 0.5),
                gamma=self._safe_float(alert.get("gamma"), 0.0),
                simulated=order_response.simulated,
                instrument="equity",
            )

            logger.info(f"✅ Order placed: {position_id} | {order_response.message}")
            return True

        except Exception as e:
            logger.error(f"❌ Order placement error: {e}")
            return False

    async def _exit_symbol(self, symbol: str, reason: str) -> bool:
        """
        Close every open position in `symbol` at the live share price.

        Used when bearish option flow arrives on a name we are long — in a
        long-only book that is an exit signal rather than a short entry.
        """
        closed_any = False
        for pos_id, pos in list(self.position_manager.get_all_positions().items()):
            if pos.symbol != symbol:
                continue
            exit_price, exit_spot = await self.position_manager.mark_position(
                pos, self.robinhood_mcp
            )
            try:
                await self.robinhood_mcp.place_equity_order(
                    symbol=symbol, quantity=pos.quantity, side="sell",
                    order_type="limit", limit_price=exit_price,
                )
            except Exception as e:
                logger.error(f"❌ {symbol}: exit order failed ({e}); keeping position open")
                continue

            closed = self.position_manager.close_position(
                pos_id, exit_price=exit_price, exit_reason=reason,
                exit_underlying=exit_spot,
            )
            self._record_pnl(closed)
            closed_any = True
        return closed_any

    @staticmethod
    def _safe_float(value, default: float) -> float:
        try:
            f = float(value)
            return f if f == f else default  # reject NaN
        except (TypeError, ValueError):
            return default

    def _record_pnl(self, closed_position) -> None:
        """
        Track realized P&L and trip the daily-loss circuit breaker.

        BLOCKER FIX #9: MAX_DAILY_LOSS_PCT was defined in config and never
        referenced, so there was no drawdown halt of any kind.
        """
        if not closed_position or closed_position.exit_price is None:
            return

        mult = closed_position.multiplier
        entry_cost = closed_position.entry_price * closed_position.quantity * mult
        exit_value = closed_position.exit_price * closed_position.quantity * mult
        self.session_realized_pnl += (exit_value - entry_cost)

        if self.session_start_equity > 0:
            drawdown_pct = (self.session_realized_pnl / self.session_start_equity) * 100
            if drawdown_pct <= MAX_DAILY_LOSS_PCT:
                self.halted = True
                logger.error(
                    f"🛑 CIRCUIT BREAKER TRIPPED: session P&L "
                    f"${self.session_realized_pnl:,.0f} ({drawdown_pct:.2f}%) "
                    f"breached {MAX_DAILY_LOSS_PCT}% limit. No new entries."
                )

    @staticmethod
    def _size_multiplier(confidence: float) -> float:
        """
        Scale position notional by confidence (0 = do not trade).

        Applied to INSTRUMENT_CONFIG["position_dollars"], so sizing is
        dollar-based rather than a fixed share/contract count — a $19 stock
        and a $1,700 stock then carry comparable risk.
        """
        if confidence < TECHNICAL_GATES_CONFIG.get("min_confidence_to_trade", 0.50):
            return 0.0
        if confidence < 0.65:
            return 0.5
        if confidence < 0.85:
            return 1.0
        return 1.5

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
                        # BLOCKER FIX #8: mark to the real underlying instead of
                        # booking exit_price = entry_price (always exactly $0 P&L,
                        # which forced a 0% win rate on every Tier 2 exit).
                        exit_price, exit_spot = await self.position_manager.mark_position(
                            pos, self.robinhood_mcp
                        )
                        logger.info(f"✅ TIER 2 EXIT: {pos_id} via {exit_reason} (conf={confidence:.0%})")
                        closed = self.position_manager.close_position(
                            pos_id,
                            exit_price=exit_price,
                            exit_reason=f"tier2_{exit_reason}",
                            exit_underlying=exit_spot,
                        )
                        self._record_pnl(closed)
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
                                        # BLOCKER FIX #8: was `entry_price * 1.01`,
                                        # i.e. every ATR exit booked a guaranteed
                                        # +1% win regardless of what price did.
                                        exit_price, exit_spot = await self.position_manager.mark_position(
                                            pos, self.robinhood_mcp
                                        )
                                        logger.info(f"✅ ATR EXIT: {pos_id} via {reason}")
                                        closed = self.position_manager.close_position(
                                            pos_id,
                                            exit_price=exit_price,
                                            exit_reason=reason,
                                            exit_underlying=exit_spot,
                                        )
                                        self._record_pnl(closed)

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
            from uw_contract_filter import ContractFilter
            from uw_config import CONTRACT_FILTER_CONFIG, ALERTS_PER_CYCLE

            api = self.api_client or UnusualWhalesAPI()
            alerts = api.get_flow_alerts(limit=ALERTS_PER_CYCLE, min_premium=100_000)

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

            # ---------------------------------------------------------------
            # BLOCKER FIX #11: screen the CONTRACT, not just the signal.
            # Runs before consolidation so that consolidation picks the best
            # *tradeable* contract per symbol rather than the highest-premium
            # one (which is systematically a deep-ITM LEAP).
            # ---------------------------------------------------------------
            if CONTRACT_FILTER_CONFIG.get("enabled", True):
                cf_kwargs = {k: v for k, v in CONTRACT_FILTER_CONFIG.items() if k != "enabled"}
                contract_filter = ContractFilter(**cf_kwargs)
                md = get_market_data()
                approved_alerts = contract_filter.filter_alerts(
                    approved_alerts, atr_lookup=lambda s: md.get_atr(s) if s else None
                )
                contract_filter.log_stats()

                if not approved_alerts:
                    logger.info("⚠️ No tradeable contracts this cycle (all LEAPs/wide spreads)")
                    logger.info("✅ Cycle complete")
                    return

                logger.info(f"✅ Contract filter: {len(approved_alerts)} tradeable")

            # NEW: Consolidate directional conflicts (single direction per symbol)
            consolidator = PositionConsolidation(dominance_threshold=0.20)
            consolidated_alerts = consolidator.consolidate_alerts(approved_alerts)

            if not consolidated_alerts:
                logger.info(f"⚠️ Consolidation rejected all {len(approved_alerts)} alerts (all conflicts)")
                logger.info("✅ Cycle complete")
                return

            logger.info(f"✅ Consolidation: {len(consolidated_alerts)}/{len(approved_alerts)} approved")

            # ---------------------------------------------------------------
            # Direction classification from UW tags (follow-the-buyer policy).
            # Replaces the blind `CALL -> BULLISH` mapping.
            # ---------------------------------------------------------------
            actionable = []
            for alert in consolidated_alerts:
                cls = self.classify_alert(alert)
                if cls:
                    actionable.append((alert, cls))

            if not actionable:
                logger.info("⚠️ No buyer-initiated (ask_side) signals this cycle")
                logger.info("✅ Cycle complete")
                return

            logger.info(f"✅ Actionable (ask_side): {len(actionable)}/{len(consolidated_alerts)}")

            # ---------------------------------------------------------------
            # BLOCKER FIX #7: technical confirmation now actually runs and
            # produces the confidence that drives position sizing (previously
            # confidence was the constant 0.80).
            # ---------------------------------------------------------------
            executed = 0
            for alert, cls in actionable:
                if executed >= 5:  # per-cycle cap
                    break
                try:
                    symbol = alert.get("underlying_symbol")
                    direction = cls["direction"]
                    confidence = 0.75  # Tier 2 baseline

                    if self.technical_gates:
                        try:
                            spot = self._safe_float(alert.get("underlying_price"), 0.0)
                            if spot > 0:
                                confidence = await self.technical_gates.calculate_technical_confidence(
                                    symbol, direction, spot
                                )
                        except Exception as e:
                            logger.warning(f"Technical gates failed for {symbol}: {e}; using baseline")

                    result = await self.execute_trade(
                        alert, {"direction": direction, "confidence": confidence}
                    )

                    if result:
                        executed += 1
                        logger.info(f"✅ TRADE EXECUTED: {symbol} {direction} (conf {confidence:.0%})")

                except Exception as e:
                    logger.error(f"Trade execution error: {e}")

            logger.info(f"✅ Cycle complete ({executed} executed, {self.position_manager.total_open_positions()} open)")

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

    from uw_config import validate_config, get_execution_mode_name
    validate_config()

    # BLOCKER FIX #6: pass the API client so Tier 2 exit monitoring actually
    # initializes. main() previously called UnusualWhalesBot() with no client,
    # which silently disabled all four Tier 2 exit rules in production.
    from uw_api_client import UnusualWhalesAPI
    api_client = UnusualWhalesAPI()

    bot = UnusualWhalesBot(api_client=api_client)

    logger.info(f"▶️  Execution mode: {get_execution_mode_name()}")
    logger.info(f"▶️  Tier 2 exits: {'ACTIVE' if bot.tier2_integration else 'INACTIVE'}")
    logger.info(f"▶️  Technical gates: {'ACTIVE' if bot.technical_gates else 'INACTIVE'}")

    asyncio.run(bot.main_loop(poll_interval=300))


if __name__ == "__main__":
    main()
