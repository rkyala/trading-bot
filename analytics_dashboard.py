#!/usr/bin/env python3
"""
Complete Trading System Analytics Dashboard
Shows: Stocks checked, Orders placed, Orders sold, Block trades
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd

# ============================================================================
# DATA LOADERS
# ============================================================================

def load_bot_log_analysis() -> Dict:
    """Extract comprehensive bot analytics from logs"""
    log_file = Path("bot_production.log")
    if not log_file.exists():
        return {"cycles": 0, "entries": [], "exits": [], "stocks_checked": []}

    content = log_file.read_text()
    lines = content.split("\n")

    analysis = {
        "cycles": 0,
        "stocks_checked": set(),
        "entries": [],
        "exits": [],
        "signals": [],
        "current_positions": set()
    }

    for line in lines:
        # Count cycles
        if "CYCLE |" in line:
            analysis["cycles"] += 1

        # Find stocks checked (all symbols analyzed)
        symbol_match = re.search(r"\[(\w{1,5})\]", line)
        if symbol_match:
            symbol = symbol_match.group(1)
            if symbol not in ["MCP", "UTC", "EST", "CDT"]:
                analysis["stocks_checked"].add(symbol)

        # Find entry signals
        if "ENTRY SIGNAL" in line or "🎯 ENTRY SIGNAL" in line:
            # Extract symbol and price
            parts = line.split("|")
            if len(parts) > 1:
                analysis["signals"].append(line.strip())

        # Find orders placed
        if "Order placed" in line or "placed:" in line:
            analysis["entries"].append(line.strip())

        # Find exits
        if "Exit" in line and ("reason" in line or "stoch" in line or "price" in line):
            analysis["exits"].append(line.strip())

        # Track open positions
        if "Already owned" in line:
            pos_match = re.search(r"\[(\w{1,5})\].*Already owned", line)
            if pos_match:
                analysis["current_positions"].add(pos_match.group(1))

    analysis["stocks_checked"] = sorted(list(analysis["stocks_checked"]))
    return analysis


def load_block_trades_analysis() -> pd.DataFrame:
    """Load and analyze block trades"""
    block_file = Path("block_trades.csv")
    if block_file.exists():
        try:
            df = pd.read_csv(block_file)
            return df
        except:
            return pd.DataFrame()
    return pd.DataFrame()


def load_positions_tracking() -> Dict:
    """Load position tracking data"""
    pos_file = Path("positions_tracking.json")
    if pos_file.exists():
        try:
            return json.loads(pos_file.read_text())
        except:
            return {}
    return {}


def load_schwab_signals() -> Dict:
    """Load current cached signals"""
    sig_file = Path("schwab_signals.json")
    if sig_file.exists():
        try:
            return json.loads(sig_file.read_text())
        except:
            return {"signals": []}
    return {"signals": []}


# ============================================================================
# ANALYTICS & FORMATTING
# ============================================================================

def print_header():
    """Print dashboard header"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S CDT")
    print("\n" + "=" * 120)
    print("COMPLETE TRADING ANALYTICS DASHBOARD".center(120))
    print(f"Updated: {now}".center(120))
    print("=" * 120 + "\n")


def print_stocks_checked(bot_analysis: Dict):
    """Print all stocks checked today"""
    stocks = bot_analysis["stocks_checked"]
    print("📊 STOCKS CHECKED TODAY")
    print("─" * 120)
    print(f"  Total Symbols Scanned: {len(stocks)}")
    print(f"\n  Symbols ({len(stocks)} total):")

    # Print in grid format (10 per row)
    for i in range(0, len(stocks), 10):
        chunk = stocks[i:i+10]
        print(f"  {' | '.join(chunk)}")
    print()


def print_signals_generated(bot_analysis: Dict, signals: Dict):
    """Print all signals generated"""
    print("🎯 ENTRY SIGNALS GENERATED")
    print("─" * 120)

    current_signals = signals.get("signals", [])
    print(f"  Current Signals: {len(current_signals)}")

    if current_signals:
        print(f"\n  Current Setup ({len(current_signals)} signals):")
        for sig in current_signals:
            print(f"    • {sig['symbol']:<6} @ ${sig['price']:>8.2f} | ADX: {sig['adx']:>5.1f} | Stoch %K: {sig['stoch_k']:>5.1f}")
    else:
        print("  ℹ️  No signals (market conditions don't support mean-reversion)")

    print(f"\n  All Signals Found (from logs): {len(bot_analysis['signals'])}")
    if bot_analysis['signals']:
        for sig_line in bot_analysis['signals'][-5:]:
            print(f"    {sig_line[:110]}")
    print()


