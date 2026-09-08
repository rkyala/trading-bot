#!/usr/bin/env python3
"""
Tier 2 Integration Layer
Integrates 4 options-based exit rules into the main bot execution flow
"""

import asyncio
import logging
from typing import Dict, Optional, Tuple

from uw_tier2_exit_monitor import Tier2ExitMonitor, ExitSignal
from uw_config import EXIT_RULES_CONFIG

logger = logging.getLogger(__name__)


class Tier2ExitIntegration:
    """
    Manages Tier 2 exit monitoring for live positions.
    Monitors all 4 rules in parallel, exits on first trigger.
    """

    def __init__(self, api_client):
        self.tier2_monitor = Tier2ExitMonitor(api_client)
        self.enabled = EXIT_RULES_CONFIG.get("tier2_enabled", True)
        logger.info(f"✅ Tier 2 Exit Integration: {'ENABLED' if self.enabled else 'DISABLED'}")

    async def check_tier2_exits(self, positions: Dict) -> Dict[str, Tuple[str, float]]:
        """
        Check all positions for Tier 2 exit signals.

        Args:
            positions: Dict of {symbol: position_data}

        Returns:
            Dict of {symbol: (exit_reason, confidence)}
            Empty dict if no exits triggered
        """
        if not self.enabled or not positions:
            return {}

        try:
            exit_signals = await self.tier2_monitor.check_all_exits(positions)

            result = {}
            for symbol, signal in exit_signals.items():
                if signal.triggered:
                    result[symbol] = (signal.reason, signal.confidence)
                    logger.info(
                        f"🚨 TIER 2 EXIT: {symbol} | "
                        f"Reason: {signal.reason} | "
                        f"Confidence: {signal.confidence:.0%}"
                    )

            return result

        except Exception as e:
            logger.error(f"❌ Tier 2 exit check error: {e}")
            return {}

    def cleanup_position(self, symbol: str) -> None:
        """Remove position from Tier 2 monitoring"""
        self.tier2_monitor.cleanup_position(symbol)

    def get_exit_summary(self) -> Dict:
        """Get summary of active position monitoring"""
        return {
            "positions_monitored": len(self.tier2_monitor.positions),
            "rules_active": {
                "flow_exhaustion": EXIT_RULES_CONFIG.get("flow_exhaustion_enabled", True),
                "put_call_flip": EXIT_RULES_CONFIG.get("put_call_flip_enabled", True),
                "dark_pool": EXIT_RULES_CONFIG.get("dark_pool_enabled", True),
                "market_tide": EXIT_RULES_CONFIG.get("market_tide_enabled", True),
            }
        }
