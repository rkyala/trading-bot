#!/usr/bin/env python3
"""
Detailed V3 Backtest + Llama Analysis
- Run 15 cycles
- Analyze Llama confidence calibration
- Identify improvement opportunities
- Test prompt enhancements
"""

import subprocess
import json
import re
from datetime import datetime
from collections import defaultdict

class DetailedBacktester:
    """Comprehensive backtest with Llama performance analysis"""

    def __init__(self):
        self.cycles = []
        self.llama_analysis = defaultdict(list)
        self.trade_analysis = []

    def run_backtest(self, cycles=15):
        """Run multiple cycles and collect detailed data"""

        print("\n" + "="*80)
        print(f"DETAILED V3 BACKTEST - {cycles} Cycles")
        print("="*80 + "\n")

        for cycle_num in range(1, cycles + 1):
            print(f"🔄 Cycle {cycle_num}/{cycles}...", end=" ", flush=True)

            try:
                result = subprocess.run(
                    ["python3", "bot_dry_run_v3.py"],
                    capture_output=True,
                    text=True,
                    timeout=300
                )

                output = result.stdout + result.stderr

                # Extract BUY trades
                buy_matches = re.findall(
                    r"BUY \| (\w+) @ \$([\d.]+) \| Llama (\d+)%.*\| Fib Boost ([+-]?\d+)%",
                    output
                )

                # Extract profit
                profit_match = re.search(r"Realistic \(\+1\.5%\): \+\$([0-9.]+)", output)
                profit = float(profit_match.group(1)) if profit_match else 0

                # Extract performance
                perf_match = re.search(r"Trades triggered: (\d+)", output)
                num_trades = int(perf_match.group(1)) if perf_match else len(buy_matches)

                # Extract avg confidence
                conf_match = re.search(r"Avg confidence: (\d+)%", output)
                avg_conf = int(conf_match.group(1)) if conf_match else 0

                # Store cycle data
                cycle_data = {
                    "cycle": cycle_num,
                    "trades": len(buy_matches),
                    "profit": profit,
                    "avg_confidence": avg_conf,
                    "trades_detail": buy_matches
                }

                self.cycles.append(cycle_data)

                # Analyze Llama performance per trade
                for symbol, price, conf, fib_boost in buy_matches:
                    self.trade_analysis.append({
                        "cycle": cycle_num,
                        "symbol": symbol,
                        "price": float(price),
                        "llama_confidence": int(conf),
                        "fib_boost": int(fib_boost),
                        "final_confidence": int(conf) + int(fib_boost),
                        "profit": profit / max(1, len(buy_matches))
                    })

                    # Group by confidence level
                    self.llama_analysis[symbol].append({
                        "confidence": int(conf),
                        "final": int(conf) + int(fib_boost),
                        "profit": profit / max(1, len(buy_matches))
                    })

                print(f"✅ {num_trades} trades, +${profit:.2f}")

            except Exception as e:
                print(f"❌ Error: {e}")
                continue

        # Analyze results
        self._generate_analysis()

    def _generate_analysis(self):
        """Generate detailed analysis"""

        print("\n" + "="*80)
        print("DETAILED ANALYSIS")
        print("="*80)

        # Overall stats
        print(f"\n📊 OVERALL PERFORMANCE:")
        total_trades = sum(c["trades"] for c in self.cycles)
        total_profit = sum(c["profit"] for c in self.cycles)
        avg_profit_per_cycle = total_profit / len(self.cycles) if self.cycles else 0
        avg_trades_per_cycle = total_trades / len(self.cycles) if self.cycles else 0

        print(f"  Total Cycles: {len(self.cycles)}")
        print(f"  Total Trades: {total_trades}")
        print(f"  Total Profit: ${total_profit:.2f}")
        print(f"  Avg Trades/Cycle: {avg_trades_per_cycle:.1f}")
        print(f"  Avg Profit/Cycle: ${avg_profit_per_cycle:.2f}")
        print(f"  Annualized: ${avg_profit_per_cycle * 252:.2f}/year")

        # Llama confidence calibration
        print(f"\n📈 LLAMA CONFIDENCE CALIBRATION:")
        print(f"  {'Confidence':<15} {'Trades':<10} {'Avg Profit':<15} {'Reliability':<15}")
        print(f"  {'-'*55}")

        confidence_buckets = defaultdict(lambda: {"count": 0, "profit": 0})
        for trade in self.trade_analysis:
            conf_bucket = f"{trade['llama_confidence']//10*10}-{trade['llama_confidence']//10*10+9}"
            confidence_buckets[conf_bucket]["count"] += 1
            confidence_buckets[conf_bucket]["profit"] += trade["profit"]

        for bucket in sorted(confidence_buckets.keys()):
            data = confidence_buckets[bucket]
            avg_p = data["profit"] / data["count"] if data["count"] > 0 else 0
            reliability = "✅ GOOD" if avg_p > 5 else "⚠️ FAIR" if avg_p > 0 else "❌ POOR"
            print(f"  {bucket:<15} {data['count']:<10} ${avg_p:<14.2f} {reliability:<15}")

        # Per-symbol analysis
        print(f"\n🎯 PER-SYMBOL ANALYSIS:")
        print(f"  {'Symbol':<10} {'Trades':<10} {'Avg Conf':<12} {'Avg Profit':<15} {'Win %':<10}")
        print(f"  {'-'*60}")

        symbol_stats = defaultdict(lambda: {"trades": 0, "profit": 0, "conf": []})
        for trade in self.trade_analysis:
            sym = trade["symbol"]
            symbol_stats[sym]["trades"] += 1
            symbol_stats[sym]["profit"] += trade["profit"]
            symbol_stats[sym]["conf"].append(trade["llama_confidence"])

        for symbol in sorted(symbol_stats.keys()):
            stats = symbol_stats[symbol]
            avg_conf = sum(stats["conf"]) / len(stats["conf"]) if stats["conf"] else 0
            avg_profit = stats["profit"] / stats["trades"] if stats["trades"] > 0 else 0
            win_pct = 100 if avg_profit > 0 else 0
            print(f"  {symbol:<10} {stats['trades']:<10} {avg_conf:<11.0f}% ${avg_profit:<14.2f} {win_pct:.0f}%")

        # Identify Llama weaknesses
        print(f"\n⚠️ LLAMA WEAKNESSES (Improvement Opportunities):")
        low_conf_trades = [t for t in self.trade_analysis if t["llama_confidence"] < 50]
        high_conf_trades = [t for t in self.trade_analysis if t["llama_confidence"] >= 70]

        print(f"  Low Confidence (<50%): {len(low_conf_trades)} trades")
        print(f"    Avg Profit: ${sum(t['profit'] for t in low_conf_trades) / max(1, len(low_conf_trades)):.2f}")
        print(f"    Issue: Llama being too conservative?")

        print(f"\n  High Confidence (≥70%): {len(high_conf_trades)} trades")
        print(f"    Avg Profit: ${sum(t['profit'] for t in high_conf_trades) / max(1, len(high_conf_trades)):.2f}")
        print(f"    Issue: Overconfident or good signal?")

        # Fibonacci boost effectiveness
        print(f"\n✨ FIBONACCI BOOST EFFECTIVENESS:")
        boosted = [t for t in self.trade_analysis if t["fib_boost"] > 0]
        unboosted = [t for t in self.trade_analysis if t["fib_boost"] == 0]

        if boosted:
            avg_boosted = sum(t["profit"] for t in boosted) / len(boosted)
            print(f"  Boosted Trades: {len(boosted)}")
            print(f"    Avg Profit: ${avg_boosted:.2f}")
            print(f"    Impact: {boosted[0]['fib_boost'] if boosted else 0}% confidence boost")

        if unboosted:
            avg_unboosted = sum(t["profit"] for t in unboosted) / len(unboosted)
            print(f"  Unboosted Trades: {len(unboosted)}")
            print(f"    Avg Profit: ${avg_unboosted:.2f}")

        # Improvement recommendations
        print(f"\n🚀 IMPROVEMENT RECOMMENDATIONS:")
        print(f"  1. Llama Confidence Range: Currently 20-90%")
        print(f"     → Recommend: Narrow to 40-80% for consistency")
        print(f"     → Add stronger negative signals (< 40%)")

        print(f"\n  2. Fibonacci Integration:")
        if boosted and unboosted:
            boost_better = avg_boosted > avg_unboosted
            print(f"     {'✅ Working' if boost_better else '⚠️ Not helping'}")
            print(f"     → Keep Fibonacci + increase boost amounts if working")

        print(f"\n  3. Symbol-Specific Tuning:")
        best_symbol = max(symbol_stats.items(), key=lambda x: x[1]["profit"])[0]
        print(f"     → Best: {best_symbol} (avg ${symbol_stats[best_symbol]['profit']/symbol_stats[best_symbol]['trades']:.2f})")
        print(f"     → Lower threshold for {best_symbol}, higher for others")

        # Save detailed results
        results = {
            "timestamp": datetime.now().isoformat(),
            "cycles": self.cycles,
            "trade_analysis": self.trade_analysis,
            "summary": {
                "total_cycles": len(self.cycles),
                "total_trades": total_trades,
                "total_profit": total_profit,
                "avg_profit_per_cycle": avg_profit_per_cycle,
                "annualized": avg_profit_per_cycle * 252
            }
        }

        with open("backtest_v3_detailed_results.json", "w") as f:
            json.dump(results, f, indent=2, default=str)

        print(f"\n💾 Detailed results saved: backtest_v3_detailed_results.json")
        print("="*80 + "\n")


if __name__ == "__main__":
    print("\n🔍 Starting detailed backtest with Llama analysis...")
    print("This will run 15 cycles and analyze Llama's performance\n")

    tester = DetailedBacktester()
    tester.run_backtest(cycles=15)
