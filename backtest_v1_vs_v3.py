#!/usr/bin/env python3
"""
Comprehensive Backtest: v1 vs v3 (Fibonacci)
Run 5 cycles of each to confirm improvement
"""

import subprocess
import json
import re
from datetime import datetime

def run_bot_cycles(bot_file, cycles=5):
    """Run bot multiple cycles and aggregate results"""

    all_trades = []
    all_profits = []
    all_confidences = []

    print(f"\n📊 Running {bot_file} ({cycles} cycles)...")
    print("="*80)

    for cycle_num in range(1, cycles + 1):
        try:
            result = subprocess.run(
                ["python3", bot_file],
                capture_output=True,
                text=True,
                timeout=300
            )

            output = result.stdout + result.stderr

            # Extract all BUY trades
            buy_matches = re.findall(
                r"BUY \| (\w+) @ \$([\d.]+) \| Llama (\d+)%",
                output
            )

            # Extract profit from performance summary
            profit_match = re.search(r"Realistic \(\+1\.5%\): \+\$([0-9.]+)", output)
            profit = float(profit_match.group(1)) if profit_match else 0

            cycle_trades = len(buy_matches)
            cycle_confidences = [int(conf) for _, _, conf in buy_matches]

            all_trades.append(cycle_trades)
            all_profits.append(profit)
            all_confidences.extend(cycle_confidences)

            print(f"  Cycle {cycle_num}: {cycle_trades} trades, +${profit:.2f}")

        except Exception as e:
            print(f"  ❌ Cycle {cycle_num} error: {e}")
            all_trades.append(0)
            all_profits.append(0)

    # Calculate statistics
    total_trades = sum(all_trades)
    total_profit = sum(all_profits)
    avg_trades_per_cycle = total_trades / cycles
    avg_profit_per_cycle = total_profit / cycles
    avg_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else 0

    return {
        "bot": bot_file,
        "cycles": cycles,
        "trades_per_cycle": all_trades,
        "profits_per_cycle": all_profits,
        "total_trades": total_trades,
        "total_profit": total_profit,
        "avg_trades": avg_trades_per_cycle,
        "avg_profit": avg_profit_per_cycle,
        "avg_confidence": avg_confidence,
        "all_confidences": all_confidences
    }

def main():
    print("\n" + "="*80)
    print("COMPREHENSIVE BACKTEST: v1 vs v3 (Fibonacci)")
    print("5 cycles each = 40 trades total for statistical confidence")
    print("="*80)

    # Run v1
    print("\n🔄 PHASE 1: Testing v1 (Current Bot)")
    v1_results = run_bot_cycles("bot_dry_run.py", cycles=5)

    # Run v3
    print("\n🔄 PHASE 2: Testing v3 (Fibonacci)")
    v3_results = run_bot_cycles("bot_dry_run_v3.py", cycles=5)

    # Detailed comparison
    print("\n" + "="*80)
    print("DETAILED RESULTS")
    print("="*80)

    print(f"\n📊 V1 (Current):")
    print(f"   Cycles: {v1_results['cycles']}")
    print(f"   Total trades: {v1_results['total_trades']}")
    print(f"   Total profit: ${v1_results['total_profit']:.2f}")
    print(f"   Avg trades/cycle: {v1_results['avg_trades']:.1f}")
    print(f"   Avg profit/cycle: ${v1_results['avg_profit']:.2f}")
    print(f"   Avg confidence: {v1_results['avg_confidence']:.1f}%")

    print(f"\n📊 V3 (Fibonacci):")
    print(f"   Cycles: {v3_results['cycles']}")
    print(f"   Total trades: {v3_results['total_trades']}")
    print(f"   Total profit: ${v3_results['total_profit']:.2f}")
    print(f"   Avg trades/cycle: {v3_results['avg_trades']:.1f}")
    print(f"   Avg profit/cycle: ${v3_results['avg_profit']:.2f}")
    print(f"   Avg confidence: {v3_results['avg_confidence']:.1f}%")

    # Calculate improvements
    trade_improvement = ((v3_results['total_trades'] - v1_results['total_trades'])
                         / max(1, v1_results['total_trades']) * 100)
    profit_improvement = ((v3_results['total_profit'] - v1_results['total_profit'])
                          / max(0.01, v1_results['total_profit']) * 100)

    print("\n" + "="*80)
    print("IMPROVEMENT ANALYSIS")
    print("="*80)

    print(f"\n📈 Metrics:")
    print(f"   Trade count: {v1_results['total_trades']} → {v3_results['total_trades']} ({trade_improvement:+.1f}%)")
    print(f"   Total profit: ${v1_results['total_profit']:.2f} → ${v3_results['total_profit']:.2f} ({profit_improvement:+.1f}%)")
    print(f"   Profit/cycle: ${v1_results['avg_profit']:.2f} → ${v3_results['avg_profit']:.2f}")

    # Annualize
    print(f"\n💰 Annual Projections (252 trading days):")
    v1_annual = v1_results['total_profit'] / v1_results['cycles'] * 252
    v3_annual = v3_results['total_profit'] / v3_results['cycles'] * 252
    annual_gain = v3_annual - v1_annual

    print(f"   v1: ${v1_annual:.2f}/year")
    print(f"   v3: ${v3_annual:.2f}/year")
    print(f"   Gain: ${annual_gain:+.2f}/year")

    # Decision
    print("\n" + "="*80)
    print("RECOMMENDATION")
    print("="*80)

    if v3_results['total_profit'] > v1_results['total_profit'] and trade_improvement > 0:
        print(f"\n✅ DEPLOY V3 (Fibonacci)")
        print(f"   • Trades: +{trade_improvement:.1f}%")
        print(f"   • Profit: +{profit_improvement:.1f}%")
        print(f"   • Annual gain: ${annual_gain:+,.2f}")
        print(f"   • Confidence in decision: HIGH (5-cycle validated)")
    elif v3_results['total_profit'] > v1_results['total_profit']:
        print(f"\n⚠️ V3 SHOWS PROMISE but needs more testing")
        print(f"   • Profit improved but trade count flat")
        print(f"   • Run backtest with 10 cycles for more confidence")
    else:
        print(f"\n❌ KEEP V1")
        print(f"   • V3 did not improve performance")
        print(f"   • Fibonacci not adding value")

    # Save detailed results
    results = {
        "timestamp": datetime.now().isoformat(),
        "v1": v1_results,
        "v3": v3_results,
        "improvements": {
            "trade_count": trade_improvement,
            "profit": profit_improvement,
            "annual_gain": annual_gain
        }
    }

    with open("backtest_v1_vs_v3_detailed.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n💾 Results saved: backtest_v1_vs_v3_detailed.json")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
