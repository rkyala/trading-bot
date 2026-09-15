#!/usr/bin/env python3
"""
Simple Regime Detection (no external API calls)
Uses price position and volatility from bot's internal calculations
"""

class SimpleRegimeFilter:
    """
    Simple regime detection without needing ADX calculation

    TRENDING Signals:
    - Price near 52-week high (within 5%)
    - High volatility expansion

    RANGING Signals:
    - Price in middle of 52-week range
    - Low volatility compression
    """

    def __init__(self):
        pass

    def detect_regime(self, current_price, high_52w, low_52w, current_volatility, avg_volatility):
        """
        Simple regime detection based on price position and volatility

        Returns: (regime: str, confidence: float 0-100)
        """

        # Calculate price position in range (0-100, 0=52w low, 100=52w high)
        range_width = high_52w - low_52w
        if range_width == 0:
            price_position = 50
        else:
            price_position = ((current_price - low_52w) / range_width) * 100

        # Volatility ratio
        vol_ratio = current_volatility / avg_volatility if avg_volatility > 0 else 1

        # Determine regime
        if price_position > 75 and vol_ratio > 0.9:
            # High price + expanding volatility = TRENDING (breakout mode)
            regime = "TRENDING"
            confidence = min(100, 50 + (price_position - 75) + (vol_ratio - 1) * 50)

        elif price_position < 25 and vol_ratio < 0.8:
            # Low price + compressing volatility = RANGING (mean reversion mode)
            regime = "RANGING"
            confidence = min(100, 50 + (25 - price_position) + (0.8 - vol_ratio) * 50)

        elif 35 < price_position < 65 and 0.7 < vol_ratio < 1.3:
            # Middle of range + normal volatility = TRANSITION
            regime = "TRANSITION"
            confidence = 50

        else:
            # Default based on price position
            if price_position > 60:
                regime = "TRENDING"
                confidence = min(100, (price_position - 50) * 2)
            else:
                regime = "RANGING"
                confidence = min(100, (50 - price_position) * 2)

        return regime, confidence

    def route_capital(self, regime):
        """
        Route capital allocation based on regime
        Returns: (breakout_allocation: %, mean_reversion_allocation: %)
        """
        if regime == "TRENDING":
            return 100, 0, "Breakout (100%)"
        elif regime == "RANGING":
            return 0, 100, "Mean-Reversion (100%)"
        else:
            return 50, 50, "Dual-Strategy (50/50)"


# Example usage
if __name__ == "__main__":
    regime_filter = SimpleRegimeFilter()

    # Test cases
    test_cases = [
        {
            "symbol": "AAPL",
            "price": 225,
            "high_52w": 235,
            "low_52w": 150,
            "current_vol": 25,
            "avg_vol": 20,
            "description": "Near 52-week high, expanding volatility"
        },
        {
            "symbol": "MSFT",
            "price": 350,
            "high_52w": 415,
            "low_52w": 280,
            "current_vol": 18,
            "avg_vol": 22,
            "description": "Middle of range, compressing volatility"
        },
        {
            "symbol": "NVDA",
            "price": 120,
            "high_52w": 140,
            "low_52w": 60,
            "current_vol": 20,
            "avg_vol": 25,
            "description": "Low in range, compressing volatility"
        }
    ]

    print("=" * 100)
    print("SIMPLE REGIME DETECTION (No API Calls)")
    print("=" * 100)
    print()

    for test in test_cases:
        regime, confidence = regime_filter.detect_regime(
            test["price"],
            test["high_52w"],
            test["low_52w"],
            test["current_vol"],
            test["avg_vol"]
        )

        bo_alloc, mr_alloc, allocation = regime_filter.route_capital(regime)

        print(f"{test['symbol']:6} | Regime: {regime:11} | Confidence: {confidence:5.1f}%")
        print(f"        | {test['description']}")
        print(f"        | Price: ${test['price']} (52w: ${test['low_52w']}-${test['high_52w']})")
        print(f"        | Volatility: {test['current_vol']} vs avg {test['avg_vol']} (ratio: {test['current_vol']/test['avg_vol']:.2f}x)")
        print(f"        | Capital Allocation: {allocation}")
        print()
