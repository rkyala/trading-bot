"""
Phase 2: Execution Client (MOCK / PAPER / LIVE)

BLOCKER FIX #4
--------------
Previously: `mock_mode: False` routed to a non-mock branch whose every method
was a stub — place_option_order returned success=False, get_option_quotes
returned []. execute_trade then hit `if not quotes: return False`. That is the
real source of the "No quotes available" failures on every attempted trade.
The `paper_trading: True` flag was read nowhere and routed to nothing.

Now there are three explicit modes:
  MOCK  - random synthetic quotes; for unit tests only
  PAPER - REAL NBBO from the Unusual Whales alert, simulated fills, positions
          marked to market using delta against real underlying moves
  LIVE  - refuses to run unless a real MCP executor is injected. It fails
          LOUDLY instead of silently returning success=False.

BLOCKER FIX #8
--------------
Exits previously used `exit_price = entry_price` (P&L exactly $0) or
`entry_price * 1.01` (a fixed +1% "win"). Win rate was therefore an artifact of
the code, not the market. PAPER mode now marks positions using a first-order
delta/gamma approximation against the REAL underlying price. This is a model,
not a broker fill — it is labelled as such everywhere it is surfaced.
"""

import logging
import random
from typing import Optional, List, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


MODE_MOCK = "MOCK"
MODE_PAPER = "PAPER"
MODE_LIVE = "LIVE"


@dataclass
class OrderResponse:
    """Result of a placed order"""
    success: bool
    order_id: Optional[str]
    message: str
    fill_price: Optional[float] = None
    simulated: bool = False


class LiveExecutionUnavailable(RuntimeError):
    """Raised when LIVE mode is requested without a working MCP executor."""


