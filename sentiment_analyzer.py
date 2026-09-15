#!/usr/bin/env python3
"""
Sentiment Analyzer - Uses Llama 2 to analyze market sentiment
Part of Option 3: Sentiment Hybrid Strategy

Analyzes market data and generates sentiment signals for trading
"""

import logging
import json
from datetime import datetime, timedelta

log = logging.getLogger(__name__)


class SentimentAnalyzer:
    """Analyze market sentiment using Llama 2"""

    def __init__(self):
        """Initialize sentiment analyzer"""
        try:
            from local_llm_wrapper import LocalLLMWrapper
            self.llm = LocalLLMWrapper()
            self.available = self.llm.is_available()
            if self.available:
                log.info("✅ Sentiment analyzer ready (Llama 2)")
            else:
                log.warning("⚠️  Llama 2 not available, using rule-based sentiment")
        except Exception as e:
            log.warning(f"Sentiment analyzer init error: {e}, using rules")
            self.llm = None
            self.available = False

    def analyze_sentiment(self, symbol, price_data, context=""):
        """
        Analyze sentiment for a symbol using Llama 2

        Args:
            symbol: Stock ticker
            price_data: Dict with price info
                {
                    "current_price": 102.50,
                    "change_pct": 5.2,
                    "volume_change": 1.5,
                    "trend": "up"
                }
            context: Additional context (news, events)

        Returns:
            {
                "sentiment": "bullish" | "neutral" | "bearish",
                "confidence": 0-100,
                "reasoning": "..."
            }
        """

        if self.available and self.llm:
            return self._analyze_with_llm(symbol, price_data, context)
        else:
            return self._analyze_with_rules(symbol, price_data, context)

    def _analyze_with_llm(self, symbol, price_data, context):
        """Use Llama 2 for sentiment analysis"""
        try:
            prompt = f"""Analyze market sentiment for {symbol}.

Price Data:
- Current Price: ${price_data.get('current_price', 0):.2f}
- Change: {price_data.get('change_pct', 0):+.1f}%
- Volume Change: {price_data.get('volume_change', 0):+.1f}%
- Trend: {price_data.get('trend', 'unknown')}
- RSI: {price_data.get('rsi', 50):.0f}
- MACD: {price_data.get('macd_signal', 'neutral')}

Context: {context or 'Market conditions normal'}

Assess sentiment as: BULLISH, NEUTRAL, or BEARISH
Provide confidence 0-100 and brief reasoning.

Format response as JSON:
{{
  "sentiment": "BULLISH|NEUTRAL|BEARISH",
  "confidence": <0-100>,
  "reasoning": "<brief explanation>"
}}"""

            decision = self.llm.analyze_trade(
                symbol=symbol,
                pct_change=price_data.get("change_pct", 0),
                anomaly_score=abs(price_data.get("change_pct", 0)) * 15,
                regime=price_data.get("trend", "unknown")
            )

            # Map Llama 2 decision to sentiment
            action = decision.get("action", "HOLD")
            conf = decision.get("confidence", 50)

            if action == "BUY":
                sentiment = "BULLISH"
            elif action == "SKIP":
                sentiment = "BEARISH"
            else:
                sentiment = "NEUTRAL"

            return {
                "sentiment": sentiment,
                "confidence": conf,
                "reasoning": decision.get("reason", "Llama 2 analysis")
            }

        except Exception as e:
            log.warning(f"LLM sentiment error: {e}, using rules")
            return self._analyze_with_rules(symbol, price_data, context)

    def _analyze_with_rules(self, symbol, price_data, context):
        """Fallback: Rule-based sentiment analysis"""
        change = price_data.get("change_pct", 0)
        volume = price_data.get("volume_change", 0)
        rsi = price_data.get("rsi", 50)
        macd = price_data.get("macd_signal", "neutral")

        # Score components
        price_score = 0
        volume_score = 0
        rsi_score = 0
        macd_score = 0

        # Price momentum (0-30 points)
        if change > 5:
            price_score = 30
        elif change > 2:
            price_score = 20
        elif change > 0:
            price_score = 10
        elif change < -5:
            price_score = -30
        elif change < -2:
            price_score = -20
        else:
            price_score = -10

        # Volume confirmation (0-20 points)
        if volume > 20:
            volume_score = 20
        elif volume > 5:
            volume_score = 10
        elif volume < -20:
            volume_score = -20
        elif volume < -5:
            volume_score = -10

        # RSI levels (0-30 points)
        if rsi < 30:
            rsi_score = 30  # Oversold = bullish
        elif rsi < 40:
            rsi_score = 15
        elif rsi > 70:
            rsi_score = -30  # Overbought = bearish
        elif rsi > 60:
            rsi_score = -15

        # MACD signal (0-20 points)
        if macd == "bullish":
            macd_score = 20
        elif macd == "bearish":
            macd_score = -20

        # Total score (-100 to +100)
        total_score = price_score + volume_score + rsi_score + macd_score

        # Convert to sentiment
        if total_score > 40:
            sentiment = "BULLISH"
            confidence = min(100, 50 + abs(total_score) / 2)
        elif total_score < -40:
            sentiment = "BEARISH"
            confidence = min(100, 50 + abs(total_score) / 2)
        else:
            sentiment = "NEUTRAL"
            confidence = 50

        reasoning = f"Score: {total_score} (Price:{price_score:+d}, Vol:{volume_score:+d}, RSI:{rsi_score:+d}, MACD:{macd_score:+d})"

        return {
            "sentiment": sentiment,
            "confidence": int(confidence),
            "reasoning": reasoning
        }

    def combine_signals(self, technical_signal, sentiment_signal, weights=None):
        """
        Combine technical and sentiment signals

        Args:
            technical_signal: {"action": "BUY", "confidence": 75}
            sentiment_signal: {"sentiment": "BULLISH", "confidence": 80}
            weights: {"technical": 0.6, "sentiment": 0.4}

        Returns:
            Combined signal with adjusted confidence
        """

        if weights is None:
            weights = {"technical": 0.6, "sentiment": 0.4}

        # Get sentiment score (-100 to +100)
        sentiment = sentiment_signal.get("sentiment", "NEUTRAL")
        if sentiment == "BULLISH":
            sentiment_score = sentiment_signal.get("confidence", 50)
        elif sentiment == "BEARISH":
            sentiment_score = -sentiment_signal.get("confidence", 50)
        else:
            sentiment_score = 0

        # Get technical score
        action = technical_signal.get("action", "HOLD")
        if action == "BUY":
            technical_score = technical_signal.get("confidence", 50)
        elif action == "SKIP":
            technical_score = -technical_signal.get("confidence", 50)
        else:
            technical_score = 0

        # Combine with weights
        combined_score = (
            technical_score * weights["technical"] +
            sentiment_score * weights["sentiment"]
        )

        # Determine final action
        if combined_score > 40:
            final_action = "BUY"
        elif combined_score < -40:
            final_action = "SKIP"
        else:
            final_action = "HOLD"

        final_confidence = abs(combined_score)

        return {
            "symbol": technical_signal.get("symbol", "?"),
            "action": final_action,
            "confidence": min(100, int(final_confidence)),
            "technical_score": technical_score,
            "sentiment_score": sentiment_score,
            "combined_score": combined_score,
            "reasoning": f"Tech:{technical_score:+.0f} ({action}) + Sentiment:{sentiment_score:+.0f} ({sentiment})"
        }
