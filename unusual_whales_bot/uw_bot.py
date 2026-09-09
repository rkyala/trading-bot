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
    CAPACITY_CONFIG,
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

        # Build the UW client early: the watchlist needs it at construction.
        if api_client is None:
            try:
                from uw_api_client import UnusualWhalesAPI
                api_client = UnusualWhalesAPI()
            except Exception as e:
                logger.warning(f"⚠️ Could not construct UW API client: {e}")
        api_client_for_watchlist = api_client

        # Position tracking
        self.position_manager = PositionManager()

        # Whale watchlist — follows large blocks via open interest from open
        # to close. Detection happens BEFORE the contract filter, because the
        # blocks most worth following (e.g. GOOGL 73-DTE) are exactly the ones
        # that filter rejects for trading.
        from uw_whale_watchlist import WhaleWatchlist
        self.watchlist = WhaleWatchlist(api_client=api_client_for_watchlist)
        self._watchlist_polled_on = None

        # Training-data capture. Features cannot be recovered retroactively,
        # so this runs from day one even though no model consumes it yet.
        from uw_feature_logger import FeatureLogger
        self.feature_logger = FeatureLogger()

        # Exposure conflict guard (inverse ETFs + concentration)
        from uw_exposure_guard import ExposureGuard
        self.exposure_guard = ExposureGuard()
        self._position_sectors: Dict[str, str] = {}

        # Surface conflicts that already exist in a restored book, rather than
        # letting them sit quietly until someone reads the P&L.
        existing = ExposureGuard.audit_book(list(self.position_manager.open_symbols()))
        for problem in existing:
            logger.warning(f"🛡️  PRE-EXISTING EXPOSURE CONFLICT: {problem}")

        # Per-position max favourable/adverse excursion, in ATR units
        self._excursions: Dict[str, Dict] = {}

        # Bearish signals dropped by the long-only rule, digested per cycle
        self._skipped_bearish: list = []

        # GEX zone-crossing alerter; built lazily on first cycle
        self._gex_alerts = None

        # Rotations performed today (bounded to prevent churn)
        self._rotations_today = 0

        # Why the most recent entry was declined (captured for training data)
        self._last_reject_reason: Optional[str] = None

        # Circuit-breaker state (BLOCKER FIX #9)
        self.halted = False
        self.session_realized_pnl = 0.0
        self.session_start_equity = float(EXECUTION_MODE.get("session_equity", 25000.0))

        # ---------------------------------------------------------------
        # BLOCKER FIX #6: Tier 2 required an api_client that main() never
        # passed, so all four exit rules silently never initialized. The bot
        # now builds its own client when one is not supplied.
        # ---------------------------------------------------------------
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
            self._last_reject_reason = "no_symbol"
            logger.error("❌ Alert has no underlying symbol; skipping")
            return False

        direction = classification.get("direction", "CALL")  # "CALL" | "PUT"
        confidence = float(classification.get("confidence", 0.0))
        is_bearish = str(direction).upper().startswith("P")

        if self.halted:
            self._last_reject_reason = "circuit_breaker"
            logger.warning("🛑 Trading halted by circuit breaker; skipping")
            return False

        # ---------------------------------------------------------------
        # ENTRY WINDOW. On Sep 8 the bot opened ORCL and TSLA at 15:46 ET —
        # inside its own EOD liquidation pass — and closed them 20 seconds
        # later. The EOD check force-closed positions but never gated entries.
        # ---------------------------------------------------------------
        window_open, window_reason = self.execution_safeguards.entry_window_open()
        if not window_open:
            self._last_reject_reason = "entry_window_closed"
            logger.info(f"⏰ {symbol}: no new entries — {window_reason}")
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
            self._last_reject_reason = "bearish_no_short"
            logger.info(f"⏭️  {symbol}: bearish flow, not held, shorting disabled → skip")
            # Collected here, posted as one digest at cycle end so three
            # skips in a cycle do not become three separate alerts.
            # NB: `confidence` is NOT in scope here — the technical gates run
            # in the caller, so execute_trade only sees (alert, classification).
            # Record the premium, which is in scope and is what makes the
            # signal notable in the first place.
            try:
                if not hasattr(self, "_skipped_bearish"):
                    self._skipped_bearish = []
                self._skipped_bearish.append({
                    "symbol": symbol,
                    "direction": str(alert.get("option_type", "PUT")).upper(),
                    "premium": float(alert.get("premium") or 0.0),
                })
            except Exception:
                pass
            return False

        # ===============================================================
        # ELIGIBILITY CHECKS FIRST, CAPACITY LAST.
        #
        # Rotation closes a real position, so it must never run before we
        # know the candidate is actually takeable. Running it first caused a
        # live incident: FSLR (73%) was liquidated "to make room" for TSLA,
        # and TSLA was then rejected on the very next line as a duplicate —
        # a position destroyed for nothing, book down to 9.
        #
        # Everything that can decline a trade for free is therefore
        # evaluated before anything that costs money.
        # ===============================================================

        # ---------------------------------------------------------------
        # BLOCKER FIX #10: do not re-enter a symbol we already hold.
        # ---------------------------------------------------------------
        if self.position_manager.has_open_position(symbol):
            self._last_reject_reason = "already_held"
            logger.info(f"⏭️  {symbol}: position already open, skipping duplicate entry")
            return False

        # ---------------------------------------------------------------
        # EXPOSURE CONFLICT GUARD
        # The book was found holding TQQQ (3x long Nasdaq) and SQQQ (3x short
        # Nasdaq) simultaneously — self-cancelling, and both decaying. Neither
        # consolidation (same-ticker call/put) nor the dedup check (same
        # ticker) can see a conflict across DIFFERENT tickers.
        # ---------------------------------------------------------------
        held = list(self.position_manager.open_symbols())
        allowed, reason = self.exposure_guard.check(
            symbol,
            held,
            candidate_sector=alert.get("sector"),
            held_sectors=[self._position_sectors.get(s) for s in held],
        )
        if not allowed:
            self._last_reject_reason = f"exposure:{reason.split(':')[0]}"
            logger.warning(f"🛡️  {symbol}: {reason}")
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
            self._last_reject_reason = "no_price"
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
            self._last_reject_reason = "no_execution_plan"
            logger.warning(f"❌ {symbol}: could not build a safe execution plan; skipping")
            return False

        # ---------------------------------------------------------------
        # Dollar-notional sizing, scaled by confidence. Shares are derived
        # from the live price rather than a fixed contract count, so a $19
        # stock and a $1,700 stock take comparable risk.
        # ---------------------------------------------------------------
        conf_mult = self._size_multiplier(confidence)
        if conf_mult <= 0:
            self._last_reject_reason = "low_confidence"
            logger.info(f"⏭️  {symbol}: confidence {confidence:.0%} below trade threshold")
            return False

        target_dollars = INSTRUMENT_CONFIG.get("position_dollars", 500.0) * conf_mult
        target_dollars = min(target_dollars, INSTRUMENT_CONFIG.get("max_dollars_per_symbol", 1500.0))
        quantity = int(target_dollars // limit_price)

        if quantity < 1:
            self._last_reject_reason = "size_rounds_to_zero"
            logger.info(
                f"⏭️  {symbol}: ${target_dollars:.0f} buys 0 shares at ${limit_price:.2f}; skipping"
            )
            return False

        # ---------------------------------------------------------------
        # CAPACITY — evaluated LAST, once the trade is fully qualified.
        # Rotation liquidates a real holding, so it only runs at the point
        # where the order is otherwise certain to be placed.
        # ---------------------------------------------------------------
        open_count = self.position_manager.total_open_positions()
        if open_count >= MAX_OPEN_POSITIONS:
            rotated = await self._try_rotate_for(symbol, confidence)
            if not rotated:
                self._last_reject_reason = "position_cap"
                logger.warning(
                    f"🛑 Position cap reached ({open_count}/{MAX_OPEN_POSITIONS}); "
                    f"skipping {symbol} (conf {confidence:.0%})"
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
                candidate_id=classification.get("candidate_id", ""),
                entry_confidence=confidence,
            )

            # Remember the sector for concentration checks on later entries.
            if alert.get("sector"):
                self._position_sectors[symbol] = alert["sector"]

            logger.info(f"✅ Order placed: {position_id} | {order_response.message}")
            return True

        except Exception as e:
            logger.error(f"❌ Order placement error: {e}")
            return False

    async def _poll_watchlist(self) -> None:
        """
        Refresh open interest on tracked whale blocks, once per day.

        OI only updates overnight, so polling per cycle would burn API calls
        for no new information.
        """
        from uw_execution_safeguards import now_eastern
        today = now_eastern().date()
        if self._watchlist_polled_on == today:
            return
        # Poll after the open, once OI for the prior session has settled.
        if now_eastern().time() < __import__("datetime").time(10, 0):
            return

        self._watchlist_polled_on = today
        events = await asyncio.to_thread(self.watchlist.poll)
        for ev in events:
            self._alert_watchlist_event(ev["event"], ev["position"])
        if self.watchlist.active():
            logger.info(f"👁️  Watchlist: {len(self.watchlist.active())} positions tracked")

    def _alert_watchlist_event(self, event: str, pos) -> None:
        """Notify on a tracked whale position changing state."""
        import os
        headline = {
            "CONFIRMED": "🐋 WHALE POSITION CONFIRMED",
            "UNWINDING": "⚠️ WHALE POSITION UNWINDING",
            "CLOSED":    "🚪 WHALE POSITION CLOSED",
            "FAILED":    "👻 BLOCK DID NOT OPEN A POSITION",
            "EXPIRED":   "⌛ TRACKED CONTRACT EXPIRED",
        }.get(event, event)

        detail = (
            f"**{pos.symbol} ${pos.strike:.0f} {pos.option_type}** exp {pos.expiry}\n"
            f"Block: {pos.block_size:,.0f} contracts, ${pos.block_premium/1e6:.2f}M "
            f"({pos.side}, {pos.bias})\n"
            f"OI: baseline {pos.baseline_oi:,.0f} → peak {pos.peak_oi:,.0f} → "
            f"now {pos.current_oi:,.0f} ({pos.pct_off_peak:+.1f}% off peak)\n"
            f"Block was {pos.oi_concentration:.0%} of peak OI"
        )
        logger.warning(f"{headline}: {pos.symbol} {pos.strike:.0f}{pos.option_type[0]}")

        wh = os.getenv("DISCORD_WEBHOOK_URL")
        if not wh:
            return
        try:
            import requests
            colour = {"CONFIRMED": 3066993, "UNWINDING": 16776960,
                      "CLOSED": 15158332, "FAILED": 9807270}.get(event, 10181046)
            note = ("Open interest is aggregate — a fall means somebody closed, "
                    "not provably this holder. Concentration above shows how "
                    "strong that inference is.")
            requests.post(wh, json={"embeds": [{
                "title": headline,
                "description": detail,
                "color": colour,
                "timestamp": datetime.utcnow().isoformat(),
                "fields": [{"name": "Caveat", "value": note, "inline": False}],
                "footer": {"text": "Unusual Whales bot · whale watchlist"},
            # TLS verification stays ON: a Discord webhook URL is a credential
            # (anyone holding it can post as this bot), so verify=False would
            # expose it to interception for no benefit.
            }]}, timeout=10)
        except Exception as e:
            logger.debug(f"watchlist alert failed: {e}")

    def _log_shadow_exit(self, pos, reason, confidence, mark, spot, ret_pct) -> None:
        """Record a Tier 2 signal that was observed but not acted on."""
        import json
        try:
            with open("tier2_shadow.jsonl", "a") as fh:
                fh.write(json.dumps({
                    "logged_at": datetime.now().isoformat(),
                    "symbol": pos.symbol,
                    "reason": reason,
                    "confidence": round(float(confidence), 4),
                    "entry_price": pos.entry_price,
                    "mark_at_signal": mark,
                    "return_at_signal_pct": round(ret_pct, 4),
                    "entry_time": pos.entry_time,
                    "candidate_id": getattr(pos, "candidate_id", ""),
                }) + "\n")
        except Exception as e:
            logger.debug(f"shadow log failed: {e}")

    async def _track_excursions(self) -> None:
        """
        Sample every open position and record how far it has travelled toward
        its stop and target, in ATR units.

        WHY: no stop or target fired on Sep 8 — every position closed on the
        EOD bell — so the exit logic is unverified and waiting for a trigger
        could take weeks. Excursion turns a rare event into a daily
        measurement: if positions never travel beyond ~0.3 ATR while stops sit
        at 1.5 ATR, the barriers are unreachable at this holding period and the
        ATR multiples need recalibrating (or the hold lengthening).

        MFE = max favourable excursion, MAE = max adverse excursion.
        """
        positions = self.position_manager.get_all_positions()
        if not positions:
            return

        for pos_id, pos in positions.items():
            spot = get_market_data().get_underlying_price(pos.symbol)
            if not spot or not pos.entry_underlying:
                continue

            # ATR implied by the plan: stop sits 1.5 ATR from entry.
            atr = abs(pos.entry_underlying - pos.underlying_stop) / 1.5
            if atr <= 0:
                continue

            is_put = str(pos.direction).upper().startswith("P")
            move = (pos.entry_underlying - spot) if is_put else (spot - pos.entry_underlying)
            excursion_atr = move / atr

            st = self._excursions.setdefault(pos_id, {"mfe_atr": 0.0, "mae_atr": 0.0, "samples": 0})
            st["mfe_atr"] = max(st["mfe_atr"], excursion_atr)
            st["mae_atr"] = min(st["mae_atr"], excursion_atr)
            st["samples"] += 1
            st["atr"] = atr
            st["symbol"] = pos.symbol
            st["stop_distance_atr"] = 1.5
            st["target_distance_atr"] = 2.5
            # How much of the way to each barrier the position actually got
            st["pct_to_target"] = round(max(st["mfe_atr"], 0) / 2.5 * 100, 1)
            st["pct_to_stop"] = round(abs(min(st["mae_atr"], 0)) / 1.5 * 100, 1)

    def _flush_excursion(self, pos_id: str, pos) -> None:
        """Persist a position's excursion record when it closes."""
        import json
        st = self._excursions.pop(pos_id, None)
        if not st:
            return
        try:
            with open("excursions.jsonl", "a") as fh:
                fh.write(json.dumps({
                    "closed_at": datetime.now().isoformat(),
                    "position_id": pos_id,
                    "symbol": pos.symbol,
                    "direction": pos.direction,
                    "exit_reason": pos.exit_reason,
                    "candidate_id": getattr(pos, "candidate_id", ""),
                    **st,
                }) + "\n")
        except Exception as e:
            logger.debug(f"excursion log failed: {e}")

    async def _try_rotate_for(self, symbol: str, confidence: float) -> bool:
        """
        Free a slot by closing a clearly weaker holding.

        Returns True only if a rotation actually happened. Deliberately
        conservative — every swap pays the spread twice, so this fires only on
        unambiguous upgrades:

          - candidate must beat the weakest holding by `rotation_margin`
          - the holding must have been open at least `min_hold_minutes`
            (no thrashing fresh entries)
          - positions currently up more than `protect_winners_pct` are never
            rotated out; dumping a working trade to chase a marginally better
            signal is precisely the behaviour that loses money
          - capped at `max_rotations_per_day`
        """
        cfg = CAPACITY_CONFIG
        if not cfg.get("quality_rotation_enabled", True):
            return False

        if self._rotations_today >= cfg.get("max_rotations_per_day", 6):
            logger.info(f"🔁 {symbol}: daily rotation limit reached; not rotating")
            return False

        margin = cfg.get("rotation_margin", 0.15)
        min_hold = cfg.get("min_hold_minutes", 30)
        protect = cfg.get("protect_winners_pct", 1.0)

        candidates = []
        for pos_id, pos in self.position_manager.get_all_positions().items():
            # ---------------------------------------------------------------
            # UNKNOWN IS NOT WORST.
            # Positions opened before entry_confidence existed load with the
            # dataclass default 0.0. Treating that as "lowest quality" made
            # every legacy position maximally rotatable, and the first live
            # run promptly closed ORCL (96%), CRWV (100%) and NVDA (96%) to
            # buy BE (54%), SKHY (60%) and TQQQ (70%) — strictly worse.
            # A position whose quality is unrecorded cannot be judged, so it
            # is never a rotation candidate.
            # ---------------------------------------------------------------
            if not pos.entry_confidence or pos.entry_confidence <= 0.0:
                continue

            # Age gate
            try:
                age_min = (datetime.now() - datetime.fromisoformat(pos.entry_time)).total_seconds() / 60.0
            except Exception:
                age_min = 9999
            if age_min < min_hold:
                continue

            # Never rotate out a position that is currently working
            mark, spot = await self.position_manager.mark_position(pos, self.robinhood_mcp)
            ret_pct = ((mark - pos.entry_price) / pos.entry_price * 100) if pos.entry_price else 0.0
            if ret_pct > protect:
                continue

            candidates.append((pos_id, pos, mark, spot, ret_pct))

        if not candidates:
            return False

        pos_id, pos, mark, spot, ret_pct = min(candidates, key=lambda x: x[1].entry_confidence)

        if confidence < pos.entry_confidence + margin:
            logger.info(
                f"🔁 {symbol} ({confidence:.0%}) does not beat weakest holding "
                f"{pos.symbol} ({pos.entry_confidence:.0%}) by {margin:.0%}; no rotation"
            )
            return False

        # Execute the rotation
        try:
            await self.robinhood_mcp.place_equity_order(
                symbol=pos.symbol, quantity=pos.quantity, side="sell",
                order_type="limit", limit_price=mark,
            )
        except Exception as e:
            logger.error(f"❌ rotation exit failed for {pos.symbol}: {e}; keeping it")
            return False

        closed = self.position_manager.close_position(
            pos_id, exit_price=mark, exit_reason="rotated_for_better_signal",
            exit_underlying=spot,
        )
        self._record_pnl(closed)
        self._position_sectors.pop(pos.symbol, None)
        self._rotations_today += 1

        logger.info(
            f"🔁 ROTATION: closed {pos.symbol} ({pos.entry_confidence:.0%}, "
            f"{ret_pct:+.2f}%) to make room for {symbol} ({confidence:.0%})"
        )
        return True

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

    # Exit reasons that mean a RISK RULE fired, as opposed to housekeeping
    # (rotation, EOD flatten). These are the ones worth waking someone for.
    _RISK_EXITS = ("STOP_HIT", "TARGET_HIT")
    _FIRST_FIRE_MARKER = "first_risk_exit_seen.flag"

    @staticmethod
    def _discord_post(embed: dict) -> bool:
        """
        Single place every Discord alert goes through.

        Returns True only on a real 2xx. Delivery failures are logged rather
        than swallowed silently — a notification path that fails quietly is
        indistinguishable from one that has nothing to say, which is how the
        hardcoded ATR multipliers and the dead all_opening_trades gate both
        stayed hidden. Never raises; alerting must not break trading.

        TLS verification stays on: the webhook URL is a credential.
        """
        import os
        wh = os.getenv("DISCORD_WEBHOOK_URL")
        if not wh:
            return False
        try:
            import requests
            r = requests.post(wh, json={"embeds": [embed]}, timeout=10)
            if r.status_code not in (200, 204):
                logger.warning(f"Discord alert rejected: HTTP {r.status_code}")
                return False
            return True
        except Exception as e:
            logger.warning(f"Discord alert failed to send: {e}")
            return False

    def _alert_entry(self, symbol, direction, qty, price, confidence,
                     stop, target, signal="") -> None:
        """Announce a fill. The bot opened 5 positions today in silence."""
        notional = qty * price
        risk = abs(price - stop) / price * 100 if price else 0.0
        rew = abs(target - price) / price * 100 if price else 0.0
        self._discord_post({
            "title": f"📥 ENTRY — {symbol} {direction}",
            "color": 3447003,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": [
                {"name": "Fill", "value": f"{qty} @ ${price:,.2f}", "inline": True},
                {"name": "Notional", "value": f"${notional:,.0f}", "inline": True},
                {"name": "Confidence", "value": f"{confidence:.0%}", "inline": True},
                {"name": "Stop", "value": f"${stop:,.2f} ({risk:.2f}%)", "inline": True},
                {"name": "Target", "value": f"${target:,.2f} ({rew:.2f}%)", "inline": True},
                {"name": "Signal", "value": (signal or "n/a")[:60], "inline": True},
            ],
            "footer": {"text": "Unusual Whales bot · "
                       + ("PAPER" if EXECUTION_MODE.get("paper_trading", True) else "LIVE")},
        })

    def _check_whale_distribution(self) -> None:
        """
        Alert when a CONFIRMED whale position is being sold into today.

        Open interest settles overnight, so the watchlist state machine cannot
        see an unwind until the next morning. Contract-level intraday aggressor
        flow shows it the same day — which for a position we are following as
        a thesis is the difference between reacting and reading history.

        Deduped per contract per day: the condition persists all session, and
        re-alerting every 300s would bury it.
        """
        if not getattr(self, "watchlist", None):
            return
        today = datetime.now().strftime("%Y-%m-%d")
        if getattr(self, "_distribution_day", None) != today:
            self._distribution_day = today
            self._distribution_alerted = set()

        for hit in self.watchlist.check_intraday_distribution():
            pos, flow = hit["position"], hit["flow"]
            cid = pos.option_chain_id
            if cid in self._distribution_alerted:
                continue
            self._distribution_alerted.add(cid)
            total = flow["ask_premium"] + flow["bid_premium"]
            self._discord_post({
                "title": f"⚠️ WHALE DISTRIBUTION — {pos.symbol} "
                         f"${pos.strike:.0f}{pos.option_type[0]}",
                "description": (
                    f"A position we are tracking is being **sold into today**.\n"
                    f"Open interest will not reflect this until tomorrow."
                ),
                "color": 16776960,
                "timestamp": datetime.utcnow().isoformat(),
                "fields": [
                    {"name": "Hit the bid", "value": f"{flow['bid_share']:.0%} of "
                     f"${total/1e3:,.0f}k", "inline": True},
                    {"name": "Contract volume", "value": f"{flow['volume']:,.0f}", "inline": True},
                    {"name": "Last", "value": f"${flow['last']:,.2f}", "inline": True},
                    {"name": "Original block", "value": f"{pos.block_size:,.0f} @ "
                     f"${pos.block_premium/1e6:.2f}M", "inline": True},
                    {"name": "OI", "value": f"{pos.baseline_oi:,.0f} → {pos.current_oi:,.0f}", "inline": True},
                    {"name": "Block share of OI", "value": f"{pos.oi_concentration:.0%}", "inline": True},
                    {"name": "Caveat", "value":
                     "Bid-side pressure means SOMEBODY is selling this contract, "
                     "not provably the holder being tracked. The block's share of "
                     "open interest above indicates how strong that inference is.",
                     "inline": False},
                ],
                "footer": {"text": "Unusual Whales bot · whale watchlist · intraday"},
            })

    def _alert_skipped_bearish(self, skipped: list) -> None:
        """
        One digest per cycle of bearish signals the long-only rule discarded.

        These are routinely the STRONGEST reads of the cycle — on 2026-09-09
        the two highest-conviction signals were GOOGL PUT at 96% and IWM PUT
        at 94%, both dropped in silence. Whether or not shorting is ever
        enabled, the fact that the best information is being discarded should
        be visible rather than buried in a log nobody reads.

        Batched, not one alert per symbol: three fired in a single cycle today.
        """
        if not skipped:
            return
        lines = []
        for s in sorted(skipped, key=lambda x: -x.get("premium", 0))[:12]:
            prem = s.get("premium") or 0.0
            tag = f" — ${prem/1e6:.2f}M premium" if prem else ""
            lines.append(f"**{s['symbol']}** {s.get('direction','PUT')}{tag}")
        self._discord_post({
            "title": f"📉 {len(skipped)} bearish signal(s) skipped — shorting disabled",
            "description": "\n".join(lines),
            "color": 16776960,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": [{
                "name": "Why",
                "value": ("Long-only: bearish flow on a name we do not hold is "
                          "skipped rather than shorted. Shown because these are "
                          "often the highest-conviction reads of the cycle."),
                "inline": False,
            }],
            "footer": {"text": "Unusual Whales bot · long-only"},
        })

    def _alert_exit(self, pos, pnl: float, pnl_pct: float) -> None:
        """
        Post every position close to Discord, flagging risk-rule exits.

        WHY THIS EXISTS
        Across the bot's entire history NO stop or target has ever fired —
        every position closed on the time barrier, so the exit logic has never
        once been observed working. Win rate cannot validate it: the LEAP run
        scored 60% wins while losing ~$3,500. The first genuine STOP_HIT or
        TARGET_HIT is therefore a milestone, and it is called out as such the
        first time it happens.

        Routed from _record_pnl, which every one of the four close_position
        call sites funnels through, so this cannot miss an exit type.
        """
        import os
        reason = (getattr(pos, "exit_reason", "") or "").upper()
        is_risk = any(r in reason for r in self._RISK_EXITS)

        if "STOP_HIT" in reason:
            head, colour = "🛑 STOP LOSS FIRED", 15158332          # red
        elif "TARGET_HIT" in reason:
            head, colour = "🎯 TARGET HIT", 3066993                # green
        elif reason.startswith("TIER2"):
            head, colour = "🧠 TIER 2 EXIT", 10181046              # purple
        elif "ROTAT" in reason:
            head, colour = "🔄 ROTATED OUT", 9807270               # grey
        elif "EOD" in reason:
            head, colour = "🌆 EOD FLATTEN", 9807270
        else:
            head, colour = "🚪 POSITION CLOSED", 9807270

        # Announce the first-ever risk-rule exit once, then never again.
        first = False
        if is_risk and not os.path.exists(self._FIRST_FIRE_MARKER):
            try:
                with open(self._FIRST_FIRE_MARKER, "w") as fh:
                    fh.write(datetime.now().isoformat())
                first = True
            except Exception:
                pass

        held = ""
        try:
            t0 = datetime.fromisoformat(str(pos.entry_time))
            mins = (datetime.now() - t0).total_seconds() / 60.0
            held = f"{mins:.0f}m" if mins < 120 else f"{mins/60:.1f}h"
        except Exception:
            pass

        logger.warning(
            f"{head}: {pos.symbol} ${pnl:,.0f} ({pnl_pct:+.2f}%) [{reason}]"
        )
        if first:
            logger.warning(
                "🎉 FIRST risk-rule exit ever recorded — exit logic is now "
                "observed working, not merely assumed."
            )

        fields = [
            {"name": "Entry", "value": f"${pos.entry_price:,.2f}", "inline": True},
            {"name": "Exit", "value": f"${pos.exit_price:,.2f}", "inline": True},
            {"name": "P&L", "value": f"${pnl:,.0f} ({pnl_pct:+.2f}%)", "inline": True},
            {"name": "Reason", "value": reason or "n/a", "inline": True},
            {"name": "Qty", "value": f"{pos.quantity}", "inline": True},
            {"name": "Held", "value": held or "n/a", "inline": True},
        ]
        if first:
            fields.append({
                "name": "⚠️ Milestone",
                "value": ("First stop/target ever to fire in this bot. Until "
                          "now every position closed on the time barrier, so "
                          "the exit logic was untested in live conditions."),
                "inline": False,
            })
        self._discord_post({
            "title": f"{head} — {pos.symbol}",
            "color": colour,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": fields,
            "footer": {"text": "Unusual Whales bot · "
                       + ("PAPER" if EXECUTION_MODE.get("paper_trading", True)
                          else "LIVE")},
        })

    def _record_pnl(self, closed_position) -> None:
        """
        Track realized P&L and trip the daily-loss circuit breaker.

        BLOCKER FIX #9: MAX_DAILY_LOSS_PCT was defined in config and never
        referenced, so there was no drawdown halt of any kind.
        """
        if not closed_position or closed_position.exit_price is None:
            return

        for pid, st in list(self._excursions.items()):
            if st.get("symbol") == closed_position.symbol:
                self._flush_excursion(pid, closed_position)
                break

        # Emit the triple-barrier label for the training set. Joined back to
        # features.jsonl by candidate_id.
        try:
            self.feature_logger.log_outcome(
                candidate_id=getattr(closed_position, "candidate_id", "") or "",
                symbol=closed_position.symbol,
                entry_price=closed_position.entry_price,
                exit_price=closed_position.exit_price,
                exit_reason=closed_position.exit_reason or "",
                entry_underlying=closed_position.entry_underlying,
                exit_underlying=closed_position.exit_underlying,
                entry_time=closed_position.entry_time,
                quantity=closed_position.quantity,
                multiplier=closed_position.multiplier,
            )
        except Exception as e:
            logger.debug(f"label logging skipped: {e}")

        mult = closed_position.multiplier
        entry_cost = closed_position.entry_price * closed_position.quantity * mult
        exit_value = closed_position.exit_price * closed_position.quantity * mult
        pnl = exit_value - entry_cost
        self.session_realized_pnl += pnl

        # Alert on every close. Wrapped so a webhook problem can never stop
        # the circuit-breaker check below from running.
        try:
            self._alert_exit(closed_position, pnl,
                             (pnl / entry_cost * 100) if entry_cost else 0.0)
        except Exception as e:
            logger.debug(f"exit alert skipped: {e}")

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
                # Whale watchlist: OI settles overnight, so poll once a day
                # rather than every cycle.
                try:
                    await self._poll_watchlist()
                except Exception as e:
                    logger.debug(f"watchlist poll error: {e}")

                # Sample how far each position has travelled toward its
                # barriers before evaluating any exit.
                try:
                    await self._track_excursions()
                except Exception as e:
                    logger.debug(f"excursion tracking error: {e}")

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
                    # SHADOW MODE: record what Tier 2 would have done without
                    # acting. Tier 2 became capable of firing only today, and
                    # its first live signal was a market-wide rule that would
                    # have closed every long at once.
                    if EXIT_RULES_CONFIG.get("tier2_shadow_mode", True):
                        for pos_id, pos in matching_positions:
                            mark, spot = await self.position_manager.mark_position(
                                pos, self.robinhood_mcp
                            )
                            ret = ((mark - pos.entry_price) / pos.entry_price * 100) if pos.entry_price else 0.0
                            logger.warning(
                                f"👻 TIER2 SHADOW: would exit {pos.symbol} via {exit_reason} "
                                f"(conf {confidence:.0%}) at {ret:+.2f}% — NOT acted on"
                            )
                            self._log_shadow_exit(pos, exit_reason, confidence, mark, spot, ret)
                        continue

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

            # Register whale-sized blocks for OI tracking. Runs before the
            # contract filter deliberately — a 73-DTE block is rejected for
            # TRADING but is exactly what we want to FOLLOW.
            try:
                for a in approved_alerts:
                    self.watchlist.consider(a)
            except Exception as e:
                logger.debug(f"watchlist detection skipped: {e}")

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

                # ---------------------------------------------------------
                # Record the verdict on EVERY Phase-1 survivor, passed or not.
                # The filter discards ~53% of all premium, and the discarded
                # flow is systematically the largest (mean premium at >120 DTE
                # is 4.4x the 0-1d bucket). The 60-day cutoff was a judgement
                # call; without these rows there is no way to check it.
                # De-duplicated by contract so repeated hits on one position
                # are counted once.
                # ---------------------------------------------------------
                pre_filter = list(approved_alerts)
                approved_alerts = contract_filter.filter_alerts(
                    approved_alerts, atr_lookup=lambda s: md.get_atr(s) if s else None
                )
                kept_ids = {a.get("option_chain_id") for a in approved_alerts}

                seen_contracts = set()
                for a in pre_filter:
                    cid = a.get("option_chain_id")
                    if not cid or cid in seen_contracts:
                        continue
                    seen_contracts.add(cid)
                    passed = cid in kept_ids
                    reason = ""
                    if not passed:
                        try:
                            _, reason = ContractFilter(**cf_kwargs).evaluate(
                                a, atr=md.get_atr(a.get("underlying_symbol"))
                            )
                        except Exception:
                            reason = "unknown"
                    try:
                        self.feature_logger.log_screened_alert(a, passed, reason)
                    except Exception as e:
                        logger.debug(f"screened-alert log skipped: {e}")

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

                    gate_detail = {}
                    if self.technical_gates:
                        try:
                            spot = self._safe_float(alert.get("underlying_price"), 0.0)
                            if spot <= 0:
                                spot = get_market_data().get_underlying_price(symbol) or 0.0
                            if spot > 0:
                                gate_detail = await self.technical_gates.evaluate_detailed(
                                    symbol, direction, spot
                                )
                                confidence = gate_detail.get("confidence", confidence)
                        except Exception as e:
                            logger.warning(f"Technical gates failed for {symbol}: {e}; using baseline")

                    # Capture the decision-time feature vector BEFORE executing.
                    # Rejects are logged too — a classifier needs negatives, and
                    # the informative ones are these near-misses.
                    candidate_id = self.feature_logger.make_id(symbol)

                    result = await self.execute_trade(
                        alert,
                        {"direction": direction, "confidence": confidence,
                         "candidate_id": candidate_id},
                    )

                    try:
                        self.feature_logger.log_candidate(
                            alert=alert,
                            technicals=gate_detail.get("technicals"),
                            gate_detail=gate_detail,
                            confidence=confidence,
                            decision="EXECUTED" if result else "REJECTED",
                            reject_reason=None if result else self._last_reject_reason,
                            candidate_id=candidate_id,
                        )
                    except Exception as e:
                        logger.debug(f"feature logging skipped for {symbol}: {e}")

                    if result:
                        executed += 1
                        logger.info(f"✅ TRADE EXECUTED: {symbol} {direction} (conf {confidence:.0%})")
                        try:
                            # No get_latest_position() on the manager — take the
                            # most recent open position for this symbol. pos_id
                            # carries an HHMMSS suffix, so max() is newest.
                            cands = [(pid, p) for pid, p in
                                     self.position_manager.get_all_positions().items()
                                     if p.symbol == symbol]
                            pos = max(cands, key=lambda x: x[0])[1] if cands else None
                            if pos:
                                self._alert_entry(
                                    symbol, direction, pos.quantity, pos.entry_price,
                                    confidence, pos.underlying_stop,
                                    pos.underlying_target,
                                    getattr(pos, "option_chain_id", "") or "",
                                )
                        except Exception as e:
                            logger.debug(f"entry alert skipped for {symbol}: {e}")

                except Exception as e:
                    logger.error(f"Trade execution error: {e}")

            logger.info(f"✅ Cycle complete ({executed} executed, {self.position_manager.total_open_positions()} open)")

            # Post the bearish-skip digest for this cycle, then clear it.
            try:
                self._alert_skipped_bearish(getattr(self, "_skipped_bearish", []))
            except Exception as e:
                logger.debug(f"skip digest failed: {e}")
            finally:
                self._skipped_bearish = []

            # Whale positions being sold into TODAY, a day before open
            # interest would reveal it. Alerted once per contract per day.
            try:
                self._check_whale_distribution()
            except Exception as e:
                logger.debug(f"distribution check failed: {e}")

            # GEX zone alerts. Event-driven: one snapshot at the first cycle
            # of the day, then only when an index CROSSES a gamma level.
            # Posting all four every 300s would be ~48 messages an hour.
            try:
                if self._gex_alerts is None:
                    from uw_discord_gex_alerts import GEXDiscordAlerts
                    self._gex_alerts = GEXDiscordAlerts()
                fired = await self._gex_alerts.check_crossings()
                if fired:
                    logger.info(f"⚡ GEX alerts posted: {', '.join(fired)}")
            except Exception as e:
                logger.debug(f"GEX alert check failed: {e}")

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
