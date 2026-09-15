#!/usr/bin/env python3
"""
Ensemble Trading System
- Combines Llama + FinRL predictions
- Weighted voting for better accuracy
- Confidence calibration
"""

class EnsembleAnalyzer:
    """Combine multiple AI models for better decisions"""

    def __init__(self, llama_weight=0.6, finrl_weight=0.4):
        """
        Initialize ensemble

        Args:
            llama_weight: How much to trust Llama (0.0-1.0)
            finrl_weight: How much to trust FinRL (0.0-1.0)
        """
        self.llama_weight = llama_weight
        self.finrl_weight = finrl_weight

        # Validate weights sum to 1
        total = llama_weight + finrl_weight
        self.llama_weight = llama_weight / total
        self.finrl_weight = finrl_weight / total

    def combine_signals(self, llama_confidence, finrl_signal, finrl_prob):
        """
        Combine Llama + FinRL into single confidence score

        Args:
            llama_confidence: Llama's confidence (0-100)
            finrl_signal: FinRL action ("BUY", "HOLD", "SELL")
            finrl_prob: FinRL probability (0-1)

        Returns:
            dict with combined_confidence and decision
        """
        # Convert FinRL probability to 0-100 scale
        finrl_confidence = finrl_prob * 100

        # Weight the scores
        combined = (
            llama_confidence * self.llama_weight +
            finrl_confidence * self.finrl_weight
        )

        # Apply signal modifier
        if finrl_signal == "SELL":
            combined *= 0.5  # Reduce confidence if FinRL says sell
        elif finrl_signal == "HOLD":
            combined *= 0.8  # Slightly reduce if FinRL says hold

        # Determine action
        decision = "BUY" if combined >= 65 else "SKIP"

        return {
            "llama_score": llama_confidence,
            "finrl_score": finrl_confidence,
            "finrl_signal": finrl_signal,
            "combined_confidence": round(combined, 1),
            "decision": decision,
            "reasoning": self._get_reasoning(
                llama_confidence, finrl_confidence, finrl_signal
            ),
        }

    def _get_reasoning(self, llama_score, finrl_score, finrl_signal):
        """Explain the ensemble decision"""
        reasons = []

        if llama_score >= 70:
            reasons.append(f"Llama bullish ({llama_score}%)")
        elif llama_score < 50:
            reasons.append(f"Llama bearish ({llama_score}%)")

        if finrl_score >= 70:
            reasons.append(f"FinRL bullish ({finrl_score:.0f}%)")
        elif finrl_score < 50:
            reasons.append(f"FinRL bearish ({finrl_score:.0f}%)")

        if finrl_signal == "SELL":
            reasons.append("FinRL suggests caution (SELL signal)")

        if not reasons:
            reasons.append("Mixed signals - using threshold")

        return " + ".join(reasons)

    def get_adaptive_threshold(self, win_rate, market_regime="neutral"):
        """
        Adjust threshold based on performance

        Args:
            win_rate: Recent win rate (0-1)
            market_regime: "bull", "bear", or "neutral"

        Returns:
            Recommended confidence threshold (0-100)
        """
        base_threshold = 65

        # Adjust for win rate
        if win_rate >= 0.7:
            base_threshold -= 10  # Lower bar if performing well
        elif win_rate < 0.4:
            base_threshold += 15  # Higher bar if performing poorly

        # Adjust for market regime
        if market_regime == "bull":
            base_threshold -= 5  # Easier in bull market
        elif market_regime == "bear":
            base_threshold += 10  # Harder in bear market

        return max(50, min(80, base_threshold))  # Clamp 50-80


# Test
if __name__ == "__main__":
    ensemble = EnsembleAnalyzer(llama_weight=0.6, finrl_weight=0.4)

    # Test case 1: Both bullish
    result1 = ensemble.combine_signals(
        llama_confidence=75,
        finrl_signal="BUY",
        finrl_prob=0.72
    )
    print("Case 1 (Both bullish):")
    print(f"  Combined confidence: {result1['combined_confidence']}%")
    print(f"  Decision: {result1['decision']}")
    print(f"  Reasoning: {result1['reasoning']}")
    print()

    # Test case 2: Llama bullish, FinRL cautious
    result2 = ensemble.combine_signals(
        llama_confidence=80,
        finrl_signal="HOLD",
        finrl_prob=0.55
    )
    print("Case 2 (Llama bullish, FinRL hold):")
    print(f"  Combined confidence: {result2['combined_confidence']}%")
    print(f"  Decision: {result2['decision']}")
    print(f"  Reasoning: {result2['reasoning']}")
    print()

    # Test case 3: Disagreement
    result3 = ensemble.combine_signals(
        llama_confidence=60,
        finrl_signal="SELL",
        finrl_prob=0.35
    )
    print("Case 3 (Disagreement):")
    print(f"  Combined confidence: {result3['combined_confidence']}%")
    print(f"  Decision: {result3['decision']}")
    print(f"  Reasoning: {result3['reasoning']}")