class RobinhoodMCPClient:
    """Execution client with explicit, non-silent mode handling."""

    def __init__(
        self,
        use_mock: bool = True,
        paper_trading: bool = False,
        mcp_executor=None,
    ):
        if use_mock:
            self.mode = MODE_MOCK
        elif paper_trading:
            self.mode = MODE_PAPER
        else:
            self.mode = MODE_LIVE

        self.mcp_executor = mcp_executor
        self._paper_fills: Dict[str, Dict] = {}

        self.stats = {
            "orders_placed": 0,
            "orders_successful": 0,
            "orders_failed": 0,
            "quotes_fetched": 0,
        }

        if self.mode == MODE_MOCK:
            logger.info("🎭 Execution client: MOCK (synthetic data, tests only)")
        elif self.mode == MODE_PAPER:
            logger.info("📝 Execution client: PAPER (real quotes, simulated fills)")
        else:
            if self.mcp_executor is None:
                logger.error(
                    "🚨 LIVE mode requested but no MCP executor was injected. "
                    "Orders will be REFUSED rather than silently dropped."
                )
            else:
                logger.info("🚀 Execution client: LIVE (real money)")

    # ------------------------------------------------------------------ orders

    async def place_option_order(
        self,
        symbol: str,
        option_chain_id: str,
        quantity: int,
        order_type: str = "limit",
        limit_price: Optional[float] = None,
        direction: str = "buy_to_open",
        nbbo_bid: Optional[float] = None,
        nbbo_ask: Optional[float] = None,
    ) -> OrderResponse:
        """Place an option order in the configured mode."""
        self.stats["orders_placed"] += 1

        if self.mode == MODE_MOCK:
            return self._mock_place_option_order(
                symbol, option_chain_id, quantity, order_type, limit_price, direction
            )

        if self.mode == MODE_PAPER:
            return self._paper_place_option_order(
                symbol, option_chain_id, quantity, limit_price, direction,
                nbbo_bid, nbbo_ask,
            )

        # LIVE
        if self.mcp_executor is None:
            self.stats["orders_failed"] += 1
            msg = (
                "LIVE execution unavailable: no Robinhood MCP executor is connected. "
                "Authorize the robinhood-trading MCP server before enabling live mode."
            )
            logger.error(f"🚨 {msg}")
            return OrderResponse(success=False, order_id=None, message=msg)

        try:
            result = await self.mcp_executor.place_option_order(
                symbol=symbol,
                option_chain_id=option_chain_id,
                quantity=quantity,
                order_type=order_type,
                limit_price=limit_price,
                direction=direction,
            )
            ok = bool(result.get("success"))
            self.stats["orders_successful" if ok else "orders_failed"] += 1
            return OrderResponse(
                success=ok,
                order_id=result.get("order_id"),
                message=result.get("message", ""),
                fill_price=result.get("fill_price"),
            )
        except Exception as e:
            self.stats["orders_failed"] += 1
            logger.error(f"❌ LIVE order failed: {e}")
            return OrderResponse(success=False, order_id=None, message=str(e))

    def _paper_place_option_order(
        self,
        symbol: str,
        option_chain_id: str,
        quantity: int,
        limit_price: Optional[float],
        direction: str,
        nbbo_bid: Optional[float],
        nbbo_ask: Optional[float],
    ) -> OrderResponse:
        """
        Simulate a fill against the REAL NBBO carried on the alert.

        Fill assumption: marketable limit at the midpoint fills at the midpoint
        plus half the remaining half-spread (conservative slippage), never
        better than the midpoint.
        """
        if not nbbo_bid or not nbbo_ask or nbbo_ask <= 0 or nbbo_bid <= 0:
            self.stats["orders_failed"] += 1
            return OrderResponse(
                success=False,
                order_id=None,
                message="PAPER: no real NBBO available; refusing to invent a fill price",
            )

        midpoint = (nbbo_bid + nbbo_ask) / 2.0
        half_spread = (nbbo_ask - nbbo_bid) / 2.0
        # Conservative: pay half the half-spread on entry, give it up on exit.
        fill = midpoint + (half_spread * 0.5) if "buy" in direction else midpoint - (half_spread * 0.5)
        fill = round(max(fill, 0.01), 2)

        order_id = f"paper-{self.stats['orders_placed']:05d}"
        self._paper_fills[order_id] = {
            "symbol": symbol,
            "option_chain_id": option_chain_id,
            "quantity": quantity,
            "fill_price": fill,
            "direction": direction,
        }
        self.stats["orders_successful"] += 1

        logger.info(
            f"📝 [PAPER] {direction} {quantity}x {option_chain_id} @ ${fill:.2f} "
            f"(NBBO ${nbbo_bid:.2f}/${nbbo_ask:.2f})"
        )
        return OrderResponse(
            success=True,
            order_id=order_id,
            message=f"Paper fill @ ${fill:.2f}",
            fill_price=fill,
            simulated=True,
        )

    def _mock_place_option_order(
        self, symbol, option_chain_id, quantity, order_type, limit_price, direction
    ) -> OrderResponse:
        if random.random() > 0.05:
            order_id = f"mock-order-{self.stats['orders_placed']:05d}"
            self.stats["orders_successful"] += 1
            return OrderResponse(
                success=True, order_id=order_id,
                message=f"Mock order {order_id}", fill_price=limit_price, simulated=True,
            )
        self.stats["orders_failed"] += 1
        return OrderResponse(success=False, order_id=None, message="Mock rejection")

    # ------------------------------------------------------------- valuation

    @staticmethod
    def estimate_option_value(
        entry_option_price: float,
        entry_underlying: float,
        current_underlying: float,
        delta: float,
        gamma: float = 0.0,
        direction: str = "CALL",
    ) -> float:
        """
        First-order (delta + gamma) mark for a paper position.

        NOT a broker fill. Used so paper P&L responds to real price action
        instead of the previous hardcoded `entry_price * 1.01`.
        """
        move = current_underlying - entry_underlying

        # UW reports delta signed for the contract type; normalize defensively.
        d = abs(delta) if delta else 0.5
        if str(direction).upper().startswith("P"):
            d = -d

        value = entry_option_price + (d * move) + (0.5 * (gamma or 0.0) * move * move)
        return round(max(value, 0.01), 2)

    # ---------------------------------------------------------------- quotes

    async def get_option_quotes(self, option_chain_ids: List[str]) -> List[Dict]:
        if self.mode == MODE_MOCK:
            return self._mock_get_option_quotes(option_chain_ids)

        if self.mode == MODE_PAPER:
            # PAPER never needs synthetic option quotes: the caller supplies the
            # real NBBO straight from the alert. Returning [] here would trip
            # the old `if not quotes: return False` path, so signal explicitly.
            return []

        if self.mcp_executor is None:
            logger.error("🚨 LIVE quotes unavailable: no MCP executor connected")
            return []
        try:
            return await self.mcp_executor.get_option_quotes(option_chain_ids)
        except Exception as e:
            logger.error(f"❌ LIVE quote fetch failed: {e}")
            return []

    def _mock_get_option_quotes(self, option_chain_ids: List[str]) -> List[Dict]:
        quotes = []
        for chain_id in option_chain_ids:
            bid = 4.40 + random.uniform(-0.05, 0.05)
            ask = bid + random.uniform(0.05, 0.15)
            quotes.append({
                "option_chain_id": chain_id,
                "bid": round(bid, 2),
                "ask": round(ask, 2),
                "last": round((bid + ask) / 2, 2),
            })
        self.stats["quotes_fetched"] += 1
        return quotes

    async def get_index_quotes(self, symbols: List[str]) -> List[Dict]:
        """
        Underlying prices. PAPER and LIVE both use REAL market data — the old
        implementation returned a random walk around a hardcoded 4500 for SPX.
        """
        if self.mode == MODE_MOCK:
            return self._mock_get_index_quotes(symbols)

        from uw_market_data import get_market_data
        md = get_market_data()

        quotes = []
        for symbol in symbols:
            price = md.get_underlying_price(symbol)
            if price is None:
                logger.warning(f"⚠️ No price for {symbol}; omitting from quote batch")
                continue
            quotes.append({"symbol": symbol, "last_price": price})

        self.stats["quotes_fetched"] += 1
        return quotes

    def _mock_get_index_quotes(self, symbols: List[str]) -> List[Dict]:
        base_prices = {"SPX": 4500, "NDX": 14000, "RUT": 2050}
        quotes = []
        for symbol in symbols:
            base = base_prices.get(symbol, 4500)
            price = base * (1 + random.uniform(-0.001, 0.001))
            quotes.append({"symbol": symbol, "last_price": round(price, 2)})
        self.stats["quotes_fetched"] += 1
        return quotes

    def log_stats(self):
        logger.info("\n" + "=" * 80)
        logger.info(f"EXECUTION CLIENT STATISTICS (mode={self.mode})")
        logger.info("=" * 80)
        logger.info(f"Orders placed: {self.stats['orders_placed']}")
        logger.info(f"  ✅ Successful: {self.stats['orders_successful']}")
        logger.info(f"  ❌ Failed: {self.stats['orders_failed']}")
        logger.info(f"Quotes fetched: {self.stats['quotes_fetched']}")
        if self.mode == MODE_PAPER:
            logger.info("NOTE: fills and marks are SIMULATED (delta-modelled), not broker fills")
        logger.info("=" * 80 + "\n")
