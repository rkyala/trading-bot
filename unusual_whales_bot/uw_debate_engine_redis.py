"""
Phase 3B: Deterministic Debate Engine with Redis Sentiment Cache

Integration point: Feeds sentiment from Redis cache into confidence adjustment.
Zero-latency lookups (microsecond Redis gets, no ML inference in critical path).

This is the PRODUCTION-READY debate engine that combines:
1. Gymnasium PPO signal (RL-based direction)
2. Qwen classifier confidence
3. ATR-based volatility sizing
4. Redis sentiment confluence (optional)

Toggle: SENTIMENT_ENABLED in uw_config.py
"""

import logging
from typing import Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    """Flow signal from Gymnasium or Qwen"""

    direction: str  # "BULLISH_SWEEP", "BEARISH_SWEEP", "NEUTRAL"
    confidence: float  # 0.0 - 1.0
    option_type: str  # "CALL" or "PUT"
    symbol: str  # "SPX", "NDX", "RUT"


@dataclass
class DebateVerdict:
    """Final trading decision after debate"""

    should_execute: bool
    adjusted_confidence: float
    final_position_size: int
    reasoning: str


class DeterministicDebateEngine:
    """
    Lightweight debate engine (no LLM, pure deterministic logic).

    Rules:
    1. Flow-sentiment alignment check
    2. ATR-based position sizing
    3. Hard confidence gatekeeper
    4. Confidence capping at 1.0
    """

    def __init__(
        self,
        min_confidence_threshold: float = 0.75,
        use_sentiment: bool = False,
        redis_config=None,
    ):
        self.min_confidence_threshold = min_confidence_threshold
        self.use_sentiment = use_sentiment
        self.redis_config = redis_config
        self.stats = {
            "trades_evaluated": 0,
            "trades_approved": 0,
            "trades_rejected_confidence": 0,
            "trades_boosted_sentiment": 0,
            "trades_penalized_sentiment": 0,
        }

    def _get_sentiment(self, symbol: str) -> str:
        """Fetch pre-computed sentiment from Redis (microsecond latency)"""
        if not self.use_sentiment or self.redis_config is None:
            return "neutral"

        try:
            sentiment = self.redis_config.get_sentiment(symbol)
            return sentiment
        except Exception as e:
            logger.warning(f"Sentiment lookup failed for {symbol}: {e}")
            return "neutral"

    def evaluate_and_size(
        self,
        flow: TradeSignal,
        atr: float,
        base_position_size: int = 1,
    ) -> Optional[DebateVerdict]:
        """
        Main debate logic: Flow + Sentiment → Verdict + Position Size

        Args:
            flow: TradeSignal from Gymnasium/Qwen (direction + confidence)
            atr: 14-period ATR for volatility sizing
            base_position_size: Starting position (usually 1 contract)

        Returns:
            DebateVerdict with execution decision, or None if rejected
        """
        self.stats["trades_evaluated"] += 1

        # =====================================================================
        # STEP 1: Get sentiment context (if enabled)
        # =====================================================================
        sentiment = self._get_sentiment(flow.symbol)
        confidence = flow.confidence
        reasoning = []

        # =====================================================================
        # STEP 2: Flow-Sentiment Confluence Adjustment
        # =====================================================================
        # Check if flow direction aligns with sentiment
        flow_bullish = flow.option_type == "CALL"
        sentiment_positive = sentiment == "positive"

        if self.use_sentiment:
            if (flow_bullish and sentiment_positive) or (
                not flow_bullish and not sentiment_positive
            ):
                # ALIGNMENT: Flow and sentiment agree
                confidence = min(1.0, confidence * 1.2)
                self.stats["trades_boosted_sentiment"] += 1
                reasoning.append(
                    f"✓ Confluence: {flow.option_type}+{sentiment} → +20% boost"
                )
            elif (flow_bullish and not sentiment_positive) or (
                not flow_bullish and sentiment_positive
            ):
                # DIVERGENCE: Flow and sentiment disagree
                confidence *= 0.8
                self.stats["trades_penalized_sentiment"] += 1
                reasoning.append(
                    f"⚠ Divergence: {flow.option_type} vs {sentiment} → -20% penalty"
                )
            else:
                # Neutral sentiment: no adjustment
                reasoning.append(f"→ Neutral sentiment: no adjustment")
        else:
            reasoning.append("(Sentiment disabled)")

        # =====================================================================
        # STEP 3: ATR-Based Volatility Sizing
        # =====================================================================
        # Higher ATR → smaller position (reduce risk in high-vol)
        # Lower ATR → larger position (increase size in stable market)

        atr_thresholds = {
            "SPX": {"low": 15, "high": 30},
            "NDX": {"low": 30, "high": 60},
            "RUT": {"low": 18, "high": 40},
        }

        symbol = flow.symbol
        thresholds = atr_thresholds.get(symbol, {"low": 20, "high": 40})
        low_atr = thresholds["low"]
        high_atr = thresholds["high"]

        if atr < low_atr:
            position_size_multiplier = 1.5  # Boost in low-vol
            vol_desc = "low"
        elif atr > high_atr:
            position_size_multiplier = 0.7  # Reduce in high-vol
            vol_desc = "high"
        else:
            position_size_multiplier = 1.0
            vol_desc = "normal"

        position_size = max(1, int(base_position_size * position_size_multiplier))
        reasoning.append(
            f"ATR=${atr:.1f} ({vol_desc}-vol) → Position size {position_size}x"
        )

        # =====================================================================
        # STEP 4: Hard Confidence Gatekeeper
        # =====================================================================
        if confidence < self.min_confidence_threshold:
            self.stats["trades_rejected_confidence"] += 1
            reasoning.append(
                f"❌ REJECTED: Confidence {confidence:.2f} < {self.min_confidence_threshold:.2f}"
            )
            return None

        # =====================================================================
        # STEP 5: Build Verdict
        # =====================================================================
        self.stats["trades_approved"] += 1
        confidence = min(1.0, confidence)  # Final cap at 1.0

        verdict = DebateVerdict(
            should_execute=True,
            adjusted_confidence=confidence,
            final_position_size=position_size,
            reasoning="\n".join(reasoning),
        )

        return verdict

    def log_stats(self):
        """Log debate engine statistics"""
        approval_rate = (
            self.stats["trades_approved"] / self.stats["trades_evaluated"] * 100
            if self.stats["trades_evaluated"] > 0
            else 0
        )

        logger.info("\n" + "=" * 80)
        logger.info("DEBATE ENGINE STATISTICS")
        logger.info("=" * 80)
        logger.info(f"Trades evaluated: {self.stats['trades_evaluated']}")
        logger.info(f"Trades approved: {self.stats['trades_approved']}")
        logger.info(f"  └─ Approval rate: {approval_rate:.1f}%")
        logger.info(f"Trades rejected (confidence): {self.stats['trades_rejected_confidence']}")

        if self.use_sentiment:
            logger.info(f"Trades boosted (sentiment): {self.stats['trades_boosted_sentiment']}")
            logger.info(
                f"Trades penalized (sentiment): {self.stats['trades_penalized_sentiment']}"
            )

        logger.info("=" * 80 + "\n")


