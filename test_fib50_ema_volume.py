#!/usr/bin/env python3
"""
Test Specific Combination: Fibonacci 50% + EMA + Volume Profile
"""

import json
from datetime import datetime
import yfinance as yf
import pandas as pd
from advanced_charts import AdvancedChartAnalyzer

class SpecificComboTester:
    """Test Fib 50% + EMA + Volume Profile"""

    def __init__(self):
        self.analyzer = AdvancedChartAnalyzer()

    def test_combo(self, symbol):
        """Test the specific combination"""

        try:
            # Get analysis
            analysis = self.analyzer.get_chart_analysis(symbol)
            if not analysis:
                return None

            # Get historical data for EMA
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="60d")
            if hist.empty:
                return None

            # 1. FIBONACCI 50% LEVEL (Midpoint - Most Important!)
            fib = analysis.get("fibonacci_levels", {})
            fib_50 = fib.get("500", None)  # 50% level
            current_price = analysis.get("price", 0)

            if not fib_50:
                return None

            # Distance to Fib 50% (key level)
            dist_to_fib50 = abs(current_price - fib_50)
            pct_to_fib50 = (dist_to_fib50 / fib_50) * 100

            fib_score = 0
            if pct_to_fib50 < 0.5:  # Very close to 50% level
                fib_score = 20  # Strong signal
            elif pct_to_fib50 < 1.0:  # Near 50% level
                fib_score = 12
            elif pct_to_fib50 < 2.0:  # Reasonably close
                fib_score = 6
            else:
                fib_score = 0

            # 2. EMA (Exponential Moving Average)
            ema_12 = hist['Close'].ewm(span=12).mean().iloc[-1]
            ema_26 = hist['Close'].ewm(span=26).mean().iloc[-1]

            ema_score = 0
            if current_price > ema_12 > ema_26:
                ema_score = 15  # Bullish EMA alignment
            elif current_price > ema_12:
                ema_score = 10  # Partial bullish
            elif current_price > ema_26:
                ema_score = 5   # Weak bullish
            else:
                ema_score = -5  # Bearish

            # 3. VOLUME PROFILE
            vp = analysis.get("volume_profile", {})
            vp_signal = vp.get("signal", "")

            vol_score = 0
            if vp_signal == "at_support":
                vol_score = 12  # At support = buying pressure
            elif vp_signal == "at_resistance":
                vol_score = -8  # At resistance = selling pressure
            else:
                vol_score = 2   # Neutral zone

            # SYNERGY BONUS
            synergy = 0

            # Bonus 1: Fib 50% + At Support + Bullish EMA
            if fib_score > 10 and vol_score > 8 and ema_score > 8:
                synergy += 15  # Triple alignment = strong

            # Bonus 2: Fib 50% + Bullish EMA
            if fib_score > 10 and ema_score > 10:
                synergy += 8   # Two key signals

            # Penalty: Fib 50% + At Resistance + Bearish EMA
            if fib_score > 10 and vol_score < -5 and ema_score < 0:
                synergy -= 10  # Conflict

            # COMBINED SCORE
            combined = fib_score + ema_score + vol_score + synergy

            return {
                "symbol": symbol,
                "current_price": current_price,
                "fib_50_level": fib_50,
                "distance_to_fib50_pct": pct_to_fib50,
                "fib_score": fib_score,
                "ema_12": ema_12,
                "ema_26": ema_26,
                "ema_score": ema_score,
                "volume_profile": vp_signal,
                "vol_score": vol_score,
                "synergy_bonus": synergy,
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
        print("TEST: Fibonacci 50% + EMA + Volume Profile")
        print("="*80 + "\n")

        results = []
        scores = []

        for symbol in symbols:
            result = self.test_combo(symbol)
            if result:
                results.append(result)
                scores.append(result['combined_score'])

                print(f"📊 {symbol}:")
                print(f"   Fib 50% Level: ${result['fib_50_level']:.2f}")
                print(f"   Current Price: ${result['current_price']:.2f}")
                print(f"   Distance: {result['distance_to_fib50_pct']:.2f}%")
                print(f"   Fib Score: {result['fib_score']:+d}")
                print(f"   EMA (12/26): ${result['ema_12']:.2f} / ${result['ema_26']:.2f}")
                print(f"   EMA Score: {result['ema_score']:+d}")
                print(f"   Volume: {result['volume_profile']}")
                print(f"   Volume Score: {result['vol_score']:+d}")
                print(f"   Synergy Bonus: {result['synergy_bonus']:+d}")
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

            # Breakdowns
            print(f"\nComponent Averages:")
            avg_fib = sum(r['fib_score'] for r in results) / len(results)
            avg_ema = sum(r['ema_score'] for r in results) / len(results)
            avg_vol = sum(r['vol_score'] for r in results) / len(results)
            avg_syn = sum(r['synergy_bonus'] for r in results) / len(results)

            print(f"  Fibonacci 50%: {avg_fib:+.1f}")
            print(f"  EMA: {avg_ema:+.1f}")
            print(f"  Volume Profile: {avg_vol:+.1f}")
            print(f"  Synergy Bonus: {avg_syn:+.1f}")

            # Verdict
            print("\n" + "="*80)
            print("VERDICT")
            print("="*80)

            if avg_score > 15:
                print(f"\n✅ EXCELLENT COMBINATION")
                print(f"   Score: {avg_score:+.1f}")
                print(f"   Strong signals, good synergy")
                print(f"   ➜ TEST IN BOT NOW")
            elif avg_score > 8:
                print(f"\n⚠️ GOOD COMBINATION")
                print(f"   Score: {avg_score:+.1f}")
                print(f"   Decent signals, some synergy")
                print(f"   ➜ WORTH TESTING")
            elif avg_score > 2:
                print(f"\n🟡 MIXED RESULTS")
                print(f"   Score: {avg_score:+.1f}")
                print(f"   Inconsistent, minimal synergy")
                print(f"   ➜ NEEDS TUNING")
            else:
                print(f"\n❌ POOR COMBINATION")
                print(f"   Score: {avg_score:+.1f}")
                print(f"   Weak signals, no synergy")
                print(f"   ➜ SKIP THIS")

            # Save results
            data = {
                "timestamp": datetime.now().isoformat(),
                "combination": "Fibonacci 50% + EMA + Volume Profile",
                "symbols": symbols,
                "results": results,
                "avg_score": avg_score,
                "component_averages": {
                    "fib_50": avg_fib,
                    "ema": avg_ema,
                    "volume": avg_vol,
                    "synergy": avg_syn
                }
            }

            with open("fib50_ema_volume_results.json", "w") as f:
                json.dump(data, f, indent=2, default=str)

            print(f"\n💾 Results saved: fib50_ema_volume_results.json")
            print("="*80 + "\n")


if __name__ == "__main__":
    tester = SpecificComboTester()
    tester.run_test()
