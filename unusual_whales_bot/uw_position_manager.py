"""
Phase 2: Position Manager

Tracks all open option positions:
- Entry prices and quantities
- Stop/target levels (underlying, not option)
- Order IDs for MCP tracking
- Exits when stops triggered or EOD arrives
"""

import logging
import json
from typing import List, Optional, Dict
from datetime import datetime
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class OptionsPosition:
    """Single open option position"""
    symbol: str
    direction: str  # "CALL" or "PUT"
    entry_price: float  # What we paid for the option
    quantity: float  # Shares (may be fractional) or option contracts
    entry_time: str  # ISO timestamp

    # Underlying stop/target levels (meaning depends on `direction`)
    underlying_stop: float
    underlying_target: float

    # MCP tracking
    option_chain_id: str
    order_id: Optional[str] = None

    # BLOCKER FIX #8: entry context required to mark the position to market.
    # Without the entry underlying price and greeks there is no way to compute
    # a real exit value, which is why exits previously used entry_price * 1.01.
    entry_underlying: float = 0.0
    delta: float = 0.5
    gamma: float = 0.0

    # Provenance so simulated results are never mistaken for broker fills
    simulated: bool = True

    # Links this position back to its features.jsonl row (ML training join key)
    candidate_id: str = ""

    # Gate confidence at entry. Needed so the position cap can compare a new
    # candidate against what is already held instead of allocating slots by
    # arrival order.
    entry_confidence: float = 0.0

    # "equity" (shares, multiplier 1) or "option" (contracts, multiplier 100).
    # Applying the option multiplier to a share position overstates P&L 100x.
    instrument: str = "equity"

    @property
    def multiplier(self) -> int:
        return 100 if self.instrument == "option" else 1

    # Exit tracking
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    exit_reason: Optional[str] = None
    exit_underlying: Optional[float] = None


