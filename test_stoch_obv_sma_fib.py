#!/usr/bin/env python3
"""
Test: Fibonacci + Stochastic + OBV + SMA
Check if these 3 indicators synergize with Fibonacci
"""

import json
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np
from advanced_charts import AdvancedChartAnalyzer

class IndicatorComboTester:
    """Test Fib + Stochastic + OBV + SMA"""

    def __init__(self):
        self.analyzer = AdvancedChartAnalyzer()

    def test_combo(self, symbol):
        """Test the combination"""

        try:
            # Get analysis
            analysis = self.analyzer.get_chart_analysis(symbol)
            if not analysis:
                return None

            # Get historical data
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="60d")
            if hist.empty or len(hist) < 20:
                return None

            current_price = analysis.get("price", 0)

            # ===== 1. FIBONACCI SCORE =====
            fib = analysis.get("fibonacci_levels", {})
            nearest = fib.get("nearest_level", "")
            fib_scores = {"618": 10, "786": 8, "382": 5, "500": 3}
            fib_score = fib_scores.get(nearest, 0)

            # ===== 2. STOCHASTIC OSCILLATOR =====
            # K% = (Close - Low14) / (High14 - Low14) * 100
            low_14 = hist['Low'].tail(14).min()
            high_14 = hist['High'].tail(14).max()
            close = hist['Close'].iloc[-1]

            if high_14 != low_14:
                stoch_k = ((close - low_14) / (high_14 - low_14)) * 100
            else:
                stoch_k = 50

            # Score based on overbought/oversold
            if stoch_k > 80:
                stoch_score = 15  # Overbought = pullback opportunity
            elif stoch_k > 70:
                stoch_score = 10
            elif stoch_k > 50:
                stoch_score = 5
            elif stoch_k > 30:
                stoch_score = 0   # Neutral zone
            elif stoch_k > 20:
                stoch_score = -5  # Oversold
            else:
                stoch_score = -10

            # ===== 3. ON BALANCE VOLUME (OBV) =====
            # OBV = cumulative sum of volume based on close direction
            hist['OBV'] = (np.sign(hist['Close'].diff()) * hist['Volume']).fillna(0).cumsum()
            obv_current = hist['OBV'].iloc[-1]
            obv_prev = hist['OBV'].iloc[-5]  # 5 bars ago
            obv_trend = obv_current - obv_prev

            if obv_trend > 0:
                obv_score = 12  # Volume confirming uptrend
            elif obv_trend > 0:
                obv_score = 6   # Weak uptrend
            else:
                obv_score = -8  # Volume declining

            # ===== 4. SIMPLE MOVING AVERAGE =====
            sma_20 = hist['Close'].rolling(20).mean().iloc[-1]
            sma_50 = hist['Close'].rolling(50).mean().iloc[-1]
            sma_200 = hist['Close'].rolling(200).mean().iloc[-1]

            if current_price > sma_20 > sma_50 > sma_200:
                sma_score = 15  # Strong uptrend
            elif current_price > sma_20 > sma_50:
                sma_score = 10  # Moderate uptrend
            elif current_price > sma_20:
                sma_score = 5   # Weak uptrend
            elif current_price > sma_50:
                sma_score = 0   # Neutral
            else:
                sma_score = -10 # Downtrend

            # ===== SYNERGY BONUS =====
            synergy = 0

            # Bonus 1: Fib + Stochastic (both signal mean-reversion)
            if fib_score > 8 and stoch_score > 10:
                synergy += 12  # Strong mean-reversion setup

            # Bonus 2: Fib + OBV (volume confirms level)
            if fib_score > 8 and obv_score > 8:
                synergy += 10  # Volume validates support/resistance

            # Bonus 3: Fib + SMA (trend + level alignment)
            if fib_score > 8 and sma_score > 8:
                synergy += 8   # Trend + level alignment

            # Bonus 4: All three technical + Fib
            if stoch_score > 0 and obv_score > 0 and sma_score > 0 and fib_score > 0:
                synergy += 15  # Triple alignment

            # ===== FINAL SCORE =====
            combined = fib_score + stoch_score + obv_score + sma_score + synergy

            return {
                "symbol": symbol,
                "price": current_price,
                "fib_score": fib_score,
                "stoch_k": stoch_k,
                "stoch_score": stoch_score,
                "obv_trend": obv_trend,
                "obv_score": obv_score,
                "sma_20": sma_20,
                "sma_50": sma_50,
                "sma_200": sma_200,
                "sma_score": sma_score,
                "synergy": synergy,
                "combined_score": combined
            }

        except Exception as e:
            print(f"Error testing {symbol}: {e}")
            return None

    def run_test(self, symbols=None):
        """Run test on multiple symbols"""

        if symbols is None:
            symbols = ["INTC", "AMD", "NVDA", "AAPL", "MSFT"]

        print("\n" + "="*80)
        print("TEST: Fibonacci + Stochastic + OBV + SMA")
        print("="*80 + "\n")

        results = []
        scores = []

        for symbol in symbols:
            result = self.test_combo(symbol)
            if result:
                results.append(result)
                scores.append(result['combined_score'])

                print(f"📊 {symbol}:")
                print(f"   Fibonacci: {result['fib_score']:+d}")
                print(f"   Stochastic (K%): {result['stoch_k']:.1f}% → Score {result['stoch_score']:+d}")
                print(f"   OBV Trend: {result['obv_trend']:+.0f} → Score {result['obv_score']:+d}")
                print(f"   SMA (20/50/200): ${result['sma_20']:.2f} / ${result['sma_50']:.2f} / ${result['sma_200']:.2f} → Score {result['sma_score']:+d}")
                print(f"   Synergy Bonus: {result['synergy']:+d}")
                print(f"   COMBINED: {result['combined_score']:+d} 🎯\n")

        if scores:
            avg_score = sum(scores) / len(scores)

            print("="*80)
            print("SUMMARY")
            print("="*80)
            print(f"\nTotal Tests: {len(results)}")
            print(f"Avg Combined Score: {avg_score:+.1f}")
            print(f"Min Score: {min(scores):+d}")
            print(f"Max Score: {max(scores):+d}")

            # Component breakdown
            print(f"\nComponent Averages:")
            avg_fib = sum(r['fib_score'] for r in results) / len(results)
            avg_stoch = sum(r['stoch_score'] for r in results) / len(results)
            avg_obv = sum(r['obv_score'] for r in results) / len(results)
            avg_sma = sum(r['sma_score'] for r in results) / len(results)
            avg_syn = sum(r['synergy'] for r in results) / len(results)

            print(f"  Fibonacci: {avg_fib:+.1f}")
            print(f"  Stochastic: {avg_stoch:+.1f}")
            print(f"  OBV: {avg_obv:+.1f}")
            print(f"  SMA: {avg_sma:+.1f}")
            print(f"  Synergy: {avg_syn:+.1f}")

            # Verdict
            print("\n" + "="*80)
            print("VERDICT")
            print("="*80)

            if avg_score > 20:
                print(f"\n✅ EXCELLENT COMBINATION")
                print(f"   Score: {avg_score:+.1f}")
                print(f"   Strong signals with high synergy")
                print(f"   ➜ ADD ALL FOUR TO BOT")
            elif avg_score > 12:
                print(f"\n⚠️ GOOD COMBINATION")
                print(f"   Score: {avg_score:+.1f}")
                print(f"   Decent signals, some synergy")
                print(f"   ➜ ADD TO BOT FOR TESTING")
            elif avg_score > 5:
                print(f"\n🟡 MODERATE COMBINATION")
                print(f"   Score: {avg_score:+.1f}")
                print(f"   Mixed results, minimal synergy")
                print(f"   ➜ SKIP OR TUNE")
            else:
                print(f"\n❌ WEAK COMBINATION")
                print(f"   Score: {avg_score:+.1f}")
                print(f"   Poor signals, no synergy")
                print(f"   ➜ DON'T USE")

            # Save results
            data = {
                "timestamp": datetime.now().isoformat(),
                "combination": "Fibonacci + Stochastic + OBV + SMA",
                "symbols": symbols,
                "results": results,
                "avg_score": avg_score,
                "component_averages": {
                    "fibonacci": avg_fib,
                    "stochastic": avg_stoch,
                    "obv": avg_obv,
                    "sma": avg_sma,
                    "synergy": avg_syn
                }
            }

            with open("stoch_obv_sma_fib_results.json", "w") as f:
                json.dump(data, f, indent=2, default=str)

            print(f"\n💾 Results saved: stoch_obv_sma_fib_results.json")
            print("="*80 + "\n")


if __name__ == "__main__":
    tester = IndicatorComboTester()
    tester.run_test()
