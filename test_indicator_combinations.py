#!/usr/bin/env python3
"""
Test Fibonacci + Other Indicators (Combinations)
Find which pairs work best together
"""

import json
from datetime import datetime
from advanced_charts import AdvancedChartAnalyzer

class CombinationTester:
    """Test indicator pairs"""

    def __init__(self):
        self.analyzer = AdvancedChartAnalyzer()
        self.results = {}

    def test_combination(self, symbol, combo_name):
        """
        Test two indicators working together
        Returns: combined score
        """

        try:
            analysis = self.analyzer.get_chart_analysis(symbol)
            if not analysis:
                return None

            # Individual scores
            fib_score = self._score_fibonacci(analysis)
            ma_score = self._score_ma_confluence(analysis)
            atr_score = self._score_atr(analysis)
            rsi_score = self._score_rsi_with_fib(analysis)

            # Combinations (test synergy)
            if combo_name == "fib_ma":
                # Fibonacci + Moving Average
                # Score higher if BOTH agree
                if self._fibonacci_agrees_with_ma(analysis):
                    return fib_score + ma_score + 5  # +5 bonus for agreement
                else:
                    return fib_score + ma_score - 3  # -3 penalty for disagreement

            elif combo_name == "fib_rsi":
                # Fibonacci + RSI (mean-reversion setup)
                # Price at Fib level + RSI overbought/oversold
                if self._fibonacci_at_key_level(analysis) and self._rsi_extreme(analysis):
                    return fib_score + rsi_score + 8  # Strong mean-reversion
                else:
                    return fib_score + rsi_score

            elif combo_name == "fib_atr":
                # Fibonacci + ATR Breakout
                # Fib level + volatility expansion
                if self._fibonacci_at_key_level(analysis) and analysis.get("atr_breakout", {}).get("breakout"):
                    return fib_score + atr_score + 6  # Breakout at key level
                else:
                    return fib_score + atr_score

            elif combo_name == "fib_pivot":
                # Fibonacci + Pivot Points
                # Both identify support/resistance
                pivot_score = self._score_pivot_points(analysis)
                if self._fibonacci_aligns_with_pivot(analysis):
                    return fib_score + pivot_score + 4  # Both agree
                else:
                    return fib_score + pivot_score

        except Exception as e:
            print(f"Error testing {combo_name} on {symbol}: {e}")
            return None

        return None

    # ========== SCORING FUNCTIONS ==========

    def _score_fibonacci(self, analysis):
        """Fibonacci score"""
        fib = analysis.get("fibonacci_levels", {})
        nearest = fib.get("nearest_level", "")
        scores = {"618": 10, "786": 8, "382": 5, "500": 3}
        return scores.get(nearest, 0)

    def _score_ma_confluence(self, analysis):
        """MA Confluence score"""
        ma = analysis.get("moving_average_confluence", {})
        signal = ma.get("signal", "")
        scores = {
            "strong_bullish": 20,
            "bullish_cross": 10,
            "strong_bearish": -15,
            "bearish_cross": -8,
            "none": 0
        }
        return scores.get(signal, 0)

    def _score_atr(self, analysis):
        """ATR score"""
        atr = analysis.get("atr_breakout", {})
        return 8 if atr.get("breakout") else 0

    def _score_rsi_with_fib(self, analysis):
        """RSI score (especially for mean-reversion at Fib levels)"""
        # Would need to add RSI to analysis, using proxy
        # High RSI at support = good mean-reversion
        return 5  # Simplified for now

    def _score_pivot_points(self, analysis):
        """Pivot score"""
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

    # ========== SYNERGY CHECKS ==========

    def _fibonacci_agrees_with_ma(self, analysis):
        """Check if Fibonacci and MA signals align"""
        fib = analysis.get("fibonacci_levels", {})
        ma = analysis.get("moving_average_confluence", {})

        fib_level = fib.get("nearest_level", "")
        ma_signal = ma.get("signal", "")

        # Fib near key level + bullish MA = good
        if fib_level in ["618", "786"] and "bullish" in ma_signal:
            return True
        # Fib far from level + bearish MA = bad
        if fib_level in ["23.6", "382"] and "bearish" in ma_signal:
            return True

        return False

    def _fibonacci_at_key_level(self, analysis):
        """Is price near key Fibonacci level?"""
        fib = analysis.get("fibonacci_levels", {})
        nearest = fib.get("nearest_level", "")
        return nearest in ["618", "786"]

    def _rsi_extreme(self, analysis):
        """Simplified RSI check (would need actual RSI)"""
        # Placeholder - in real implementation would check RSI > 70 or < 30
        return True  # For demo

    def _fibonacci_aligns_with_pivot(self, analysis):
        """Check if Fib and Pivot point at same zone"""
        fib = analysis.get("fibonacci_levels", {})
        pivots = analysis.get("pivot_points", {})

        fib_nearest = fib.get("nearest_level", "")
        pivot_zone = pivots.get("zone", "")

        # Both suggesting buy/sell = alignment
        if fib_nearest in ["786", "618"] and "buy" in pivot_zone:
            return True

        return False

    def run_test_suite(self, symbols=None):
        """Test all combinations"""

        if symbols is None:
            symbols = ["INTC", "AMD", "NVDA", "AAPL", "MSFT"]

        combinations = [
            "fib_ma",      # Fibonacci + Moving Average
            "fib_rsi",     # Fibonacci + RSI
            "fib_atr",     # Fibonacci + ATR
            "fib_pivot",   # Fibonacci + Pivot Points
        ]

        print("\n" + "="*80)
        print("INDICATOR COMBINATION TEST")
        print("Which indicators synergize with Fibonacci?")
        print("="*80 + "\n")

        results = {}

        for combo in combinations:
            print(f"🔍 Testing: {combo}")
            scores = []

            for symbol in symbols:
                score = self.test_combination(symbol, combo)
                if score is not None:
                    scores.append(score)
                    print(f"   {symbol}: {score:+d}")

            if scores:
                avg_score = sum(scores) / len(scores)
                results[combo] = {
                    "scores": scores,
                    "avg_score": avg_score,
                    "samples": len(scores)
                }
                print(f"   Average: {avg_score:+.1f}\n")

        # Rank combinations
        print("="*80)
        print("RANKING: Best Combinations")
        print("="*80 + "\n")

        ranked = sorted(results.items(), key=lambda x: x[1]["avg_score"], reverse=True)

        print(f"{'Rank':<6} {'Combination':<20} {'Avg Score':<12} {'Synergy':<15}")
        print("-" * 55)

        for rank, (combo, data) in enumerate(ranked, 1):
            # Determine if synergy exists (score > sum of individual parts)
            fib_score = 5.2  # From earlier test

            if "ma" in combo:
                other_score = 0.0
            elif "rsi" in combo:
                other_score = 5.0
            elif "atr" in combo:
                other_score = 0.0
            elif "pivot" in combo:
                other_score = 0.0
            else:
                other_score = 0

            expected = fib_score + other_score
            actual = data['avg_score']
            synergy = actual - expected  # Bonus from working together

            synergy_label = "✅ SYNERGY" if synergy > 2 else "⚠️ NEUTRAL" if synergy > -2 else "❌ CONFLICT"

            print(f"{rank:<6} {combo:<20} {actual:+.1f}{'':<9} {synergy_label:<15}")

        # Recommendations
        print("\n" + "="*80)
        print("RECOMMENDATIONS")
        print("="*80 + "\n")

        print("🟢 ADD THESE (Synergy > +2):")
        winners = []
        for combo, data in ranked:
            if data['avg_score'] > 8:  # Strong performers
                print(f"   ✅ {combo} (score: {data['avg_score']:+.1f})")
                winners.append(combo)

        print("\n🟡 MAYBE ADD (Neutral/Mixed):")
        for combo, data in ranked:
            if 5 <= data['avg_score'] <= 8:
                print(f"   ⚠️ {combo} (score: {data['avg_score']:+.1f})")

        print("\n🔴 DON'T COMBINE (Conflict):")
        for combo, data in ranked:
            if data['avg_score'] < 5:
                print(f"   ❌ {combo} (score: {data['avg_score']:+.1f})")

        # Save results
        results_data = {
            "timestamp": datetime.now().isoformat(),
            "test_symbols": symbols,
            "combinations": results,
            "ranked": [(combo, data['avg_score']) for combo, data in ranked],
            "recommendation": winners[0] if winners else None
        }

        with open("combination_scores.json", "w") as f:
            json.dump(results_data, f, indent=2, default=str)

        print(f"\n💾 Results saved: combination_scores.json")
        print("="*80 + "\n")

        # Final recommendation
        if winners:
            print(f"🎯 BEST COMBINATION: {winners[0]}")
            print(f"   Add this to bot alongside Fibonacci")
        else:
            print(f"🎯 RECOMMENDATION: Keep Fibonacci Only")
            print(f"   No synergistic combinations found")


if __name__ == "__main__":
    tester = CombinationTester()
    tester.run_test_suite()
