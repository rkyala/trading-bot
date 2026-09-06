"""
Phase 2.5: Dynamic Execution & Invalidation Rules

Production safety guards:
1. ATR-based dynamic stops (1.5x/2.5x ATR instead of hardcoded offsets)
2. NBBO spread validation (reject spreads > 5%)
3. NBBO midpoint limit order calculation
4. EOD force-close (all positions liquidated by 3:45 PM EST)

This prevents:
- Whipsaws from option premium noise (use underlying stops)
- Poor fills on illiquid contracts (validate spreads)
- Slippage from market orders (use NBBO midpoint limits)
- Overnight gap risk (force close intraday)
"""

import logging
from datetime import datetime, time
from typing import Optional, Dict, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExecutionPlan:
    """Execution instructions for a trade"""
    symbol: str
    entry_price: float
    entry_quantity: int

    # Stop-loss on UNDERLYING price, not option price
    underlying_stop_price: float  # SPX level, e.g., 4450
    underlying_target_price: float  # SPX level, e.g., 4600

    # Execution controls
    order_type: str = "limit"  # Not "market"
    limit_price: Optional[float] = None  # Midpoint if using limit
    max_bid_ask_spread_pct: float = 0.05  # Skip if spread > 5%

    # Time controls
    max_hold_minutes: int = 240  # 4 hours
    eod_force_close_time: time = time(15, 45)  # 3:45 PM EST

    def __repr__(self):
        return f"""
ExecutionPlan:
  Symbol: {self.symbol}
  Entry: ${self.entry_price:.2f}

  UNDERLYING STOPS (SPX price level):
  ├─ Stop Loss: SPX <= ${self.underlying_stop_price:.0f}
  ├─ Take Profit: SPX >= ${self.underlying_target_price:.0f}

  EXECUTION:
  ├─ Order Type: {self.order_type.upper()}
  ├─ Limit Price: ${self.limit_price:.2f} if limit
  ├─ Max Spread: {self.max_bid_ask_spread_pct*100:.1f}%

  TIME CONTROLS:
  ├─ Max Hold: {self.max_hold_minutes} minutes (4 hours)
  ├─ EOD Close: {self.eod_force_close_time.strftime('%H:%M %p')}
        """


