#!/usr/bin/env python3
"""
Robinhood API Integration
Fetches current positions and account info for bot decision-making
"""

import logging
from typing import List, Dict, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class RobinhoodClient:
    """
    Wrapper for Robinhood MCP tools
    Provides position and account data to bot
    """

    def __init__(self):
        """Initialize Robinhood client - uses MCP tools"""
        logger.info("🔗 Robinhood MCP client initialized")
        self.cached_positions = None
        self.cached_account = None

    def get_positions(self) -> Optional[List[Dict]]:
        """
        Fetch current open positions from Robinhood
        Returns: List of positions with symbol, quantity, current_price, etc.
        """
        try:
            logger.info("📊 Fetching positions from Robinhood...")

            # NOTE: In production, this would call:
            # from robinhood_trading import get_equity_positions
            # positions = get_equity_positions()

            # For now, return mock data (will be replaced with real API call)
            mock_positions = [
                {
                    "symbol": "NVDA",
                    "quantity": 5,
                    "average_price": 110.25,
                    "current_price": 115.50,
                    "value": 577.50,
                    "unrealized_pnl": 26.25
                },
                {
                    "symbol": "TSLA",
                    "quantity": 3,
                    "average_price": 225.00,
                    "current_price": 228.75,
                    "value": 686.25,
                    "unrealized_pnl": 11.25
                }
            ]

            self.cached_positions = mock_positions
            logger.info(f"✅ Fetched {len(mock_positions)} positions")
            return mock_positions

        except Exception as e:
            logger.error(f"❌ Error fetching positions: {e}")
            return None

    def get_account(self) -> Optional[Dict]:
        """
        Fetch account info (cash, equity, buying power)
        Returns: Account dict with balances
        """
        try:
            logger.info("💰 Fetching account info from Robinhood...")

            # NOTE: In production, this would call:
            # from robinhood_trading import get_accounts
            # accounts = get_accounts()
            # account = accounts[0]  # Primary account

            # For now, return mock data
            mock_account = {
                "cash": 25000.00,
                "equity": 75000.00,  # cash + positions value
                "buying_power": 100000.00,  # including margin
                "account_id": "mock_account_id",
                "status": "active"
            }

            self.cached_account = mock_account
            logger.info(f"✅ Account equity: ${mock_account['equity']:,.2f}")
            return mock_account

        except Exception as e:
            logger.error(f"❌ Error fetching account: {e}")
            return None

    def is_symbol_owned(self, symbol: str) -> bool:
        """Check if symbol is currently held"""
        if self.cached_positions is None:
            self.get_positions()

        owned_symbols = [p["symbol"] for p in self.cached_positions or []]
        is_owned = symbol in owned_symbols
        logger.info(f"{'✅' if is_owned else '❌'} {symbol} ownership check: {is_owned}")
        return is_owned

    def get_position_value(self, symbol: str) -> float:
        """Get current market value of position"""
        if self.cached_positions is None:
            self.get_positions()

        for pos in self.cached_positions or []:
            if pos["symbol"] == symbol:
                return pos["value"]
        return 0.0

    def place_order(self, symbol: str, qty: int, side: str, price: Optional[float] = None) -> Optional[Dict]:
        """
        Place order via Robinhood API
        NOTE: Requires circuit breaker approval before calling
        """
        try:
            logger.info(f"📤 Placing {side} order: {qty}x {symbol} @ ${price if price else 'MARKET'}")

            # NOTE: In production, this would call:
            # from robinhood_trading import place_equity_order
            # order = place_equity_order(
            #     symbol=symbol,
            #     quantity=qty,
            #     side=side.lower(),
            #     price=price
            # )

            # Mock response
            mock_order = {
                "order_id": "mock_order_12345",
                "symbol": symbol,
                "qty": qty,
                "side": side,
                "status": "submitted",
                "price": price or f"MARKET"
            }

            logger.info(f"✅ Order submitted: {mock_order['order_id']}")
            return mock_order

        except Exception as e:
            logger.error(f"❌ Error placing order: {e}")
            return None


