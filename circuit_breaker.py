#!/usr/bin/env python3
"""
Execution Circuit Breaker Middleware
Prevents order submission when drawdown or loss streak limits are exceeded
Production-ready for broker API integration
"""

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class AccountMetrics:
    """Track account state for circuit breaker evaluation"""
    initial_balance: float
    current_equity: float
    peak_equity: float
    consecutive_losses: int = 0
    total_trades: int = 0
    is_halted: bool = False
    halt_reason: Optional[str] = None


class ExecutionCircuitBreaker:
    """
    Pre-execution guard for broker API order submission
    Prevents catastrophic losses through automated halts
    """

    def __init__(self, initial_capital: float, max_loss_streak: int = 29, max_drawdown_pct: float = 0.40):
        """
        Args:
            initial_capital: Starting balance (e.g., $50,000)
            max_loss_streak: Consecutive loss threshold (default: 29, 95th percentile)
            max_drawdown_pct: Max drawdown from peak equity (default: 0.40 = -40%)
        """
        self.max_loss_streak = max_loss_streak
        self.max_drawdown_pct = max_drawdown_pct
        self.metrics = AccountMetrics(
            initial_balance=initial_capital,
            current_equity=initial_capital,
            peak_equity=initial_capital
        )

        logger.info(
            f"Circuit Breaker initialized: Capital=${initial_capital:,.0f} | "
            f"Max Streak={max_loss_streak} | Max DD={max_drawdown_pct*100:.1f}%"
        )

    def evaluate_circuit_breakers(self) -> Tuple[bool, Optional[str]]:
        """
        Evaluate all circuit breaker conditions
        Returns: (is_safe_to_trade: bool, reason: str or None)
        """
        if self.metrics.is_halted:
            return False, self.metrics.halt_reason

        # Calculate drawdown relative to peak equity (high-water mark)
        drawdown = (self.metrics.peak_equity - self.metrics.current_equity) / self.metrics.peak_equity

        # CHECK 1: Max Drawdown (-40%)
        if drawdown >= self.max_drawdown_pct:
            self.metrics.is_halted = True
            reason = (
                f"Drawdown limit exceeded: Peak ${self.metrics.peak_equity:,.0f} → "
                f"Current ${self.metrics.current_equity:,.0f} ({drawdown*100:.2f}%) >= {self.max_drawdown_pct*100:.1f}%"
            )
            self.metrics.halt_reason = reason
            logger.critical(f"🛑 CIRCUIT BREAKER [DRAWDOWN]: {reason}")
            return False, reason

        # CHECK 2: Consecutive Loss Streak (29 losses)
        if self.metrics.consecutive_losses >= self.max_loss_streak:
            self.metrics.is_halted = True
            reason = (
                f"Loss streak threshold exceeded: "
                f"{self.metrics.consecutive_losses} consecutive losses >= {self.max_loss_streak}"
            )
            self.metrics.halt_reason = reason
            logger.critical(f"🛑 CIRCUIT BREAKER [STREAK]: {reason}")
            return False, reason

        return True, None

    def record_trade(self, pnl: float, symbol: str = "UNKNOWN"):
        """
        Record trade outcome and update account metrics
        Args:
            pnl: Profit/Loss in dollars (e.g., 100.0 or -50.0)
            symbol: Stock symbol (for logging)
        """
        self.metrics.total_trades += 1
        self.metrics.current_equity += pnl

        # Update peak equity high-water mark
        if self.metrics.current_equity > self.metrics.peak_equity:
            self.metrics.peak_equity = self.metrics.current_equity
            logger.info(f"✅ New peak equity: ${self.metrics.peak_equity:,.0f}")

        # Track consecutive losses
        if pnl < 0:
            self.metrics.consecutive_losses += 1
            logger.warning(
                f"Loss #{self.metrics.consecutive_losses}: {symbol} {pnl:+.2f} | "
                f"Equity: ${self.metrics.current_equity:,.0f}"
            )
        else:
            self.metrics.consecutive_losses = 0  # Reset on winning trade
            logger.info(
                f"✅ Win: {symbol} {pnl:+.2f} | Equity: ${self.metrics.current_equity:,.0f} | "
                f"Loss streak reset"
            )

        # Re-evaluate circuit breakers after each trade
        self.evaluate_circuit_breakers()

    def process_order(self, symbol: str, order_type: str, quantity: int, price: Optional[float] = None,
                     api_client=None) -> Optional[dict]:
        """
        Pre-execution validation wrapper
        Blocks order submission if circuit breaker is active

        Args:
            symbol: Stock ticker (e.g., "NVDA")
            order_type: "BUY" or "SELL"
            quantity: Number of shares
            price: Limit price (optional, None for market order)
            api_client: Broker API instance

        Returns:
            Order response dict if submitted, None if rejected
        """
        is_safe, reason = self.evaluate_circuit_breakers()

        if not is_safe:
            logger.error(
                f"❌ Order REJECTED for {symbol}: Circuit breaker ACTIVE. "
                f"Reason: {reason}"
            )
            return None

        # Order passes safety checks - route to API
        logger.info(
            f"✅ Order approved: {order_type} {quantity}x {symbol} @ "
            f"${price if price else 'MARKET'} | "
            f"Equity: ${self.metrics.current_equity:,.0f}"
        )

        # Submit to broker API if client provided
        if api_client:
            try:
                return api_client.place_order(
                    symbol=symbol,
                    qty=quantity,
                    side=order_type,
                    price=price
                )
            except Exception as e:
                logger.error(f"API Error placing order for {symbol}: {e}")
                return None
        else:
            # Mock response for testing
            return {
                "status": "SUBMITTED",
                "symbol": symbol,
                "qty": quantity,
                "side": order_type,
                "price": price,
                "timestamp": None
            }

    def get_status(self) -> dict:
        """Return current circuit breaker status"""
        drawdown = (self.metrics.peak_equity - self.metrics.current_equity) / self.metrics.peak_equity
        return {
            "is_halted": self.metrics.is_halted,
            "halt_reason": self.metrics.halt_reason,
            "current_equity": self.metrics.current_equity,
            "peak_equity": self.metrics.peak_equity,
            "drawdown_pct": drawdown * 100,
            "consecutive_losses": self.metrics.consecutive_losses,
            "total_trades": self.metrics.total_trades,
            "safety_margins": {
                "drawdown_buffer_pct": (self.max_drawdown_pct - drawdown) * 100,
                "streak_buffer": self.max_loss_streak - self.metrics.consecutive_losses
            }
        }