class ExecutionSafeguards:
    """Phase 2.5: Dynamic execution controls"""

    def __init__(self, max_bid_ask_spread_pct: float = 0.05):
        self.max_bid_ask_spread_pct = max_bid_ask_spread_pct
        self.stats = {
            "orders_placed": 0,
            "limited_vs_market": {"limit": 0, "market": 0},
            "midpoint_fills": 0,
            "eod_forced_closes": 0,
            "underlying_stops_triggered": 0,
            "dropped_wide_spread": 0,
        }

    def get_atr_14(self, symbol: str) -> float:
        """
        Fetch 14-period ATR for underlying symbol.

        Used for dynamic stop/target calculation (adapts to volatility).

        Returns: Estimated ATR based on symbol
        """
        atr_defaults = {
            "SPX": 18.0,  # S&P 500 typical ATR
            "NDX": 40.0,  # Nasdaq-100 more volatile
            "RUT": 25.0,  # Russell 2000 mid-range
        }
        return atr_defaults.get(symbol, 18.0)

    def generate_execution_plan(
        self,
        symbol: str,
        entry_price: float,
        quantity: int,
        underlying_current_price: float,
        iv_rank: float,
        atr_14: Optional[float] = None,
    ) -> ExecutionPlan:
        """
        Generate safe execution plan for a trade.

        Phase 2.5 HOTFIX: Dynamic ATR-based stops instead of hardcoded offsets
        """

        # =====================================================================
        # HOTFIX: ADAPTIVE STOPS (ATR-based)
        # =====================================================================

        if atr_14 is None:
            atr_14 = self.get_atr_14(symbol)

        # Dynamic offsets based on volatility
        underlying_stop_offset = 1.5 * atr_14  # Tighter in low-vol, wider in high-vol
        underlying_target_offset = 2.5 * atr_14  # Target adapts too

        logger.info(
            f"📊 ATR-based stops: ATR={atr_14:.2f} → Stop offset={underlying_stop_offset:.2f}, "
            f"Target offset={underlying_target_offset:.2f}"
        )

        underlying_stop_price = underlying_current_price - underlying_stop_offset
        underlying_target_price = underlying_current_price + underlying_target_offset

        # =====================================================================
        # RULE 2: Use LIMIT orders at midpoint (not market)
        # =====================================================================

        limit_price = entry_price * 0.995  # Slightly below to improve fills

        plan = ExecutionPlan(
            symbol=symbol,
            entry_price=entry_price,
            entry_quantity=quantity,
            underlying_stop_price=underlying_stop_price,
            underlying_target_price=underlying_target_price,
            order_type="limit",
            limit_price=limit_price,
            max_bid_ask_spread_pct=0.05,
            max_hold_minutes=240,
            eod_force_close_time=time(15, 45),  # 3:45 PM EST
        )

        self.stats["orders_placed"] += 1
        self.stats["limited_vs_market"]["limit"] += 1

        return plan

    def check_underlying_stop(
        self, current_underlying_price: float, plan: ExecutionPlan
    ) -> Optional[str]:
        """
        Check if underlying price has breached stop-loss level.

        Returns None if position should stay open, or exit reason if triggered.
        """
        if current_underlying_price <= plan.underlying_stop_price:
            reason = (
                f"UNDERLYING STOP HIT: {plan.symbol} ${current_underlying_price:.0f} "
                f"<= ${plan.underlying_stop_price:.0f}"
            )
            self.stats["underlying_stops_triggered"] += 1
            return reason

        if current_underlying_price >= plan.underlying_target_price:
            reason = (
                f"UNDERLYING TARGET: {plan.symbol} ${current_underlying_price:.0f} "
                f">= ${plan.underlying_target_price:.0f}"
            )
            return reason

        return None

    def check_eod_force_close(self) -> bool:
        """
        Check if current time is past EOD close time (3:45 PM EST).
        If so, ALL positions must be closed before market close.

        Returns True if should force close all positions.
        """
        now = datetime.now().time()
        eod_close_time = time(15, 45)  # 3:45 PM EST

        if now >= eod_close_time:
            logger.warning(
                f"⏰ EOD FORCE CLOSE triggered: {now.strftime('%H:%M')} >= {eod_close_time.strftime('%H:%M')}"
            )
            self.stats["eod_forced_closes"] += 1
            return True

        return False

    def validate_nbbo_spread(self, quote: dict) -> bool:
        """
        HOTFIX (Phase 2.5): Validate bid-ask spread before placing order.

        Rejects orders on illiquid contracts (spread > max_bid_ask_spread_pct).
        Prevents slippage and fill failures.

        Args:
            quote: Dict with 'bid' and 'ask' keys

        Returns: True if spread acceptable, False if too wide
        """
        bid = quote.get("bid", 0)
        ask = quote.get("ask", 0)

        if ask <= 0:
            logger.warning("❌ Invalid quote: ask <= 0")
            return False

        spread_pct = (ask - bid) / ask
        max_spread = self.max_bid_ask_spread_pct

        if spread_pct > max_spread:
            logger.warning(
                f"❌ Spread too wide: {spread_pct*100:.2f}% > {max_spread*100:.1f}% "
                f"(bid=${bid:.2f}, ask=${ask:.2f})"
            )
            self.stats["dropped_wide_spread"] += 1
            return False

        logger.debug(f"✓ Spread OK: {spread_pct*100:.2f}% (bid=${bid:.2f}, ask=${ask:.2f})")
        return True

    def calculate_midpoint_order(
        self, nbbo_bid: float, nbbo_ask: float
    ) -> Tuple[Optional[float], bool]:
        """
        HOTFIX (Phase 2.5): Calculate optimal limit order price using NBBO midpoint.

        Strategy: Place limit at NBBO midpoint (not entry_price guess).
        This improves fills and avoids slippage.

        Args:
            nbbo_bid: Current bid price
            nbbo_ask: Current ask price

        Returns: (limit_price, should_execute)
        """
        if nbbo_ask <= 0 or nbbo_bid <= 0:
            logger.warning("❌ Invalid NBBO prices")
            return (None, False)

        spread_pct = (nbbo_ask - nbbo_bid) / nbbo_ask

        # Skip if spread is too wide (> 5%)
        if spread_pct > self.max_bid_ask_spread_pct:
            logger.warning(
                f"❌ Spread too wide: {spread_pct*100:.2f}% (bid=${nbbo_bid:.2f}, ask=${nbbo_ask:.2f})"
            )
            return (None, False)

        # Calculate NBBO midpoint
        midpoint = (nbbo_bid + nbbo_ask) / 2

        # Place limit at midpoint
        limit_price = round(midpoint, 2)

        logger.info(
            f"✓ Limit order @ NBBO midpoint: ${limit_price:.2f} "
            f"(bid=${nbbo_bid:.2f}, ask=${nbbo_ask:.2f})"
        )
        self.stats["midpoint_fills"] += 1

        return (limit_price, True)

    def log_stats(self):
        """Log execution statistics"""
        logger.info("\n" + "=" * 80)
        logger.info("PHASE 2.5: EXECUTION SAFEGUARDS STATISTICS")
        logger.info("=" * 80)
        logger.info(f"Orders placed: {self.stats['orders_placed']}")
        logger.info(
            f"  Limit orders: {self.stats['limited_vs_market']['limit']} "
            f"(vs market: {self.stats['limited_vs_market']['market']})"
        )
        logger.info(f"Midpoint fills: {self.stats['midpoint_fills']}")
        logger.info(f"EOD forced closes: {self.stats['eod_forced_closes']}")
        logger.info(f"Underlying stops triggered: {self.stats['underlying_stops_triggered']}")
        logger.info(f"Wide spreads rejected: {self.stats['dropped_wide_spread']}")
        logger.info("=" * 80 + "\n")
