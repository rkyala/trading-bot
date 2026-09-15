#!/usr/bin/env python3
"""
Backtest: v3 (Fib Only) vs v3.5 (Fib + Stochastic)
5 cycles each, head-to-head comparison
"""

import subprocess
import re
import json
from datetime import datetime

class BotComparison:
    """Compare two bot versions"""

    def __init__(self):
        self.v3_results = []
        self.v3_5_results = []

    def run_version(self, version_name, script_name, cycles=5):
        """Run bot version for N cycles"""

        print(f"\n{'='*80}")
        print(f"RUNNING {version_name} - {cycles} CYCLES")
        print(f"{'='*80}\n")

        results = []

        for cycle_num in range(1, cycles + 1):
            print(f"🔄 Cycle {cycle_num}/{cycles}...", end=" ", flush=True)

            try:
                result = subprocess.run(
                    ["python3", script_name],
                    capture_output=True,
                    text=True,
                    timeout=300
                )

                output = result.stdout + result.stderr

                # Extract trades
                buy_matches = re.findall(
                    r"BUY \| (\w+) @ \$([\d.]+)",
                    output
                )
                num_trades = len(buy_matches)

                # Extract profit
                profit_match = re.search(r"Total profit: \+\$([0-9.]+)", output)
                profit = float(profit_match.group(1)) if profit_match else 0

                # Extract avg confidence
                conf_match = re.search(r"Avg confidence: (\d+)%", output)
                avg_conf = int(conf_match.group(1)) if conf_match else 0

                cycle_data = {
                    "cycle": cycle_num,
                    "trades": num_trades,
                    "profit": profit,
                    "avg_confidence": avg_conf,
                    "symbols": [sym for sym, _ in buy_matches]
                }

                results.append(cycle_data)
                print(f"✅ {num_trades} trades, +${profit:.2f}, {avg_conf}% conf")

            except subprocess.TimeoutExpired:
                print(f"⏱️ TIMEOUT")
                results.append({
                    "cycle": cycle_num,
                    "trades": 0,
                    "profit": 0,
                    "avg_confidence": 0,
                    "error": "Timeout"
                })
            except Exception as e:
                print(f"❌ ERROR: {e}")
                results.append({
                    "cycle": cycle_num,
                    "trades": 0,
                    "profit": 0,
                    "avg_confidence": 0,
                    "error": str(e)
                })

        return results

    def compare_results(self):
        """Compare v3 vs v3.5"""

        print(f"\n{'='*80}")
        print("COMPARISON: v3 (Fibonacci) vs v3.5 (Fibonacci + Stochastic)")
        print(f"{'='*80}\n")

        # Calculate stats for each version
        v3_stats = self._calc_stats(self.v3_results, "v3")
        v35_stats = self._calc_stats(self.v3_5_results, "v3.5")

        # Display comparison
        print(f"{'Metric':<30} {'v3 (Fib)':<20} {'v3.5 (Fib+Stoch)':<20} {'Winner':<15}")
        print(f"{'-'*85}")

        # Total trades
        winner = "v3.5 ✅" if v35_stats["total_trades"] > v3_stats["total_trades"] else "v3 ✅" if v3_stats["total_trades"] > v35_stats["total_trades"] else "TIE"
        print(f"{'Total Trades':<30} {v3_stats['total_trades']:<20} {v35_stats['total_trades']:<20} {winner:<15}")

        # Total profit
        winner = "v3.5 ✅" if v35_stats["total_profit"] > v3_stats["total_profit"] else "v3 ✅" if v3_stats["total_profit"] > v35_stats["total_profit"] else "TIE"
        print(f"{'Total Profit':<30} +${v3_stats['total_profit']:<19.2f} +${v35_stats['total_profit']:<19.2f} {winner:<15}")

        # Avg profit per cycle
        winner = "v3.5 ✅" if v35_stats["avg_profit_cycle"] > v3_stats["avg_profit_cycle"] else "v3 ✅" if v3_stats["avg_profit_cycle"] > v35_stats["avg_profit_cycle"] else "TIE"
        print(f"{'Avg Profit/Cycle':<30} +${v3_stats['avg_profit_cycle']:<19.2f} +${v35_stats['avg_profit_cycle']:<19.2f} {winner:<15}")

        # Avg profit per trade
        winner = "v3.5 ✅" if v35_stats["avg_profit_trade"] > v3_stats["avg_profit_trade"] else "v3 ✅" if v3_stats["avg_profit_trade"] > v35_stats["avg_profit_trade"] else "TIE"
        print(f"{'Avg Profit/Trade':<30} +${v3_stats['avg_profit_trade']:<19.2f} +${v35_stats['avg_profit_trade']:<19.2f} {winner:<15}")

        # Avg confidence
        winner = "v3.5 ✅" if v35_stats["avg_confidence"] > v3_stats["avg_confidence"] else "v3 ✅" if v3_stats["avg_confidence"] > v35_stats["avg_confidence"] else "TIE"
        print(f"{'Avg Confidence':<30} {v3_stats['avg_confidence']:.0f}%{'':<16} {v35_stats['avg_confidence']:.0f}%{'':<16} {winner:<15}")

        # Avg trades per cycle
        winner = "v3.5 ✅" if v35_stats["avg_trades_cycle"] > v3_stats["avg_trades_cycle"] else "v3 ✅" if v3_stats["avg_trades_cycle"] > v35_stats["avg_trades_cycle"] else "TIE"
        print(f"{'Avg Trades/Cycle':<30} {v3_stats['avg_trades_cycle']:.1f}{'':<17} {v35_stats['avg_trades_cycle']:.1f}{'':<17} {winner:<15}")

        # Annualized projection
        winner = "v3.5 ✅" if v35_stats["annualized"] > v3_stats["annualized"] else "v3 ✅" if v3_stats["annualized"] > v35_stats["annualized"] else "TIE"
        print(f"{'Annualized (252 days)':<30} +${v3_stats['annualized']:<19.2f} +${v35_stats['annualized']:<19.2f} {winner:<15}")

        # Improvement percentage
        if v3_stats["total_profit"] > 0:
            improvement_pct = ((v35_stats["total_profit"] - v3_stats["total_profit"]) / v3_stats["total_profit"]) * 100
        else:
            improvement_pct = 0

        print(f"\n{'='*85}")
        print(f"📊 v3.5 IMPROVEMENT: {improvement_pct:+.1f}%")
        print(f"{'='*85}\n")

        # Detailed breakdown
        print(f"v3 (FIBONACCI ONLY) - {len(self.v3_results)} cycles:")
        for cycle in self.v3_results:
            status = "✅" if cycle.get("error") is None else "❌"
            print(f"  {status} Cycle {cycle['cycle']}: {cycle['trades']} trades, +${cycle['profit']:.2f}")

        print(f"\nv3.5 (FIBONACCI + STOCHASTIC) - {len(self.v3_5_results)} cycles:")
        for cycle in self.v3_5_results:
            status = "✅" if cycle.get("error") is None else "❌"
            print(f"  {status} Cycle {cycle['cycle']}: {cycle['trades']} trades, +${cycle['profit']:.2f}")

        # Recommendation
        print(f"\n{'='*85}")
        print("🎯 RECOMMENDATION")
        print(f"{'='*85}\n")

        if v35_stats["total_profit"] > v3_stats["total_profit"]:
            improvement = v35_stats["total_profit"] - v3_stats["total_profit"]
            print(f"✅ v3.5 (Fib + Stochastic) is BETTER")
            print(f"   +${improvement:.2f} more profit over 5 cycles")
            print(f"   → ADD STOCHASTIC to live bot")
        elif v3_stats["total_profit"] > v35_stats["total_profit"]:
            improvement = v3_stats["total_profit"] - v35_stats["total_profit"]
            print(f"✅ v3 (Fibonacci only) is BETTER")
            print(f"   +${improvement:.2f} more profit over 5 cycles")
            print(f"   → KEEP FIBONACCI, SKIP STOCHASTIC")
        else:
            print(f"🟡 TIED - Both produce same profit")
            print(f"   → v3 is simpler, keep it")

        print(f"\n{'='*85}\n")

        # Save results
        self._save_results(v3_stats, v35_stats, improvement_pct)

    def _calc_stats(self, results, version_name):
        """Calculate statistics"""

        valid_results = [r for r in results if r.get("error") is None]

        total_trades = sum(r["trades"] for r in valid_results)
        total_profit = sum(r["profit"] for r in valid_results)
        avg_confidence = sum(r["avg_confidence"] for r in valid_results) / len(valid_results) if valid_results else 0
        avg_trades_cycle = total_trades / len(valid_results) if valid_results else 0
        avg_profit_cycle = total_profit / len(valid_results) if valid_results else 0
        avg_profit_trade = total_profit / total_trades if total_trades > 0 else 0
        annualized = avg_profit_cycle * 252

        return {
            "version": version_name,
            "cycles": len(valid_results),
            "total_trades": total_trades,
            "total_profit": total_profit,
            "avg_confidence": avg_confidence,
            "avg_trades_cycle": avg_trades_cycle,
            "avg_profit_cycle": avg_profit_cycle,
            "avg_profit_trade": avg_profit_trade,
            "annualized": annualized
        }

    def _save_results(self, v3_stats, v35_stats, improvement_pct):
        """Save comparison results"""

        data = {
            "timestamp": datetime.now().isoformat(),
            "comparison": "v3 (Fibonacci) vs v3.5 (Fibonacci + Stochastic)",
            "cycles": 5,
            "v3_results": {
                "raw_cycles": self.v3_results,
                "stats": v3_stats
            },
            "v3_5_results": {
                "raw_cycles": self.v3_5_results,
                "stats": v35_stats
            },
            "improvement_percent": improvement_pct,
            "recommendation": (
                "v3.5 (add Stochastic)" if v35_stats["total_profit"] > v3_stats["total_profit"]
                else "v3 (keep Fibonacci only)" if v3_stats["total_profit"] > v35_stats["total_profit"]
                else "Keep v3 (simpler)"
            )
        }

        with open("backtest_v3_vs_v3_5_results.json", "w") as f:
            json.dump(data, f, indent=2, default=str)

        print(f"💾 Results saved: backtest_v3_vs_v3_5_results.json")


if __name__ == "__main__":
    print("\n" + "="*80)
    print("🤖 BACKTEST: v3 vs v3.5 (5 Cycles Each)")
    print("="*80)

    tester = BotComparison()

    # Run v3 (Fibonacci only)
    tester.v3_results = tester.run_version("v3 (Fibonacci)", "bot_dry_run_v3.py", cycles=5)

    # Run v3.5 (Fibonacci + Stochastic)
    tester.v3_5_results = tester.run_version("v3.5 (Fibonacci + Stochastic)", "bot_dry_run_v3_5.py", cycles=5)

    # Compare
    tester.compare_results()