# ============================================================================
# INTEGRATION EXAMPLE: Usage in uw_bot.py
# ============================================================================

INTEGRATION_EXAMPLE = """
# In uw_bot.py:execute_trade()

from uw_debate_engine_redis import DeterministicDebateEngine, TradeSignal
from uw_redis_config import get_redis_config
from uw_config import EXECUTION_MODE

class UnusualWhalesBot:
    def __init__(self, ...):
        # Initialize debate engine
        redis_config = get_redis_config() if EXECUTION_MODE.get("sentiment_enabled") else None
        self.debate_engine = DeterministicDebateEngine(
            min_confidence_threshold=0.75,
            use_sentiment=EXECUTION_MODE.get("sentiment_enabled", False),
            redis_config=redis_config,
        )

    async def execute_trade(self, alert, classification):
        # Build signal from Qwen classification
        flow_signal = TradeSignal(
            direction="BULLISH_SWEEP" if "CALL" in alert else "BEARISH_SWEEP",
            confidence=classification.confidence,
            option_type=alert.get("call_put", "CALL"),
            symbol=alert.get("symbol", "SPX"),
        )

        # Get ATR for volatility
        atr_14 = self.execution_safeguards.get_atr_14(symbol)

        # Run debate engine
        verdict = self.debate_engine.evaluate_and_size(
            flow=flow_signal,
            atr=atr_14,
            base_position_size=1,
        )

        if verdict is None:
            logger.info(f"❌ Trade rejected: {flow_signal.symbol}")
            self._send_alert(f"TRADE REJECTED: {symbol} - Debate verdict failed")
            return False

        # Place order with debate-adjusted position size
        logger.info(f"✓ Verdict:\\n{verdict.reasoning}")

        order_response = await self.robinhood_mcp.place_option_order(
            symbol=symbol,
            quantity=verdict.final_position_size,  # Use debate-sized quantity
            limit_price=plan.limit_price,
            ...
        )

        # Rest of execution...
"""
