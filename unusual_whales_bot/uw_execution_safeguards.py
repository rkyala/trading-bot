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

# ---------------------------------------------------------------------------
# BLOCKER FIX: EOD close was `time(15, 45)` compared against machine-local time.
# The machine runs CDT, so 15:45 local = 4:45 PM ET — 45 minutes AFTER the
# 4:00 PM ET close. The force-close therefore never fired before the bell.
# Now anchored explicitly to US/Eastern and evaluated in that zone.
# ---------------------------------------------------------------------------
try:
    from zoneinfo import ZoneInfo
    MARKET_TZ = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    MARKET_TZ = None

EOD_FORCE_CLOSE_TIME = time(15, 45)  # 3:45 PM *Eastern* (15 min before close)
MARKET_CLOSE_TIME = time(16, 0)      # 4:00 PM Eastern


def now_eastern() -> datetime:
    """Current time in US/Eastern, regardless of host timezone."""
    if MARKET_TZ is not None:
        return datetime.now(MARKET_TZ)
    return datetime.now()  # last resort; logged by caller


@dataclass
class ExecutionPlan:
    """Execution instructions for a trade"""
    symbol: str
    entry_price: float
    entry_quantity: int

    # Stop-loss on UNDERLYING price, not option price
    underlying_stop_price: float  # SPX level, e.g., 4450
    underlying_target_price: float  # SPX level, e.g., 4600

    # BLOCKER FIX #3: stops/targets are inverted for bearish positions.
    # "CALL" -> profits when underlying rises  (stop below, target above)
    # "PUT"  -> profits when underlying falls  (stop above, target below)
    direction: str = "CALL"

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

    def get_atr_14(self, symbol: str) -> Optional[float]:
        """
        Fetch real 14-period ATR for the underlying.

        BLOCKER FIX: previously a 3-entry lookup table that returned 18.0 for
        every equity symbol. An 18.0 ATR on a $38 stock (NKE) and on a $1,795
        stock (SNDK) cannot both be right; stops were meaningless on both.
        """
        from uw_market_data import get_market_data

        atr = get_market_data().get_atr(symbol, period=14)
        if atr is None:
            logger.warning(f"⚠️ ATR unavailable for {symbol}")
        return atr

    def generate_execution_plan(
        self,
        symbol: str,
        entry_price: float,
        quantity: int,
        underlying_current_price: float,
        iv_rank: float = 0.0,
        atr_14: Optional[float] = None,
        direction: str = "CALL",
    ) -> Optional[ExecutionPlan]:
        """
        Generate safe execution plan for a trade.

        Returns None when the plan cannot be built safely (no ATR, bad price) —
        callers MUST skip the trade rather than proceed on a placeholder.
        """
        if not underlying_current_price or underlying_current_price <= 0:
            logger.error(f"❌ {symbol}: invalid underlying price {underlying_current_price}")
            return None

        if atr_14 is None:
            atr_14 = self.get_atr_14(symbol)
        if atr_14 is None or atr_14 <= 0:
            logger.error(f"❌ {symbol}: no ATR available, cannot size stops safely")
            return None

        # Cap ATR at 10% of price to avoid absurd stops on illiquid/gappy names
        atr_14 = min(atr_14, underlying_current_price * 0.10)

        underlying_stop_offset = 1.5 * atr_14
        underlying_target_offset = 2.5 * atr_14

        # ---------------------------------------------------------------
        # BLOCKER FIX #3: direction-aware stop/target placement.
        # A PUT profits when the underlying FALLS, so its stop sits ABOVE
        # entry and its target BELOW. The previous code placed both as if
        # every position were bullish, inverting every bearish trade.
        # ---------------------------------------------------------------
        normalized = "PUT" if str(direction).upper().startswith("P") or "BEAR" in str(direction).upper() else "CALL"

        if normalized == "CALL":
            underlying_stop_price = underlying_current_price - underlying_stop_offset
            underlying_target_price = underlying_current_price + underlying_target_offset
        else:
            underlying_stop_price = underlying_current_price + underlying_stop_offset
            underlying_target_price = underlying_current_price - underlying_target_offset

        logger.info(
            f"📊 {symbol} {normalized}: spot=${underlying_current_price:.2f} ATR={atr_14:.2f} → "
            f"stop=${underlying_stop_price:.2f} target=${underlying_target_price:.2f}"
        )

        limit_price = entry_price * 0.995

        plan = ExecutionPlan(
            symbol=symbol,
            entry_price=entry_price,
            entry_quantity=quantity,
            underlying_stop_price=underlying_stop_price,
            underlying_target_price=underlying_target_price,
            direction=normalized,
            order_type="limit",
            limit_price=limit_price,
            max_bid_ask_spread_pct=self.max_bid_ask_spread_pct,
            max_hold_minutes=240,
            eod_force_close_time=EOD_FORCE_CLOSE_TIME,
        )

        self.stats["orders_placed"] += 1
        self.stats["limited_vs_market"]["limit"] += 1

        return plan

    def check_underlying_stop(
        self, current_underlying_price: float, plan: ExecutionPlan
    ) -> Optional[str]:
        """
        Check if the underlying has breached stop or target.

        BLOCKER FIX #3: comparison direction now depends on the position's
        direction. Previously a falling price on a PUT (a WIN) was recorded
        as a stop-out, and a rising price (a LOSS) as a target hit.
        """
        if plan.direction == "CALL":
            stop_hit = current_underlying_price <= plan.underlying_stop_price
            target_hit = current_underlying_price >= plan.underlying_target_price
        else:
            stop_hit = current_underlying_price >= plan.underlying_stop_price
            target_hit = current_underlying_price <= plan.underlying_target_price

        if stop_hit:
            self.stats["underlying_stops_triggered"] += 1
            return (
                f"UNDERLYING STOP HIT: {plan.symbol} {plan.direction} "
                f"${current_underlying_price:.2f} vs stop ${plan.underlying_stop_price:.2f}"
            )

        if target_hit:
            return (
                f"UNDERLYING TARGET: {plan.symbol} {plan.direction} "
                f"${current_underlying_price:.2f} vs target ${plan.underlying_target_price:.2f}"
            )

        return None

    def check_eod_force_close(self) -> bool:
        """
        True once we are inside the EOD liquidation window (3:45 PM Eastern).

        Evaluated in US/Eastern so the host timezone cannot shift the trigger.
        """
        now_et = now_eastern()
        current = now_et.time()

        # Only meaningful during a weekday session
        if now_et.weekday() >= 5:
            return False

        if EOD_FORCE_CLOSE_TIME <= current < MARKET_CLOSE_TIME:
            logger.warning(
                f"⏰ EOD FORCE CLOSE window: {current.strftime('%H:%M')} ET "
                f">= {EOD_FORCE_CLOSE_TIME.strftime('%H:%M')} ET"
            )
            self.stats["eod_forced_closes"] += 1
            return True

        return False

    @staticmethod
    def is_market_open() -> bool:
        """Regular session check (9:30 AM - 4:00 PM ET, weekdays)."""
        now_et = now_eastern()
        if now_et.weekday() >= 5:
            return False
        return time(9, 30) <= now_et.time() < MARKET_CLOSE_TIME

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
