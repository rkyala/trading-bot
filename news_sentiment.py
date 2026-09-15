#!/usr/bin/env python3
"""
News Sentiment Analyzer: Lightweight keyword-based sentiment analysis

No NLTK required - uses simple keyword matching for speed and reliability
Perfect for real-time trading decisions
"""

import logging
import re

log = logging.getLogger(__name__)


class NewsSentimentAnalyzer:
    """Analyze sentiment of news headlines"""

    def __init__(self):
        """Initialize with sentiment keywords"""
        # Positive keywords
        self.positive_keywords = [
            "beat",
            "bullish",
            "surge",
            "rally",
            "jump",
            "gain",
            "up",
            "rise",
            "above",
            "outperform",
            "strong",
            "growth",
            "profit",
            "positive",
            "upgrade",
            "approval",
            "success",
            "breakthrough",
            "record",
            "high",
            "rally",
            "recovery",
            "rebound",
            "exceed",
            "beat",
            "advantage",
            "win",
            "leading",
            "innovative",
            "expansion",
            "growth",
        ]

        # Negative keywords
        self.negative_keywords = [
            "miss",
            "bearish",
            "crash",
            "plunge",
            "drop",
            "loss",
            "down",
            "fall",
            "below",
            "underperform",
            "weak",
            "decline",
            "loss",
            "negative",
            "downgrade",
            "recall",
            "fail",
            "broke",
            "cut",
            "worst",
            "low",
            "slump",
            "correction",
            "selloff",
            "warning",
            "risk",
            "concern",
            "delay",
            "problem",
            "challenge",
        ]

        # Strengthen keywords (double the impact)
        self.strong_keywords = [
            "beat",
            "miss",
            "surge",
            "crash",
            "bullish",
            "bearish",
            "record",
            "worst",
            "profit",
            "loss",
        ]

    def analyze(self, text):
        """
        Analyze sentiment of text

        Args:
            text: News headline or summary

        Returns:
            {
                "sentiment": "POSITIVE" | "NEGATIVE" | "NEUTRAL",
                "confidence": 0-100,
                "score": -100 to +100
            }
        """

        if not text:
            return {"sentiment": "NEUTRAL", "confidence": 0, "score": 0}

        text_lower = text.lower()
        text_words = text_lower.split()

        # Count matches
        pos_count = 0
        neg_count = 0

        for word in text_words:
            # Clean word (remove punctuation)
            clean_word = re.sub(r"[^\w]", "", word)

            # Check positive
            if clean_word in self.positive_keywords:
                pos_count += 2 if clean_word in self.strong_keywords else 1

            # Check negative
            if clean_word in self.negative_keywords:
                neg_count += 2 if clean_word in self.strong_keywords else 1

        # Calculate score (-100 to +100)
        if pos_count + neg_count == 0:
            score = 0
            confidence = 0
        else:
            score = ((pos_count - neg_count) / (pos_count + neg_count)) * 100
            confidence = min(95, (pos_count + neg_count) * 15)  # Max 95%

        # Determine sentiment
        if score > 20:
            sentiment = "POSITIVE"
        elif score < -20:
            sentiment = "NEGATIVE"
        else:
            sentiment = "NEUTRAL"

        return {
            "sentiment": sentiment,
            "confidence": int(confidence),
            "score": int(score),
            "positive_signals": pos_count,
            "negative_signals": neg_count,
        }

    def combine_with_technical(self, technical_confidence, news_sentiment):
        """
        Combine technical confidence with news sentiment

        Args:
            technical_confidence: 0-100 (from mean-reversion signal)
            news_sentiment: {"sentiment": "POSITIVE|NEGATIVE|NEUTRAL", "confidence": 0-100}

        Returns:
            Adjusted confidence 0-100
        """

        if news_sentiment["sentiment"] == "POSITIVE":
            # Boost confidence
            boost = 1 + (news_sentiment["confidence"] / 500)  # Up to +20% boost
            adjusted = technical_confidence * boost
        elif news_sentiment["sentiment"] == "NEGATIVE":
            # Reduce confidence
            reduction = 1 - (news_sentiment["confidence"] / 500)  # Down to -20% reduction
            adjusted = technical_confidence * reduction
        else:
            # Neutral - no change
            adjusted = technical_confidence

        return min(95, adjusted)  # Cap at 95%


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    analyzer = NewsSentimentAnalyzer()

    # Test cases
    test_headlines = [
        "Intel beats earnings expectations, raises guidance",
        "AMD stock crashes on disappointing earnings miss",
        "NVIDIA announces record profits, strong demand",
        "Tesla issues recall on new models",
        "Apple shows steady growth in latest quarter",
    ]

    print("\nNews Sentiment Analysis Test\n")
    print("-" * 70)

    for headline in test_headlines:
        result = analyzer.analyze(headline)
        print(f"\nHeadline: {headline}")
        print(
            f"Sentiment: {result['sentiment']:8s} | "
            f"Confidence: {result['confidence']:3d}% | "
            f"Score: {result['score']:+4d}"
        )

        # Simulate combining with technical signal
        tech_conf = 75
        adjusted = analyzer.combine_with_technical(tech_conf, result)
        print(f"Technical: {tech_conf}% → Adjusted: {adjusted:.0f}%")

    print("\n" + "-" * 70 + "\n")
