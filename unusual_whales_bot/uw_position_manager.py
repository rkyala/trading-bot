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
    symbol: str  # SPX, NDX, RUT
    direction: str  # "CALL" or "PUT"
    entry_price: float  # What we paid for the option
    quantity: int  # Number of contracts
    entry_time: str  # ISO timestamp

    # Underlying stops (SPX level, not option price)
    underlying_stop: float  # SPX ≤ this = stop hit
    underlying_target: float  # SPX ≥ this = target hit

    # MCP tracking
    option_chain_id: str
    order_id: Optional[str] = None

    # Exit tracking
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    exit_reason: Optional[str] = None


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
        """Save positions to file"""
        try:
            data = {k: asdict(v) for k, v in self.positions.items()}
            with open(self.positions_file, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"💾 Saved {len(self.positions)} positions")
        except Exception as e:
            logger.error(f"❌ Failed to save positions: {e}")

    def add_position(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        quantity: int,
        underlying_stop: float,
        underlying_target: float,
        option_chain_id: str,
        order_id: Optional[str] = None,
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
        )

        self.positions[pos_id] = position
        self._save_positions()

        logger.info(
            f"✅ Position opened: {pos_id}\n"
            f"  Entry: ${entry_price:.2f} × {quantity} {direction}\n"
            f"  Stop: {symbol} ≤ ${underlying_stop:.0f}\n"
            f"  Target: {symbol} ≥ ${underlying_target:.0f}"
        )

        return pos_id

    def close_position(
        self,
        pos_id: str,
        exit_price: float,
        exit_reason: str,
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

        # Calculate P&L
        entry_cost = position.entry_price * position.quantity * 100
        exit_value = exit_price * position.quantity * 100
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

        Returns: List of (pos_id, exit_reason) for positions that should close
        """
        exits = []

        for pos_id, position in list(self.positions.items()):
            if position.symbol != symbol:
                continue

            # Check stop
            if current_underlying_price <= position.underlying_stop:
                exits.append((pos_id, "STOP_HIT"))
                continue

            # Check target
            if current_underlying_price >= position.underlying_target:
                exits.append((pos_id, "TARGET_HIT"))

        return exits

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
            # In live mode: fetch current option quote and place exit
            # In mock mode: simulate exit
            if robinhood_mcp:
                try:
                    quotes = await robinhood_mcp.get_option_quotes([position.option_chain_id])
                    if quotes:
                        exit_price = quotes[0].get("last", position.entry_price)
                    else:
                        exit_price = position.entry_price  # Fallback
                except Exception as e:
                    logger.warning(f"Failed to fetch exit quote: {e}")
                    exit_price = position.entry_price

                # Place exit order
                try:
                    await robinhood_mcp.place_option_order(
                        symbol=position.symbol,
                        option_chain_id=position.option_chain_id,
                        quantity=position.quantity,
                        order_type="market",
                        direction="sell_to_close",
                    )
                except Exception as e:
                    logger.error(f"Failed to place EOD exit order: {e}")
                    exit_price = position.entry_price
            else:
                # Mock/test mode: assume mid exit
                exit_price = position.entry_price * 1.01  # Slight profit

            # Close position
            self.close_position(pos_id, exit_price, "EOD_FORCE_CLOSE")
            closed_ids.append(pos_id)

        return closed_ids

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
                f"{pos_id}: {pos.direction} {pos.quantity}× {pos.symbol} "
                f"@ ${pos.entry_price:.2f} "
                f"| Stop: ${pos.underlying_stop:.0f} | Target: ${pos.underlying_target:.0f}"
            )

        logger.info("=" * 80 + "\n")