class PositionManager:
    """Manages all open positions"""

    def __init__(self, positions_file: str = "open_positions.json"):
        self.positions_file = positions_file
        self.positions: Dict[str, OptionsPosition] = {}
        self._load_positions()

    def _load_positions(self):
        """Load positions from file"""
        try:
            with open(self.positions_file, "r") as f:
                data = json.load(f)
                self.positions = {
                    k: OptionsPosition(**v) for k, v in data.items()
                }
            logger.info(f"✅ Loaded {len(self.positions)} positions from {self.positions_file}")
        except FileNotFoundError:
            logger.info(f"📌 No existing positions file (first run)")
            self.positions = {}

    def _save_positions(self):
        """
        Atomically persist positions (write temp + fsync + rename).

        BLOCKER FIX: the previous plain `open(...,"w")` + json.dump left a
        window where a crash mid-write truncated open_positions.json and lost
        all position state — the bot would come back believing it held nothing
        while the broker still held everything.
        """
        import os
        import tempfile

        try:
            data = {k: asdict(v) for k, v in self.positions.items()}
            directory = os.path.dirname(os.path.abspath(self.positions_file)) or "."

            fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.positions_file)
            except Exception:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise

            logger.debug(f"💾 Saved {len(self.positions)} positions (atomic)")
        except Exception as e:
            logger.error(f"❌ Failed to save positions: {e}")

    def add_position(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        quantity: float,
        underlying_stop: float,
        underlying_target: float,
        option_chain_id: str,
        order_id: Optional[str] = None,
        entry_underlying: float = 0.0,
        delta: float = 0.5,
        gamma: float = 0.0,
        simulated: bool = True,
        instrument: str = "equity",
        candidate_id: str = "",
        entry_confidence: float = 0.0,
    ) -> str:
        """
        Add a new open position.

        Returns: Position ID for tracking
        """
        import time
        # Use microsecond precision to ensure unique IDs in rapid-fire tests
        timestamp = datetime.now().strftime('%H%M%S') + str(int(time.time() * 1000000) % 1000000).zfill(6)
        pos_id = f"{symbol}_{direction}_{timestamp}"

        position = OptionsPosition(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            quantity=quantity,
            entry_time=datetime.now().isoformat(),
            underlying_stop=underlying_stop,
            underlying_target=underlying_target,
            option_chain_id=option_chain_id,
            order_id=order_id,
            entry_underlying=entry_underlying,
            delta=delta,
            gamma=gamma,
            simulated=simulated,
            instrument=instrument,
            candidate_id=candidate_id,
            entry_confidence=entry_confidence,
        )

        self.positions[pos_id] = position
        self._save_positions()

        unit = "sh" if instrument == "equity" else "ct"
        is_put = str(direction).upper().startswith("P")
        logger.info(
            f"✅ Position opened: {pos_id}\n"
            f"  Entry: {quantity:g}{unit} @ ${entry_price:.2f} ({direction})\n"
            f"  Stop:   {symbol} {'≥' if is_put else '≤'} ${underlying_stop:.2f}\n"
            f"  Target: {symbol} {'≤' if is_put else '≥'} ${underlying_target:.2f}"
        )

        return pos_id

    def close_position(
        self,
        pos_id: str,
        exit_price: float,
        exit_reason: str,
        exit_underlying: Optional[float] = None,
    ) -> Optional[OptionsPosition]:
        """
        Close a position.

        Returns: Closed position
        """
        if pos_id not in self.positions:
            logger.warning(f"❌ Position not found: {pos_id}")
            return None

        position = self.positions[pos_id]
        position.exit_price = exit_price
        position.exit_time = datetime.now().isoformat()
        position.exit_reason = exit_reason
        position.exit_underlying = exit_underlying

        # Append to a durable trade log so validation win-rate can be computed
        # from actual closed trades rather than re-derived from live state.
        self._append_trade_log(position, pos_id)

        # Calculate P&L
        mult = position.multiplier
        entry_cost = position.entry_price * position.quantity * mult
        exit_value = exit_price * position.quantity * mult
        pnl = exit_value - entry_cost
        pnl_pct = (pnl / entry_cost * 100) if entry_cost != 0 else 0

        logger.info(
            f"✅ Position closed: {pos_id}\n"
            f"  Exit: ${exit_price:.2f} ({exit_reason})\n"
            f"  P&L: ${pnl:.0f} ({pnl_pct:+.2f}%)"
        )

        # Remove from active positions
        del self.positions[pos_id]
        self._save_positions()

        return position

    def check_positions_against_price(
        self,
        symbol: str,
        current_underlying_price: float,
    ) -> List[tuple]:
        """
        Check all positions of a symbol against current price.

        BLOCKER FIX #3: comparisons are direction-aware. Previously every
        position was evaluated as if bullish, so a PUT whose underlying fell
        (a winning trade) was closed as "STOP_HIT", and one whose underlying
        rose (a losing trade) was booked as "TARGET_HIT".

        Returns: List of (pos_id, exit_reason) for positions that should close
        """
        exits = []

        for pos_id, position in list(self.positions.items()):
            if position.symbol != symbol:
                continue

            is_put = str(position.direction).upper().startswith("P")

            if is_put:
                stop_hit = current_underlying_price >= position.underlying_stop
                target_hit = current_underlying_price <= position.underlying_target
            else:
                stop_hit = current_underlying_price <= position.underlying_stop
                target_hit = current_underlying_price >= position.underlying_target

            if stop_hit:
                exits.append((pos_id, "STOP_HIT"))
            elif target_hit:
                exits.append((pos_id, "TARGET_HIT"))

        return exits

    def has_open_position(self, symbol: str) -> bool:
        """
        BLOCKER FIX #10: entry de-duplication against ALREADY OPEN positions.

        Consolidation only de-duplicates within a single cycle. Without this
        check, cycle N+1 re-enters every symbol still held from cycle N — at
        5-minute cycles with 4-hour holds that is up to ~48 stacked entries per
        symbol. This is the same defect recorded in the Aug 7 and Aug 12
        production incidents.
        """
        return any(p.symbol == symbol for p in self.positions.values())

    def open_symbols(self) -> set:
        """Set of symbols currently held."""
        return {p.symbol for p in self.positions.values()}

    def _append_trade_log(self, position: OptionsPosition, pos_id: str):
        """Append a closed trade to closed_trades.jsonl for validation stats."""
        try:
            mult = position.multiplier
            entry_cost = position.entry_price * position.quantity * mult
            exit_value = (position.exit_price or 0) * position.quantity * mult
            pnl = exit_value - entry_cost
            record = asdict(position)
            record["position_id"] = pos_id
            record["pnl"] = round(pnl, 2)
            record["pnl_pct"] = round((pnl / entry_cost * 100) if entry_cost else 0.0, 4)
            record["win"] = pnl > 0
            with open("closed_trades.jsonl", "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.warning(f"Could not append trade log: {e}")

    async def check_eod_force_close(self, robinhood_mcp=None) -> List[str]:
        """
        Force close all positions at EOD (3:45 PM).

        Args:
            robinhood_mcp: MCP client for placing exit orders

        Returns: List of closed position IDs
        """
        if not self.positions:
            logger.debug("📌 No open positions to close at EOD")
            return []

        logger.warning(f"🚨 EOD FORCE CLOSE: {len(self.positions)} positions")

        closed_ids = []
        for pos_id, position in list(self.positions.items()):
            exit_price, exit_underlying = await self.mark_position(position, robinhood_mcp)

            if robinhood_mcp is not None:
                try:
                    await robinhood_mcp.place_option_order(
                        symbol=position.symbol,
                        option_chain_id=position.option_chain_id,
                        quantity=position.quantity,
                        order_type="market",
                        direction="sell_to_close",
                    )
                except Exception as e:
                    logger.error(f"Failed to place EOD exit order for {pos_id}: {e}")

            self.close_position(pos_id, exit_price, "EOD_FORCE_CLOSE", exit_underlying)
            closed_ids.append(pos_id)

        return closed_ids

    async def mark_position(self, position: OptionsPosition, robinhood_mcp=None):
        """
        Value a position using the REAL current underlying price.

        BLOCKER FIX #8: replaces `exit_price = entry_price` (always $0 P&L) and
        `entry_price * 1.01` (always +1%). Those made the ≥55% win-rate gate
        unmeasurable — win rate was a property of the code, not the market.

        Returns: (exit_price, exit_underlying)
        """
        from uw_market_data import get_market_data

        # ---------------------------------------------------------------
        # EQUITY: the position IS the underlying, so the mark is simply the
        # live share price. No option model, no modelling error — this is a
        # real price, not an estimate.
        # ---------------------------------------------------------------
        if position.instrument == "equity":
            spot = get_market_data().get_underlying_price(position.symbol)
            if spot is None:
                logger.warning(
                    f"⚠️ {position.symbol}: no live price; booking flat rather "
                    f"than inventing a P&L"
                )
                return position.entry_price, None
            return round(spot, 2), spot

        # Prefer a real broker quote when one is actually available (LIVE).
        if robinhood_mcp is not None and getattr(robinhood_mcp, "mode", None) == "LIVE":
            try:
                quotes = await robinhood_mcp.get_option_quotes([position.option_chain_id])
                if quotes and quotes[0].get("last"):
                    spot = get_market_data().get_underlying_price(position.symbol)
                    return float(quotes[0]["last"]), spot
            except Exception as e:
                logger.warning(f"Live exit quote failed for {position.symbol}: {e}")

        spot = get_market_data().get_underlying_price(position.symbol)
        if spot is None or not position.entry_underlying:
            # No honest way to mark it — hold the entry price and say so.
            logger.warning(
                f"⚠️ {position.symbol}: cannot mark to market "
                f"(spot={spot}, entry_underlying={position.entry_underlying}); "
                f"booking flat rather than inventing a P&L"
            )
            return position.entry_price, spot

        from uw_robinhood_mcp import RobinhoodMCPClient
        value = RobinhoodMCPClient.estimate_option_value(
            entry_option_price=position.entry_price,
            entry_underlying=position.entry_underlying,
            current_underlying=spot,
            delta=position.delta,
            gamma=position.gamma,
            direction=position.direction,
        )
        return value, spot

    def get_all_positions(self) -> Dict[str, OptionsPosition]:
        """Get all open positions"""
        return self.positions.copy()

    def get_positions_by_symbol(self, symbol: str) -> List[OptionsPosition]:
        """Get all positions for a specific symbol"""
        return [p for p in self.positions.values() if p.symbol == symbol]

    def total_open_positions(self) -> int:
        """Count of open positions"""
        return len(self.positions)

    def log_positions(self):
        """Log all open positions"""
        if not self.positions:
            logger.info("📌 No open positions")
            return

        logger.info("\n" + "=" * 80)
        logger.info("OPEN POSITIONS")
        logger.info("=" * 80)

        for pos_id, pos in self.positions.items():
            logger.info(
                f"{pos_id}: {pos.direction} {pos.quantity:g}× {pos.symbol} "
                f"@ ${pos.entry_price:.2f} "
                f"| Stop: ${pos.underlying_stop:.0f} | Target: ${pos.underlying_target:.0f}"
            )

        logger.info("=" * 80 + "\n")
