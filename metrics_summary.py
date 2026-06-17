#!/usr/bin/env python3
"""
Quick summary of bot token usage vs profitability.
Run with: python metrics_summary.py
"""

import json
import os
from datetime import datetime
from pathlib import Path

DATA_DIR = os.environ.get("DATA_DIR", ".")

def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def main():
    state = read_json(os.path.join(DATA_DIR, "bot_state.json"))
    metrics = read_json(os.path.join(DATA_DIR, "daily_metrics.json"))
    
    if not metrics and not state:
        print("❌ No metrics data found. Bot hasn't run yet or DATA_DIR is incorrect.")
        return
    
    print("\n" + "="*70)
    print(" BOT ROI ANALYSIS")
    print("="*70)
    
    # Metrics summary
    if metrics:
        print(f"\n📊 Daily Token Usage ({metrics['date']}):")
        print(f"   Runs:              {metrics['runs']}")
        print(f"   Input tokens:      {metrics['total_input_tokens']:,}")
        print(f"   Output tokens:     {metrics['total_output_tokens']:,}")
        print(f"   Total tokens:      {metrics['total_input_tokens'] + metrics['total_output_tokens']:,}")
        print(f"   Cost (Sonnet 4.6): ${metrics['token_cost_usd']:.2f}")
        
        print(f"\n💰 P&L:")
        daily_pnl = metrics['daily_pnl']
        print(f"   Daily P&L:         ${daily_pnl:+.2f}")
        
        if metrics['token_cost_usd'] > 0:
            roi = (daily_pnl / metrics['token_cost_usd']) * 100
            print(f"   ROI:               {roi:+.0f}%")
            
            if roi > 50:
                print(f"   ✅ PROFITABLE (earning {roi:.0f}% of token costs)")
            elif roi > 0:
                print(f"   ⚠️  MARGINAL (earning {roi:.0f}% of token costs, need >100%)")
            else:
                print(f"   ❌ UNPROFITABLE (losing {abs(roi):.0f}% of token costs)")
    
    # State summary
    if state:
        positions = state.get('positions', {})
        trades = state.get('trade_history', [])
        
        print(f"\n📈 Positions & Trades:")
        print(f"   Open positions:    {len(positions)}")
        print(f"   Total trades:      {len(trades)}")
        
        # Win rate
        if trades:
            wins = sum(1 for t in trades if t.get('realized_pnl', 0) > 0)
            win_pct = (wins / len(trades)) * 100
            print(f"   Win rate:          {win_pct:.0f}% ({wins}/{len(trades)})")
            
            total_pnl = sum(t.get('realized_pnl', 0) for t in trades)
            avg_pnl = total_pnl / len(trades) if trades else 0
            print(f"   Avg trade P&L:     ${avg_pnl:+.2f}")
            print(f"   Total P&L:         ${total_pnl:+.2f}")
    
    print("\n" + "="*70)
    if metrics and metrics['token_cost_usd'] > 0:
        roi = (metrics['daily_pnl'] / metrics['token_cost_usd']) * 100
        if roi > 100:
            print("✅ SYSTEM IS PROFITABLE — ROI > 100%")
        elif roi > 0:
            print("⚠️  SYSTEM IS MARGINAL — ROI > 0% but < 100%, consider reducing token costs")
        else:
            print("❌ SYSTEM IS NOT PROFITABLE — losing money on token costs")
            print("   Recommendation: reduce run frequency (5min → 10min) or switch to Haiku")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