def print_orders_placed(bot_analysis: Dict, positions: Dict):
    """Print orders placed (entries)"""
    print("📈 ORDERS PLACED (ENTRIES)")
    print("─" * 120)

    entries = bot_analysis["entries"]
    positions_list = positions.get("positions", [])

    print(f"  Total Entry Orders: {len(entries)}")
    print(f"  Open Positions: {len(positions_list)}")

    if entries:
        print(f"\n  Recent Orders (Last 10):")
        for entry in entries[-10:]:
            # Extract symbol and amount
            parts = entry.split("|")
            print(f"    {entry[:110]}")

    if positions_list:
        print(f"\n  Current Open Positions ({len(positions_list)}):")
        for pos in positions_list[-5:]:
            symbol = pos.get("symbol", "?")
            entry_price = pos.get("entry_price", 0)
            qty = pos.get("quantity", 0)
            print(f"    • {symbol:<6} | {qty} shares @ ${entry_price:.2f} | Entry: {pos.get('entry_time', 'N/A')}")
    print()


def print_orders_sold(bot_analysis: Dict):
    """Print orders sold (exits)"""
    print("📉 ORDERS SOLD (EXITS)")
    print("─" * 120)

    exits = bot_analysis["exits"]
    print(f"  Total Exits: {len(exits)}")

    if exits:
        print(f"\n  Recent Exits (Last 10):")
        for exit_line in exits[-10:]:
            print(f"    {exit_line[:110]}")
    else:
        print("  ℹ️  No exits yet (positions still open)")
    print()


def print_block_trades_analysis(block_df: pd.DataFrame):
    """Print block trades (institutional flows)"""
    print("🚨 BLOCK TRADES (INSTITUTIONAL FLOWS)")
    print("─" * 120)

    if block_df.empty:
        print("  No block trades detected yet")
        print()
        return

    print(f"  Total Block Trades: {len(block_df)}")

    # Summary by symbol
    if len(block_df) > 0:
        symbol_counts = block_df["symbol"].value_counts()
        print(f"\n  Top Symbols with Block Trades:")
        for symbol, count in symbol_counts.head(10).items():
            print(f"    • {symbol:<6}: {count} trade(s)")

    # Recent trades
    print(f"\n  Recent Block Trades (Last 10):")
    print(f"  {'Timestamp':<20} | {'Symbol':<8} | {'Price':<10} | {'Size':<12} | {'Value':<15}")
    print(f"  {'-' * 112}")

    for _, row in block_df.tail(10).iterrows():
        timestamp = str(row['timestamp'])[:19]
        symbol = str(row['symbol'])
        price = f"${row['price']:.2f}"
        size = f"{int(row['size']):,}"
        value = f"${row['notional_value']:,.0f}"
        print(f"  {timestamp:<20} | {symbol:<8} | {price:>10} | {size:>12} | {value:>15}")
    print()


def print_summary_stats(bot_analysis: Dict, block_df: pd.DataFrame):
    """Print summary statistics"""
    print("📈 SUMMARY STATISTICS")
    print("─" * 120)

    total_checked = len(bot_analysis["stocks_checked"])
    total_signals = len(bot_analysis["signals"])
    total_entries = len(bot_analysis["entries"])
    total_exits = len(bot_analysis["exits"])
    total_blocks = len(block_df)

    print(f"  Stocks Checked:     {total_checked:>6}")
    print(f"  Signals Generated:  {total_signals:>6}")
    print(f"  Orders Placed:      {total_entries:>6}")
    print(f"  Orders Sold:        {total_exits:>6}")
    print(f"  Block Trades Found: {total_blocks:>6}")

    # Win rate calculation
    if total_entries > 0:
        win_rate = (total_exits / total_entries) * 100 if total_exits > 0 else 0
        print(f"  Exit Rate:          {win_rate:>6.1f}%")

    # Cycles info
    print(f"  Cycles Run:         {bot_analysis['cycles']:>6}")
    print()


def print_footer():
    """Print footer"""
    print("=" * 120)
    print("Use this dashboard to analyze trading activity and institutional block flows".center(120))
    print("=" * 120 + "\n")


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Run analytics dashboard"""
    print_header()

    # Load all data
    bot_analysis = load_bot_log_analysis()
    block_trades = load_block_trades_analysis()
    positions = load_positions_tracking()
    signals = load_schwab_signals()

    # Print sections
    print_stocks_checked(bot_analysis)
    print_signals_generated(bot_analysis, signals)
    print_orders_placed(bot_analysis, positions)
    print_orders_sold(bot_analysis)
    print_block_trades_analysis(block_trades)
    print_summary_stats(bot_analysis, block_trades)
    print_footer()


if __name__ == "__main__":
    main()
