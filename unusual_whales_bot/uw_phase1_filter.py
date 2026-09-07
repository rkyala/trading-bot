"""
Phase 1: Enhanced Alert Filter with FULL UW Capability (All 5 Endpoints)

Multi-layer filtering:
1. Premium size (>$100k)
2. Ask-side aggression (>70%)
3. Market Tide gate (macro flow alignment)
4. Net ticker premium (positioning alignment)
5. Dark pool validation (underlying divergence detection)
6. Vol/OI confirmation (new positions only)

Target: 93% false positive reduction
"""

import logging
from typing import Tuple

logger = logging.getLogger(__name__)


class Phase1AlertFilter:
    """Multi-layer filtering with full UW validation"""

    def __init__(self, uw_api):
        self.uw_api = uw_api
        self.stats = {
            "total_alerts": 0,
            "gate_1_rejected": 0,
            "gate_2_rejected": 0,
            "gate_3_rejected": 0,
            "gate_4_rejected": 0,
            "gate_5_rejected": 0,
            "gate_6_rejected": 0,
            "passed_all_gates": 0,
        }

    async def filter_alert(self, alert: dict) -> Tuple[bool, str]:
        """Filter single alert through all 6 validation gates."""
        self.stats["total_alerts"] += 1
        ticker = alert.get("symbol")
        direction = alert.get("direction")
        premium = alert.get("premium", 0)
        ask_vol_pct = alert.get("ask_volume_pct", 0)

        # Gate 1: Premium
        if premium < 100_000:
            self.stats["gate_1_rejected"] += 1
            return False, "Premium too small (<$100k)"

        # Gate 2: Ask vol
        if ask_vol_pct < 0.70:
            self.stats["gate_2_rejected"] += 1
            return False, "Not aggressive ask-side (<70%)"

        # Gate 3: Market Tide
        tide = await self.uw_api.get_market_tide("SPY")
        if direction == "CALL" and tide["net_direction"] != "BULLISH":
            self.stats["gate_3_rejected"] += 1
            return False, f"Market tide {tide['net_direction']} - wrong macro bias"
        if direction == "PUT" and tide["net_direction"] != "BEARISH":
            self.stats["gate_3_rejected"] += 1
            return False, f"Market tide {tide['net_direction']} - wrong macro bias"

        # Gate 4: Net Ticker Premium
        net_prem = await self.uw_api.get_net_ticker_premium(ticker, window_minutes=60)
        if direction == "CALL" and net_prem["net_direction"] != "BULLISH":
            self.stats["gate_4_rejected"] += 1
            return False, f"{ticker} net positioning {net_prem['net_direction']}"
        if direction == "PUT" and net_prem["net_direction"] != "BEARISH":
            self.stats["gate_4_rejected"] += 1
            return False, f"{ticker} net positioning {net_prem['net_direction']}"

        # Gate 5: Dark Pool
        dark_pool = await self.uw_api.get_dark_pool_volume(ticker)
        if dark_pool["suspicious"] and dark_pool["dark_pool_side"] == "SELL":
            self.stats["gate_5_rejected"] += 1
            return False, "Dark pool selling divergence (underlying dump)"

        # Gate 6: Vol/OI
        vol_oi = await self.uw_api.get_vol_oi_ratio(ticker, days_to_expiry=30)
        if vol_oi["vol_oi_ratio"] < 1.0:
            self.stats["gate_6_rejected"] += 1
            return False, f"Vol/OI {vol_oi['vol_oi_ratio']:.2f} - positions closing"
        if vol_oi["confirmation"] == "WEAK":
            self.stats["gate_6_rejected"] += 1
            return False, "Vol/OI weak confirmation"

        # All gates passed
        self.stats["passed_all_gates"] += 1
        return True, "All 6 gates passed - HIGH CONVICTION"

    async def filter_alerts(self, alerts: list) -> list:
        """Filter multiple alerts."""
        results = []
        for alert in alerts:
            should_trade, reason = await self.filter_alert(alert)
            results.append((alert, should_trade, reason))
        return results

    def log_stats(self):
        """Log filtering statistics"""
        total = self.stats["total_alerts"]
        passed = self.stats["passed_all_gates"]
        rejection_rate = 100 * (1 - (passed / total)) if total > 0 else 0
        logger.info(f"Phase 1 Filter: {passed}/{total} passed ({rejection_rate:.1f}% rejection)")
