"""
Tests for Full UW Capability Integration (5 Endpoints + 6-Gate Filter)

Run: pytest test_uw_endpoints.py -v -s
"""

import pytest
import asyncio
from uw_api_client import UnusualWhalesMockAPI
from uw_phase1_filter import Phase1AlertFilter


class TestUWEndpoints:
    """Test all 5 UW API endpoints"""

    @pytest.mark.asyncio
    async def test_flow_alerts(self):
        api = UnusualWhalesMockAPI()
        alerts = await api.get_flow_alerts()
        assert len(alerts) > 0
        assert "symbol" in alerts[0]
        print(f"✅ Endpoint 1: {len(alerts)} flow alerts")

    @pytest.mark.asyncio
    async def test_market_tide(self):
        api = UnusualWhalesMockAPI()
        tide = await api.get_market_tide("SPY")
        assert tide["net_direction"] in ["BULLISH", "BEARISH", "NEUTRAL"]
        print(f"✅ Endpoint 2: Market Tide {tide['net_direction']}")

    @pytest.mark.asyncio
    async def test_net_ticker_premium(self):
        api = UnusualWhalesMockAPI()
        net_prem = await api.get_net_ticker_premium("SPX")
        assert net_prem["ticker"] == "SPX"
        print(f"✅ Endpoint 3: {net_prem['ticker']} {net_prem['net_direction']}")

    @pytest.mark.asyncio
    async def test_dark_pool_volume(self):
        api = UnusualWhalesMockAPI()
        dp = await api.get_dark_pool_volume("NDX")
        assert "dark_pool_volume" in dp
        print(f"✅ Endpoint 4: Dark pool ${dp['dark_pool_volume']/1e6:.1f}M")

    @pytest.mark.asyncio
    async def test_vol_oi_ratio(self):
        api = UnusualWhalesMockAPI()
        vol_oi = await api.get_vol_oi_ratio("RUT")
        assert vol_oi["vol_oi_ratio"] >= 0
        print(f"✅ Endpoint 5: Vol/OI {vol_oi['vol_oi_ratio']:.2f}")


class TestPhase1Filter:
    """Test Phase 1 filter with all 6 gates"""

    @pytest.mark.asyncio
    async def test_alert_passes_all_gates(self):
        api = UnusualWhalesMockAPI()
        filter_engine = Phase1AlertFilter(api)
        alert = {
            "symbol": "SPX",
            "direction": "CALL",
            "premium": 250_000,
            "ask_volume_pct": 0.85,
        }
        should_trade, reason = await filter_engine.filter_alert(alert)
        assert should_trade is True
        print(f"✅ Alert passed: {reason}")

    @pytest.mark.asyncio
    async def test_alert_fails_gate_1(self):
        api = UnusualWhalesMockAPI()
        filter_engine = Phase1AlertFilter(api)
        alert = {"symbol": "SPX", "direction": "CALL", "premium": 50_000, "ask_volume_pct": 0.85}
        should_trade, reason = await filter_engine.filter_alert(alert)
        assert should_trade is False
        assert "premium" in reason.lower()
        print(f"✅ Rejected: {reason}")

    @pytest.mark.asyncio
    async def test_multiple_alerts(self):
        api = UnusualWhalesMockAPI()
        filter_engine = Phase1AlertFilter(api)
        alerts = await api.get_flow_alerts()
        results = await filter_engine.filter_alerts(alerts)
        passed = sum(1 for _, should_trade, _ in results if should_trade)
        print(f"✅ Filtered {len(alerts)} alerts: {passed} passed")
        filter_engine.log_stats()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
