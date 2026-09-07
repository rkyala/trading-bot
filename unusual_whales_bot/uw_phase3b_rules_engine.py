"""
Phase 3B: Deterministic Rules Engine (Pure Python, Zero Cost)

Confidence-based trade filtering and position sizing.
No Redis, no external dependencies, sub-millisecond execution.

Confidence Scoring:
  Base: 0.75 (Phase 1 passed)
  + Premium size: +0.10 if >$400k, -0.05 if <$200k
  + Dark pool: +0.05 if BUY, -0.15 if SELL
  + IV window: +0.05 if 0.15-0.25, -0.10 if <0.14

Position Sizing:
  0.85+ confidence: 100% position
  0.70-0.85: 75% position
  0.65-0.70: 50% position
  <0.65: REJECT

Expected Impact:
  - Filters out low-quality alerts
  - Sizes positions by conviction
  - Improves win rate +5-10%
"""

import logging
from dataclasses import dataclass
from typing import Tuple

logger = logging.getLogger(__name__)


@dataclass
class PhaseThreeBVerdict:
    """Phase 3B trade decision"""
    should_execute: bool
    adjusted_confidence: float
    position_scale: float  # 0.5, 0.75, or 1.0
    reasoning: str


class PhaseThreeBRulesEngine:
    """Deterministic rules-based trade filtering and sizing"""

    def __init__(self, min_confidence_threshold: float = 0.65):
        """
        Args:
            min_confidence_threshold: Minimum confidence to execute (0-1)
        """
        self.min_confidence_threshold = min_confidence_threshold
        self.stats = {
            "total_reviewed": 0,
            "approved": 0,
            "rejected": 0,
        }

    def evaluate_trade(self, alert: dict) -> PhaseThreeBVerdict:
        """
        Evaluate trade through Phase 3B rules.

        Args:
            alert: Phase 1 approved alert dict

        Returns:
            PhaseThreeBVerdict with confidence and position sizing
        """
        self.stats["total_reviewed"] += 1

        try:
            # Extract fields
            symbol = alert.get("underlying_symbol", alert.get("symbol", "UNKNOWN"))
            direction = (alert.get("option_type") or alert.get("direction", "")).upper()
            premium = float(alert.get("premium", 0))
            dark_pool_side = alert.get("dark_pool_side", "NEUTRAL")
            iv = float(alert.get("implied_volatility", 0.20))
            multi_vol = int(alert.get("multi_vol", 0))

            # ===== HARD REJECT: Multi-leg spreads =====
            if multi_vol > 0:
                self.stats["rejected"] += 1
                return PhaseThreeBVerdict(
                    should_execute=False,
                    adjusted_confidence=0.0,
                    position_scale=0.0,
                    reasoning=f"Synthetic spread trap (multi_vol={multi_vol})"
                )

            # ===== CONFIDENCE SCORING =====
            confidence = 0.75  # Phase 1 baseline

            # Factor 1: Premium size
            if premium > 400_000:
                confidence += 0.10
            elif premium < 200_000:
                confidence -= 0.05

            # Factor 2: Dark pool alignment
            if dark_pool_side == "BUY":
                confidence += 0.05
            elif dark_pool_side == "SELL":
                confidence -= 0.15  # Red flag: selling pressure

            # Factor 3: IV window
            if 0.15 <= iv <= 0.25:
                confidence += 0.05
            elif iv < 0.14:
                confidence -= 0.10

            # Clamp to [0, 1]
            confidence = max(0.0, min(1.0, confidence))

            # ===== EXECUTION DECISION =====
            should_execute = confidence >= self.min_confidence_threshold

            if should_execute:
                self.stats["approved"] += 1
            else:
                self.stats["rejected"] += 1

            # ===== POSITION SIZING =====
            if confidence >= 0.85:
                position_scale = 1.0  # 100% position
            elif confidence >= 0.70:
                position_scale = 0.75  # 75% position
            elif confidence >= 0.65:
                position_scale = 0.5  # 50% position
            else:
                position_scale = 0.0  # Rejected

            reasoning = (
                f"{symbol} {direction} | "
                f"Conf={confidence:.2f} | "
                f"Premium=${premium/1e6:.1f}M | "
                f"DarkPool={dark_pool_side} | "
                f"IV={iv:.2f} | "
                f"Scale={position_scale:.0%}"
            )

            return PhaseThreeBVerdict(
                should_execute=should_execute,
                adjusted_confidence=confidence,
                position_scale=position_scale,
                reasoning=reasoning
            )

        except Exception as e:
            logger.error(f"Phase 3B error: {e}")
            return PhaseThreeBVerdict(
                should_execute=False,
                adjusted_confidence=0.0,
                position_scale=0.0,
                reasoning=f"Error: {str(e)[:50]}"
            )

    def get_stats(self) -> dict:
        """Return statistics"""
        total = self.stats["total_reviewed"]
        if total == 0:
            approval_rate = 0.0
        else:
            approval_rate = self.stats["approved"] / total * 100

        return {
            "total_reviewed": total,
            "approved": self.stats["approved"],
            "rejected": self.stats["rejected"],
            "approval_rate_pct": approval_rate,
        }