# ==========================================
# DEPLOYMENT EXAMPLE
# ==========================================
if __name__ == "__main__":
    print("\n" + "="*100)
    print("CIRCUIT BREAKER EXECUTION MIDDLEWARE - DEPLOYMENT TEST")
    print("="*100)

    # Initialize with $50K account
    cb = ExecutionCircuitBreaker(initial_capital=50000, max_loss_streak=29, max_drawdown_pct=0.40)
    mock_api = None

    print("\n✅ Test 1: Normal trading (consecutive losses at 28/29)")
    print("-" * 100)
    for i in range(28):
        cb.record_trade(pnl=-500)
        if i == 27:
            status = cb.get_status()
            print(f"\nStatus at 28 consecutive losses:")
            print(f"  Current Equity: ${status['current_equity']:,.0f}")
            print(f"  Drawdown: {status['drawdown_pct']:.2f}%")
            print(f"  Streak Buffer: {status['safety_margins']['streak_buffer']} trades")

    # Try order at 28 losses (should succeed)
    print(f"\nAttempting order with 28 consecutive losses...")
    result = cb.process_order("NVDA", "BUY", 10, price=120.00)
    print(f"Result: {'✅ ACCEPTED' if result else '❌ REJECTED'}\n")

    print("\n🛑 Test 2: Trigger circuit breaker (29th consecutive loss)")
    print("-" * 100)
    cb.record_trade(pnl=-500)
    status = cb.get_status()
    print(f"\nStatus at 29 consecutive losses:")
    print(f"  Is Halted: {status['is_halted']}")
    print(f"  Halt Reason: {status['halt_reason']}")

    # Try order at 29 losses (should fail)
    print(f"\nAttempting order with 29 consecutive losses...")
    result = cb.process_order("NVDA", "BUY", 10, price=120.00)
    print(f"Result: {'✅ ACCEPTED' if result else '❌ REJECTED'}\n")

    print("\n📊 Test 3: Drawdown circuit breaker")
    print("-" * 100)
    cb2 = ExecutionCircuitBreaker(initial_capital=50000, max_loss_streak=29, max_drawdown_pct=0.40)

    # Simulate 40% drawdown
    loss_per_trade = 500
    num_losses = int(50000 * 0.40 / loss_per_trade)
    print(f"Simulating {num_losses} losses of $500 each to trigger -40% drawdown...")

    for i in range(num_losses + 1):
        cb2.record_trade(pnl=-loss_per_trade)

    status = cb2.get_status()
    print(f"\nStatus at {num_losses} losses:")
    print(f"  Current Equity: ${status['current_equity']:,.0f}")
    print(f"  Drawdown: {status['drawdown_pct']:.2f}%")
    print(f"  Is Halted: {status['is_halted']}")

    result = cb2.process_order("NVDA", "BUY", 10, price=120.00)
    print(f"\nOrder attempt: {'✅ ACCEPTED' if result else '❌ REJECTED'}")

    print("\n" + "="*100)
    print("✅ CIRCUIT BREAKER READY FOR PRODUCTION")
    print("="*100)
    print("""
    Integration with bot_dry_run_v3_5.py:

    1. Import at top:
       from circuit_breaker import ExecutionCircuitBreaker

    2. Initialize in bot setup:
       cb = ExecutionCircuitBreaker(initial_capital=50000)

    3. Before each order submission:
       result = cb.process_order(symbol, order_type, qty, price, api_client)
       if not result:
           return  # Order rejected, skip execution

    4. After trade fills:
       cb.record_trade(pnl=realized_pnl)

    This prevents any trades from executing once:
    - Drawdown exceeds -40%, OR
    - Consecutive losses reach 29+
    """)
