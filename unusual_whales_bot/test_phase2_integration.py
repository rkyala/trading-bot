"""
Phase 2 Integration Tests: 12 comprehensive tests

Tests all three gaps:
1. Gap 1: Order placement (Robinhood MCP)
2. Gap 2: Price feeds (SPX/NDX/RUT monitoring)
3. Gap 3: EOD force close (liquidate all by 3:45 PM)

Run: pytest test_phase2_integration.py -v
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock
from datetime import datetime, time

from uw_robinhood_mcp import RobinhoodMCPClient
from uw_execution_safeguards import ExecutionSafeguards
from uw_position_manager import PositionManager


class TestGap1OrderPlacement:
    """Gap 1: Order placement via Robinhood MCP"""

    def test_mock_order_placement_success(self):
        """Test placing an order in mock mode"""
        client = RobinhoodMCPClient(use_mock=True)

        # Place order
        async def run():
            response = await client.place_option_order(
                symbol="SPX",
                option_chain_id="SPX270115C04500000",
                quantity=1,
                order_type="limit",
                limit_price=4.49,
                direction="buy_to_open",
            )
            return response

        response = asyncio.run(run())

        assert response.success is True
        assert response.order_id is not None
        assert "mock-order" in response.order_id
        print(f"✅ Order placed: {response.order_id}")

    def test_order_statistics_tracking(self):
        """Test that order statistics are tracked"""
        client = RobinhoodMCPClient(use_mock=True)

        async def run():
            for i in range(5):
                await client.place_option_order(
                    symbol="SPX",
                    option_chain_id=f"SPX_{i}",
                    quantity=1,
                    order_type="limit",
                    limit_price=4.50,
                )

        asyncio.run(run())

        assert client.stats["orders_placed"] == 5
        assert client.stats["orders_successful"] >= 4  # At least 80% success
        print(f"✅ Orders placed: {client.stats['orders_placed']}")


class TestGap2PriceFeed:
    """Gap 2: Price feed (SPX/NDX/RUT monitoring)"""

    def test_index_quotes_fetching(self):
        """Test fetching index quotes"""
        client = RobinhoodMCPClient(use_mock=True)

        async def run():
            quotes = await client.get_index_quotes(["SPX", "NDX", "RUT"])
            return quotes

        quotes = asyncio.run(run())

        assert len(quotes) == 3
        for quote in quotes:
            assert "symbol" in quote
            assert "last_price" in quote
            assert quote["last_price"] > 0
        print(f"✅ Fetched {len(quotes)} index quotes")

    def test_underlying_stop_trigger(self):
        """Test stop loss trigger on underlying price breach"""
        safeguards = ExecutionSafeguards()

        plan = safeguards.generate_execution_plan(
            symbol="SPX",
            entry_price=4.50,
            quantity=1,
            underlying_current_price=4500,
            iv_rank=0.65,
            atr_14=20.0,
        )

        # Price breaches stop
        reason = safeguards.check_underlying_stop(4449, plan)
        assert reason is not None
        assert "STOP" in reason
        print(f"✅ Stop triggered: {reason}")

    def test_underlying_target_trigger(self):
        """Test take profit trigger on target price"""
        safeguards = ExecutionSafeguards()

        plan = safeguards.generate_execution_plan(
            symbol="SPX",
            entry_price=4.50,
            quantity=1,
            underlying_current_price=4500,
            iv_rank=0.65,
            atr_14=20.0,
        )

        # Price hits target
        reason = safeguards.check_underlying_stop(4551, plan)
        assert reason is not None
        assert "TARGET" in reason
        print(f"✅ Target triggered: {reason}")

    def test_position_price_check_integration(self):
        """Test position manager checking positions against price"""
        position_mgr = PositionManager()

        # Add a position
        pos_id = position_mgr.add_position(
            symbol="SPX",
            direction="CALL",
            entry_price=4.50,
            quantity=1,
            underlying_stop=4450,
            underlying_target=4550,
            option_chain_id="SPX_TEST",
        )

        # Check against price that should trigger stop
        exits = position_mgr.check_positions_against_price("SPX", 4449)
        assert len(exits) == 1
        assert exits[0][0] == pos_id
        print(f"✅ Position manager detected exit trigger")


class TestGap3EODLiquidation:
    """Gap 3: EOD force close (liquidate all by 3:45 PM)"""

    def test_eod_force_close_time_check(self):
        """Test EOD force close time detection"""
        safeguards = ExecutionSafeguards()

        # Mock time as 3:50 PM (after 3:45 PM EOD)
        import unittest.mock as mock

        with mock.patch("uw_execution_safeguards.datetime") as mock_dt:
            mock_dt.now.return_value.time.return_value = time(15, 50)

            should_close = safeguards.check_eod_force_close()
            assert should_close is True
            print(f"✅ EOD force close triggered at 3:50 PM")

    def test_eod_closes_all_positions(self):
        """Test that EOD close processes all positions"""
        position_mgr = PositionManager()

        # Add multiple positions
        for i in range(3):
            position_mgr.add_position(
                symbol="SPX",
                direction="CALL",
                entry_price=4.50,
                quantity=1,
                underlying_stop=4450,
                underlying_target=4550,
                option_chain_id=f"SPX_{i}",
            )

        assert position_mgr.total_open_positions() == 3

        # Simulate EOD close (without MCP)
        async def run():
            closed_ids = await position_mgr.check_eod_force_close()
            return closed_ids

        closed = asyncio.run(run())

        assert len(closed) == 3
        assert position_mgr.total_open_positions() == 0
        print(f"✅ EOD closed {len(closed)} positions")


class TestPhase25Hotfixes:
    """Phase 2.5: ATR-based stops + NBBO validation"""

    def test_atr_based_stops_low_volatility(self):
        """Low volatility should produce tight stops"""
        safeguards = ExecutionSafeguards()

        plan = safeguards.generate_execution_plan(
            symbol="SPX",
            entry_price=4.50,
            quantity=1,
            underlying_current_price=4500,
            iv_rank=0.65,
            atr_14=15.0,  # Low volatility
        )

        # Stop offset = 1.5 × 15 = 22.5 points
        assert plan.underlying_stop_price == 4477.5
        print(f"✅ Low-vol ATR: Stop = {plan.underlying_stop_price}")

    def test_atr_based_stops_high_volatility(self):
        """High volatility should produce wider stops"""
        safeguards = ExecutionSafeguards()

        plan = safeguards.generate_execution_plan(
            symbol="SPX",
            entry_price=4.50,
            quantity=1,
            underlying_current_price=4500,
            iv_rank=0.65,
            atr_14=40.0,  # High volatility
        )

        # Stop offset = 1.5 × 40 = 60 points
        assert plan.underlying_stop_price == 4440.0
        print(f"✅ High-vol ATR: Stop = {plan.underlying_stop_price}")

    def test_nbbo_spread_validation_tight(self):
        """Tight spread should pass validation"""
        safeguards = ExecutionSafeguards()

        quote = {"bid": 4.40, "ask": 4.50}
        result = safeguards.validate_nbbo_spread(quote)

        assert result is True
        print(f"✅ Tight spread (2.22%) passed validation")

    def test_nbbo_spread_validation_wide(self):
        """Wide spread should fail validation"""
        safeguards = ExecutionSafeguards()

        quote = {"bid": 3.00, "ask": 6.00}
        result = safeguards.validate_nbbo_spread(quote)

        assert result is False
        print(f"✅ Wide spread (50%) rejected")

    def test_nbbo_midpoint_calculation(self):
        """Calculate midpoint limit price correctly"""
        safeguards = ExecutionSafeguards()

        limit_price, should_execute = safeguards.calculate_midpoint_order(
            nbbo_bid=4.40, nbbo_ask=4.60
        )

        assert should_execute is True
        assert limit_price == 4.50
        print(f"✅ Midpoint calculated: ${limit_price:.2f}")


class TestFullExecutionFlow:
    """End-to-end flow: Alert → Order → Monitor → Exit"""

    def test_full_trade_lifecycle(self):
        """Test complete trade lifecycle"""
        position_mgr = PositionManager()
        safeguards = ExecutionSafeguards()
        client = RobinhoodMCPClient(use_mock=True)

        # 1. Generate execution plan
        plan = safeguards.generate_execution_plan(
            symbol="SPX",
            entry_price=4.50,
            quantity=1,
            underlying_current_price=4500,
            iv_rank=0.65,
            atr_14=20.0,
        )

        # 2. Add position (simulating order placement)
        pos_id = position_mgr.add_position(
            symbol="SPX",
            direction="CALL",
            entry_price=plan.limit_price,
            quantity=1,
            underlying_stop=plan.underlying_stop_price,
            underlying_target=plan.underlying_target_price,
            option_chain_id="SPX_TEST",
            order_id="mock-order-001",
        )

        assert position_mgr.total_open_positions() == 1

        # 3. Monitor price and trigger exit
        exits = position_mgr.check_positions_against_price("SPX", 4551)  # Hit target
        assert len(exits) == 1

        # 4. Close position
        position_mgr.close_position(pos_id, exit_price=4.82, exit_reason="TARGET_HIT")
        assert position_mgr.total_open_positions() == 0

        print(f"✅ Full lifecycle complete: entry → monitor → exit")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
