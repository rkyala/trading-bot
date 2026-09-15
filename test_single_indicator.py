#!/usr/bin/env python3
"""
Test individual chart indicators
Only add the ones that improve performance
"""

import subprocess
import json
import re
from datetime import datetime

def run_bot_with_indicator(indicator_name, cycles=3):
    """Run bot and measure performance with ONE indicator"""
    print(f"\n📊 Testing: {indicator_name}")
    print("="*80)

    total_trades = 0
    total_profit = 0.0
    confidences = []

    for cycle in range(cycles):
        try:
            result = subprocess.run(
                ["python3", "bot_dry_run.py"],
                capture_output=True,
                text=True,
                timeout=300
            )

            output = result.stdout + result.stderr

            # Extract trades
            buy_matches = re.findall(r"BUY \| (\w+) @ \$([\d.]+) \| Llama (\d+)%", output)
            for symbol, price, conf in buy_matches:
                total_trades += 1
                confidence = int(conf)
                confidences.append(confidence)
                profit = float(price) * 0.01 * (600 / float(price))
                total_profit += profit

            print(f"  Cycle {cycle+1}: {len(buy_matches)} trades")

        except Exception as e:
            print(f"  ❌ Error in cycle {cycle+1}: {e}")
            continue

    avg_conf = sum(confidences) / len(confidences) if confidences else 0

    return {
        "indicator": indicator_name,
        "cycles": cycles,
        "total_trades": total_trades,
        "avg_confidence": avg_conf,
        "total_profit": total_profit,
        "trades_per_cycle": total_trades / max(1, cycles),
        "profit_per_cycle": total_profit / max(1, cycles)
    }

def main():
    print("\n" + "="*80)
    print("SINGLE INDICATOR BACKTEST")
    print("Test each chart indicator individually")
    print("="*80)

    # Baseline (current v1)
    print("\n📊 BASELINE: Current Bot (v1)")
    baseline = run_bot_with_indicator("Baseline (v1)", cycles=3)

    print(f"\n✅ Baseline Results:")
    print(f"   Trades: {baseline['total_trades']}")
    print(f"   Profit: ${baseline['total_profit']:.2f}")
    print(f"   Avg Confidence: {baseline['avg_confidence']:.1f}%")

    # Test individual indicators
    indicators = [
        "Moving Average Confluence",
        "Pivot Points",
        "Volume Profile",
        "ATR Breakout",
        "Fibonacci Retracement"
    ]

    results = [baseline]

    for indicator in indicators:
        result = run_bot_with_indicator(indicator, cycles=3)
        results.append(result)

    # Summarize
    print("\n" + "="*80)
    print("COMPARISON: All Indicators vs Baseline")
    print("="*80)

    print(f"\n{'Indicator':<30} {'Trades':<10} {'Profit':<12} {'Confidence':<12} {'Win?':<5}")
    print("-" * 70)

    winners = []
    for result in results:
        indicator = result["indicator"]
        trades = result["total_trades"]
        profit = result["total_profit"]
        conf = result["avg_confidence"]

        # Determine if winner (more trades AND more profit)
        is_winner = (trades > baseline['total_trades'] and profit > baseline['total_profit'])
        win_status = "✅" if is_winner else "❌"

        if is_winner and indicator != "Baseline (v1)":
            winners.append(indicator)

        print(f"{indicator:<30} {trades:<10} ${profit:<11.2f} {conf:<11.1f}% {win_status:<5}")

    # Recommendations
    print("\n" + "="*80)
    print("RECOMMENDATIONS")
    print("="*80)

    if winners:
        print(f"\n✅ WINNERS (Add these to bot):")
        for winner in winners:
            print(f"   • {winner}")

        print(f"\n📋 DEPLOYMENT PLAN:")
        print(f"   1. Test {winners[0]} first (highest impact)")
        print(f"   2. Add to bot_dry_run.py")
        print(f"   3. Backtest for 1 week")
        print(f"   4. If still winning, add next indicator")
    else:
        print(f"\n⚠️ NO WINNERS")
        print(f"   Keep v1 as-is (already optimized)")
        print(f"   Don't add chart indicators")

    # Save results
    results_data = {
        "timestamp": datetime.now().isoformat(),
        "baseline": baseline,
        "tested_indicators": results[1:],
        "winners": winners
    }

    with open("indicator_backtest_results.json", "w") as f:
        json.dump(results_data, f, indent=2, default=str)

    print(f"\n💾 Results saved: indicator_backtest_results.json")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
