#!/usr/bin/env python3
"""
DRY-RUN DASHBOARD: View analysis results and hypothetical performance
"""

import os
import json
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = "dry_run_logs"

def show_today_summary():
    """Show today's performance summary"""

    today = datetime.now().strftime("%Y%m%d")
    perf_file = os.path.join(LOG_DIR, f"performance_{today}.json")

    if not os.path.exists(perf_file):
        print(f"\n❌ No performance log found for today ({today})")
        print(f"   Run bot_dry_run.py first to generate logs\n")
        return

    with open(perf_file, 'r') as f:
        summary = json.load(f)

    print("\n" + "="*80)
    print(f"  DRY-RUN PERFORMANCE: {summary['date']}")
    print("="*80 + "\n")

    print(f"Trades Analyzed: {summary['total_analyzed']}")
    print(f"Would Execute: {summary['trades_that_would_execute']}\n")

    # Best case
    print("BEST CASE SCENARIO (+3% target):")
    print(f"  Total Profit: ${summary['best_case_scenario']['total_profit']:,.2f}")
    print(f"  Avg ROI: {summary['best_case_scenario']['total_roi']:.2f}%")
    print(f"  Per Trade: ${summary['best_case_scenario']['total_profit']/max(1, summary['total_analyzed']):,.2f}\n")

    # Realistic
    print("REALISTIC SCENARIO (+1.5% target):")
    print(f"  Total Profit: ${summary['realistic_scenario']['total_profit']:,.2f}")
    print(f"  Avg ROI: {summary['realistic_scenario']['total_roi']:.2f}%")
    print(f"  Per Trade: ${summary['realistic_scenario']['total_profit']/max(1, summary['total_analyzed']):,.2f}\n")

    # Conservative
    print("CONSERVATIVE SCENARIO (stop loss):")
    print(f"  Total Profit: ${summary['conservative_scenario']['total_profit']:,.2f}")
    print(f"  Avg ROI: {summary['conservative_scenario']['total_roi']:.2f}%")
    print(f"  Per Trade: ${summary['conservative_scenario']['total_profit']/max(1, summary['total_analyzed']):,.2f}\n")

    print("="*80 + "\n")


def show_trade_details():
    """Show detailed analysis of each trade"""

    today = datetime.now().strftime("%Y%m%d")
    perf_file = os.path.join(LOG_DIR, f"performance_{today}.json")

    if not os.path.exists(perf_file):
        return

    with open(perf_file, 'r') as f:
        summary = json.load(f)

    if not summary.get('trades'):
        return

    print("\nTRADE DETAILS:\n")
    print("Symbol | Entry    | Qty | +1%  Profit | +2% Profit | +3% Profit | Stop Loss")
    print("-"*95)

    for trade in summary['trades']:
        symbol = trade['symbol']
        entry = trade['entry_price']
        qty = trade['quantity']

        profit_1 = trade['hypothetical_exits']['+1%']['profit']
        profit_2 = trade['hypothetical_exits']['+2%']['profit']
        profit_3 = trade['hypothetical_exits']['+3%']['profit']
        stop = trade['hypothetical_exits']['stop_loss']['profit']

        print(f"{symbol:6} | ${entry:7.2f} | {qty:3d} | ${profit_1:7.2f} | ${profit_2:7.2f} | ${profit_3:7.2f} | ${stop:7.2f}")

    print()


def show_llm_finrl_decisions():
    """Show what Llama 2 and FinRL decided"""

    today = datetime.now().strftime("%Y%m%d")
    analysis_file = os.path.join(LOG_DIR, f"analysis_{today}.jsonl")

    if not os.path.exists(analysis_file):
        print(f"\n❌ No analysis log found\n")
        return

    print("\nLLAMA 2 & FINRL DECISIONS:\n")
    print("Symbol | Llama Decision | Confidence | Sentiment | FinRL Sharpe | Would Trade?")
    print("-"*95)

    analyses = []
    with open(analysis_file, 'r') as f:
        for line in f:
            analyses.append(json.loads(line))

    for analysis in analyses:
        symbol = analysis['symbol']
        llama_decision = analysis['llama2']['decision']
        confidence = analysis['llama2']['confidence']
        sentiment = analysis['sentiment']['sentiment_type']
        sharpe = analysis['finrl']['sharpe']
        would_trade = "✓ YES" if analysis['would_trade'] else "✗ NO"

        print(f"{symbol:6} | {llama_decision:14} | {confidence:10}% | {sentiment:9} | {sharpe:12.2f} | {would_trade}")

    print()


def show_logs():
    """Show raw log file"""

    today = datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(LOG_DIR, f"bot_{today}.log")

    if not os.path.exists(log_file):
        return

    print("\nRECENT LOG ENTRIES (last 30 lines):\n")
    print("="*80)

    with open(log_file, 'r') as f:
        lines = f.readlines()
        for line in lines[-30:]:
            print(line.rstrip())

    print("="*80 + "\n")


def main():
    """Main dashboard"""

    if not os.path.exists(LOG_DIR):
        print(f"\n❌ No logs found. Run bot_dry_run.py first.\n")
        return

    print("\n" + "="*80)
    print("  DRY-RUN DASHBOARD")
    print("="*80)

    # Show performance
    show_today_summary()

    # Show trade details
    show_trade_details()

    # Show decisions
    show_llm_finrl_decisions()

    # Show logs
    show_logs()

    # File listing
    print("LOG FILES:")
    for f in sorted(os.listdir(LOG_DIR)):
        path = os.path.join(LOG_DIR, f)
        size = os.path.getsize(path)
        print(f"  {f:50} ({size:,} bytes)")

    print()


if __name__ == "__main__":
    main()
