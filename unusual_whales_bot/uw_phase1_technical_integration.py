#!/usr/bin/env python3
"""
Phase 1 + Technical Integration Wrapper
Adds technical gates (9-11) to Tier 2 filter without modifying core logic
"""

import logging
from typing import Tuple, Dict
import asyncio

from uw_technical_gates import TechnicalGates

logger = logging.getLogger(__name__)


class Phase1TechnicalWrapper:
    """
    Wraps Phase 1 filter and adds technical confirmation.

    Flow:
    1. Run standard Phase 1 gates (1-8)
    2. If passes: Get current price
    3. Run technical gates (9-11)
    4. Adjust confidence based on technical confirmation
    5. Return approval + final confidence score
    """

    def __init__(self, phase1_filter, api_client):
        self.phase1_filter = phase1_filter
        self.technical_gates = TechnicalGates(api_client)
        self.api_client = api_client

    async def filter_alert_with_technicals(
        self, alert: Dict, current_price: float = None
    ) -> Tuple[bool, float]:
        """
        Run Phase 1 filter + technical confirmation

        Args:
            alert: UW alert dict
            current_price: Current underlying price (if not provided, will fetch)

        Returns:
            (approved: bool, confidence: 0-1.0)
        """
        # BLOCKER FIX: read the field the UW API actually returns.
        symbol = alert.get("underlying_symbol") or alert.get("symbol") or "UNKNOWN"
        direction = alert.get("option_type") or alert.get("direction", "CALL")

        # Step 1: Run Phase 1 institutional gates
        # BLOCKER FIX: Phase1AlertFilter exposes `filter_alert`, not
        # `evaluate_alert`. The old call raised AttributeError on every alert,
        # was swallowed by this except block, and returned (False, 0.0) —
        # so wiring this wrapper in would have rejected 100% of trades.
        try:
            phase1_approved = self.phase1_filter.filter_alert(alert) is not None
        except Exception as e:
            logger.error(f"Phase 1 error on {symbol}: {e}")
            return False, 0.0

        if not phase1_approved:
            logger.info(f"❌ Phase 1 rejected {symbol} {direction}")
            return False, 0.3  # Low confidence rejection

        logger.info(f"✅ Phase 1 approved {symbol} {direction}")

        # Step 2: Get current price if not provided
        if current_price is None:
            try:
                quotes = await self.api_client.get_index_quotes([symbol])
                if quotes:
                    current_price = quotes[0].get("last_price", 0)
                else:
                    logger.warning(f"⚠️ No price data for {symbol}, skipping tech gates")
                    return True, 0.75  # Phase 1 pass, neutral confidence
            except Exception as e:
                logger.warning(f"⚠️ Price fetch error for {symbol}: {e}")
                return True, 0.75

        if not current_price or current_price <= 0:
            logger.warning(f"⚠️ Invalid price {current_price} for {symbol}")
            return True, 0.75

        # Step 3: Run technical confirmation
        try:
            technical_confidence = (
                await self.technical_gates.calculate_technical_confidence(
                    symbol, direction, current_price
                )
            )
        except Exception as e:
            logger.error(f"Technical gates error on {symbol}: {e}")
            technical_confidence = 0.75  # Neutral on error

        # Step 4: Final approval decision
        if technical_confidence >= 0.65:
            logger.info(
                f"✅✅ APPROVED: {symbol} {direction} "
                f"(Phase 1 + Tech confidence {technical_confidence:.0%})"
            )
            return True, technical_confidence
        elif technical_confidence >= 0.50:
            logger.info(
                f"⚠️ MARGINAL: {symbol} {direction} "
                f"(Phase 1 pass but tech weak {technical_confidence:.0%})"
            )
            return True, technical_confidence  # Still approve, lower confidence
        else:
            logger.warning(
                f"❌ REJECTED: {symbol} {direction} "
                f"(Tech gates failed {technical_confidence:.0%})"
            )
            return False, technical_confidence

    def get_position_size_from_confidence(self, confidence: float) -> float:
        """
        Scale position size by confidence score

        50-65%:  0.5x (half position - risky)
        65-75%:  0.75x (medium position - acceptable)
        75-85%:  1.0x (full position - good)
        85-95%:  1.25x (overweight - excellent)
        95%+:    1.5x (max position - perfect)
        """
        if confidence < 0.50:
            return 0.0  # Don't trade
        elif confidence < 0.65:
            return 0.5
        elif confidence < 0.75:
            return 0.75
        elif confidence < 0.85:
            return 1.0
        elif confidence < 0.95:
            return 1.25
        else:
            return 1.5

    async def filter_with_position_sizing(
        self, alert: Dict, current_price: float = None, base_size: float = 1.0
    ) -> Tuple[bool, float, float]:
        """
        Run filter + return position size

        Returns:
            (approved: bool, confidence: 0-1.0, position_size: 0-1.5x)
        """
        approved, confidence = await self.filter_alert_with_technicals(
            alert, current_price
        )

        if not approved:
            return False, confidence, 0.0

        position_size = self.get_position_size_from_confidence(confidence)
        scaled_size = base_size * position_size

        logger.info(
            f"Position sizing: confidence {confidence:.0%} "
            f"→ {position_size:.1f}x → {scaled_size:.2f} contracts"
        )

        return True, confidence, scaled_size