class BotWithRobinhoodIntegration:
    """
    Full bot integration with Robinhood positions and circuit breaker
    """

    def __init__(self, initial_capital: float = 50000):
        from circuit_breaker import ExecutionCircuitBreaker

        self.rb = RobinhoodClient()
        self.cb = ExecutionCircuitBreaker(initial_capital=initial_capital)
        self.account_equity = initial_capital

    def sync_account_state(self):
        """Update circuit breaker with current Robinhood account state"""
        account = self.rb.get_account()
        if account:
            self.account_equity = account["equity"]
            self.cb.metrics.current_equity = account["equity"]
            logger.info(f"✅ Account synced: Equity ${account['equity']:,.2f}")

    def can_buy_symbol(self, symbol: str) -> tuple[bool, str]:
        """
        Check if symbol can be bought (not already owned + circuit breaker ok)
        Returns: (can_buy: bool, reason: str)
        """
        # Check 1: Already owned?
        if self.rb.is_symbol_owned(symbol):
            return False, f"Already own {symbol}"

        # Check 2: Circuit breaker allows?
        is_safe, reason = self.cb.evaluate_circuit_breakers()
        if not is_safe:
            return False, f"Circuit breaker: {reason}"

        return True, "OK to buy"

    def execute_trade(self, symbol: str, qty: int, side: str, price: Optional[float] = None) -> bool:
        """
        Execute trade with full safety checks
        """
        # Pre-checks
        if side == "BUY":
            can_buy, reason = self.can_buy_symbol(symbol)
            if not can_buy:
                logger.error(f"❌ Cannot buy {symbol}: {reason}")
                return False

        # Submit order via circuit breaker
        result = self.cb.process_order(symbol, side, qty, price)
        if not result:
            logger.error(f"❌ Order rejected by circuit breaker")
            return False

        # Place actual order
        order = self.rb.place_order(symbol, qty, side, price)
        return order is not None


# ========================================
# TEST
# ========================================
if __name__ == "__main__":
    print("\n" + "="*100)
    print("ROBINHOOD INTEGRATION TEST")
    print("="*100)

    print("\n✅ Test 1: Get current positions")
    print("-" * 100)
    rb = RobinhoodClient()
    positions = rb.get_positions()
    if positions:
        for pos in positions:
            print(f"  {pos['symbol']:6} | Qty: {pos['quantity']:3} | "
                  f"Price: ${pos['current_price']:7.2f} | Value: ${pos['value']:8.2f} | "
                  f"P&L: ${pos['unrealized_pnl']:+7.2f}")

    print("\n✅ Test 2: Get account info")
    print("-" * 100)
    account = rb.get_account()
    if account:
        print(f"  Cash:         ${account['cash']:>12,.2f}")
        print(f"  Equity:       ${account['equity']:>12,.2f}")
        print(f"  Buying Power: ${account['buying_power']:>12,.2f}")

    print("\n✅ Test 3: Check symbol ownership")
    print("-" * 100)
    for symbol in ["NVDA", "AAPL", "TSLA", "MSFT"]:
        owned = rb.is_symbol_owned(symbol)
        print(f"  {'✅ Owned' if owned else '❌ Not owned'}: {symbol}")

    print("\n✅ Test 4: Full bot integration with circuit breaker")
    print("-" * 100)
    bot = BotWithRobinhoodIntegration(initial_capital=50000)

    print(f"\nInitial state:")
    bot.sync_account_state()

    print(f"\nCan buy NVDA? ", end="")
    can_buy, reason = bot.can_buy_symbol("NVDA")
    print(f"{'✅ YES' if can_buy else '❌ NO'} ({reason})")

    print(f"Can buy AAPL? ", end="")
    can_buy, reason = bot.can_buy_symbol("AAPL")
    print(f"{'✅ YES' if can_buy else '❌ NO'} ({reason})")

    print("\n✅ Test 5: Simulate trade execution with circuit breaker")
    print("-" * 100)
    success = bot.execute_trade("AAPL", 10, "BUY", price=150.00)
    print(f"Trade execution: {'✅ SUCCESS' if success else '❌ FAILED'}")

    print("\n" + "="*100)
    print("✅ ROBINHOOD INTEGRATION READY")
    print("="*100)
    print("""
    Integration Summary:

    ✅ Get current positions from Robinhood
    ✅ Get account balance/equity
    ✅ Check symbol ownership (avoid duplication)
    ✅ Place orders via Robinhood API
    ✅ Circuit breaker pre-execution guard
    ✅ Mock data for testing (ready for real API)

    Next: Replace mock data with actual MCP tool calls
    """)
