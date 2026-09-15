#!/usr/bin/env python3
"""
Test individual indicators and pick winners
Strategy: Test baseline, then add ONE indicator at a time
"""

import json
from datetime import datetime
from advanced_charts import AdvancedChartAnalyzer

class IndicatorTester:
    """Test each indicator's impact"""

    def __init__(self):
        self.analyzer = AdvancedChartAnalyzer()
        self.results = {}

    def test_indicator(self, symbol, indicator_name):
        """
        Test one indicator on a symbol
        Returns: boost amount (0-100)
        """

        try:
            analysis = self.analyzer.get_chart_analysis(symbol)
            if not analysis:
                return None

            # Extract specific indicator
            if indicator_name == "moving_average":
                return self._score_ma_confluence(analysis)
            elif indicator_name == "pivot_points":
                return self._score_pivot_points(analysis)
            elif indicator_name == "volume_profile":
                return self._score_volume_profile(analysis)
            elif indicator_name == "atr_breakout":
                return self._score_atr(analysis)
            elif indicator_name == "fibonacci":
                return self._score_fibonacci(analysis)

        except Exception as e:
            print(f"Error testing {indicator_name} on {symbol}: {e}")
            return None

    def _score_ma_confluence(self, analysis):
        """Score moving average confluence impact"""
        ma = analysis.get("moving_average_confluence", {})
        signal = ma.get("signal", "")

        # Scores for each signal
        scores = {
            "strong_bullish": 20,
            "bullish_cross": 10,
            "strong_bearish": -15,
            "bearish_cross": -8,
            "none": 0
        }
        return scores.get(signal, 0)

    def _score_pivot_points(self, analysis):
        """Score pivot points impact"""
        pivots = analysis.get("pivot_points", {})
        zone = pivots.get("zone", "")

        scores = {
            "above_R2_buy": 15,
            "R1_to_R2_strong": 10,
            "P_to_R1_neutral": 0,
            "S1_to_P_neutral": 0,
            "S2_to_S1_weak": -5,
            "below_S2_sell": -10
        }
        return scores.get(zone, 0)

    def _score_volume_profile(self, analysis):
        """Score volume profile impact"""
        vp = analysis.get("volume_profile", {})
        signal = vp.get("signal", "")

        scores = {
            "at_support": 12,
            "at_resistance": -10,
            "midpoint": 0
        }
        return scores.get(signal, 0)

    def _score_atr(self, analysis):
        """Score ATR breakout impact"""
        atr = analysis.get("atr_breakout", {})
        if atr.get("breakout"):
            return 8
        return 0

    def _score_fibonacci(self, analysis):
        """Score Fibonacci impact"""
        fib = analysis.get("fibonacci_levels", {})
        nearest = fib.get("nearest_level", "")

        # Trading near key Fibonacci levels is significant
        scores = {
            "618": 10,  # Most important level
            "382": 5,
            "500": 3,
            "786": 8,
        }
        return scores.get(nearest, 0)

    def run_test_suite(self, symbols=None):
        """Test each indicator on multiple symbols"""

        if symbols is None:
            symbols = ["INTC", "AMD", "NVDA", "AAPL", "MSFT"]

        indicators = [
            "moving_average",
            "pivot_points",
            "volume_profile",
            "atr_breakout",
            "fibonacci"
        ]

        print("\n" + "="*80)
        print("INDIVIDUAL INDICATOR TEST")
        print("="*80 + "\n")

        results = {}

        for indicator in indicators:
            print(f"🔍 Testing: {indicator}")
            scores = []

            for symbol in symbols:
                score = self.test_indicator(symbol, indicator)
                if score is not None:
                    scores.append(score)
                    print(f"   {symbol}: {score:+d}")

            if scores:
                avg_score = sum(scores) / len(scores)
                impact = "✅ POSITIVE" if avg_score > 2 else "⚠️ MIXED" if avg_score > -2 else "❌ NEGATIVE"
                results[indicator] = {
                    "scores": scores,
                    "avg_score": avg_score,
                    "impact": impact,
                    "samples": len(scores)
                }
                print(f"   Average impact: {avg_score:+.1f} {impact}\n")

        # Rank indicators
        print("="*80)
        print("RANKING: Best to Worst")
        print("="*80 + "\n")

        ranked = sorted(results.items(), key=lambda x: x[1]["avg_score"], reverse=True)

        print(f"{'Rank':<6} {'Indicator':<25} {'Avg Score':<12} {'Verdict':<15}")
        print("-" * 60)

        for rank, (indicator, data) in enumerate(ranked, 1):
            print(f"{rank:<6} {indicator:<25} {data['avg_score']:+.1f}{'':<10} {data['impact']:<15}")

        # Recommendations
        print("\n" + "="*80)
        print("RECOMMENDATIONS")
        print("="*80 + "\n")

        print("🟢 ADD THESE (avg_score > +3):")
        for indicator, data in ranked:
            if data['avg_score'] > 3:
                print(f"   ✅ {indicator} (+{data['avg_score']:.1f})")

        print("\n🟡 MAYBE ADD (avg_score > 0):")
        for indicator, data in ranked:
            if 0 < data['avg_score'] <= 3:
                print(f"   ⚠️ {indicator} (+{data['avg_score']:.1f})")

        print("\n🔴 DON'T ADD (avg_score <= 0):")
        for indicator, data in ranked:
            if data['avg_score'] <= 0:
                print(f"   ❌ {indicator} ({data['avg_score']:+.1f})")

        # Save results
        results_data = {
            "timestamp": datetime.now().isoformat(),
            "test_symbols": symbols,
            "indicators": results,
            "ranked": [(ind, data['avg_score']) for ind, data in ranked]
        }

        with open("indicator_scores.json", "w") as f:
            json.dump(results_data, f, indent=2, default=str)

        print(f"\n💾 Results saved: indicator_scores.json")
        print("="*80 + "\n")

        return results


if __name__ == "__main__":
    tester = IndicatorTester()
    tester.run_test_suite()
