#!/usr/bin/env python3
"""
Backtest PULLBACK TRACKING strategy - waits for dips before buying.

Current bot: Tries to buy on spike day (low confidence, few trades)
New strategy: Tracks spikes, buys on pullback (high confidence, more trades)

Tests if waiting for pullback -1% to -4% generates better mean-reversion signals.
"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json

# Config
START_DATE = "2026-04-27"
END_DATE = "2026-07-27"
TOTAL_BUDGET = 2000
MAX_POSITION = 600
CONFIDENCE_THRESHOLD = 55

# S&P 500 + NASDAQ-50 watchlist
WATCHLIST = [
    'NVDA', 'MSFT', 'META', 'GOOGL', 'AMZN', 'TSLA', 'AAPL', 'NFLX', 'SNPS', 'ADBE',
    'CRM', 'NOW', 'ACN', 'CDNS', 'INTU', 'BKNG', 'V', 'MA', 'AMAT', 'LRCX',
    'AMD', 'INTC', 'KEYS', 'ADI', 'MU', 'AVGO', 'AXP', 'BA', 'CAT', 'GE',
    'RTX', 'JNJ', 'PFE', 'KO', 'PEP', 'WMT', 'MCD', 'CMCSA', 'VZ', 'CVX',
    'XOM', 'COP', 'GILD', 'AMGN', 'LLY', 'AZO', 'COST', 'HD', 'PCAR', 'ENPH'
]

def backtest_pullback_tracking():
    """Test strategy: Track spikes, buy on pullback."""
    print(f"Loading 3-month historical data ({START_DATE} to {END_DATE})...")

    # Fetch data
    data = yf.download(' '.join(WATCHLIST), start=START_DATE, end=END_DATE, progress=False)['Close']
    dates = data.index.tolist()

    trades = []
    cash = TOTAL_BUDGET
    positions = {}  # {symbol: {'entry_price': X, 'qty': Y, 'entry_date': Z}}
    watchlist = {}  # {symbol: {'spike_date': D, 'spike_price': P, 'spike_pct': %}}

    print(f"Backtesting {len(dates)} trading days with PULLBACK TRACKING...\n")

    spike_count = 0
    pullback_count = 0

    for day_idx, date in enumerate(dates[1:], start=1):
        prev_date = dates[day_idx - 1]

        # Get prices
        today_prices = data.loc[date]
        prev_prices = data.loc[prev_date]
        pct_changes = ((today_prices - prev_prices) / prev_prices * 100).dropna()

        # STAGE 1: Detect new spikes (2%+, lower threshold to catch more)
        spike_threshold_min = 2.0
        new_spikes = pct_changes[pct_changes >= spike_threshold_min]

        for symbol, pct in new_spikes.items():
            if symbol not in watchlist and symbol not in positions:
                watchlist[symbol] = {
                    'spike_date': prev_date,
                    'spike_price': prev_prices[symbol],
                    'spike_pct': pct,
                    'spike_high': today_prices[symbol]
                }
                spike_count += 1

        # STAGE 2: Check watchlist for pullbacks
        buy_signals = []
        symbols_to_remove = []

        for symbol in list(watchlist.keys()):
            if symbol not in today_prices.index or symbol in positions:
                continue

            watchlist_entry = watchlist[symbol]
            spike_high = watchlist_entry['spike_high']
            current_price = today_prices[symbol]
            pullback_pct = (current_price - spike_high) / spike_high * 100

            # Pullback -0.5% to -3%? = Mean-reversion entry point (more lenient)
            if -3.0 <= pullback_pct <= -0.5:
                # High confidence: spike happened + pullback confirmed
                confidence = min(70 + int(abs(pullback_pct) * 5), 85)
                buy_signals.append({
                    'symbol': symbol,
                    'confidence': confidence,
                    'spike_pct': watchlist_entry['spike_pct'],
                    'pullback_pct': pullback_pct,
                    'entry_price': current_price
                })
                pullback_count += 1
                symbols_to_remove.append(symbol)

            # If no pullback after 5 days or too deep (< -5%), remove from watchlist
            else:
                days_in_watchlist = (date - watchlist_entry['spike_date']).days
                if days_in_watchlist > 5 or pullback_pct < -5.0:
                    symbols_to_remove.append(symbol)

        # Remove symbols from watchlist
        for symbol in symbols_to_remove:
            if symbol in watchlist:
                del watchlist[symbol]

        # STAGE 3: Execute buy signals (mean-reversion buys)
        for signal in buy_signals:
            symbol = signal['symbol']
            confidence = signal['confidence']

            if confidence < CONFIDENCE_THRESHOLD:
                continue

            entry_price = signal['entry_price']
            qty = min(MAX_POSITION // int(entry_price), int(cash / entry_price))

            if qty == 0 or cash < entry_price * qty:
                continue

            # Execute buy
            cost = entry_price * qty
            cash -= cost
            positions[symbol] = {
                'entry_price': entry_price,
                'qty': qty,
                'entry_date': date,
                'confidence': confidence,
                'spike_pct': signal['spike_pct'],
                'pullback_pct': signal['pullback_pct']
            }

            # Remove from watchlist
            if symbol in watchlist:
                del watchlist[symbol]

        # STAGE 4: Exit logic (50% at +0.75%, 50% at +2%)
        closed_positions = []
        for symbol in list(positions.keys()):
            if symbol not in today_prices.index:
                continue

            pos = positions[symbol]
            current_price = today_prices[symbol]
            pnl_pct = (current_price - pos['entry_price']) / pos['entry_price'] * 100
            days_held = (date - pos['entry_date']).days

            # Exit half at +1% (quick recovery)
            if pnl_pct >= 1.0 and 'half_sold' not in pos:
                exit_qty = pos['qty'] // 2
                exit_price = current_price
                pnl = (exit_price - pos['entry_price']) * exit_qty
                cash += exit_price * exit_qty

                positions[symbol]['qty'] -= exit_qty
                positions[symbol]['half_sold'] = True

                if exit_qty > 0:
                    trades.append({
                        'symbol': symbol,
                        'entry_date': pos['entry_date'],
                        'exit_date': date,
                        'entry_price': pos['entry_price'],
                        'exit_price': exit_price,
                        'qty': exit_qty,
                        'pnl': pnl,
                        'pnl_pct': pnl_pct,
                        'days': days_held,
                        'confidence': pos['confidence'],
                        'reason': 'partial_+1%'
                    })

            # Exit rest at +3% OR -2% stop OR 4 days
            if positions[symbol]['qty'] > 0:
                if pnl_pct >= 3.0 or pnl_pct <= -2.0 or days_held >= 4:
                    exit_qty = positions[symbol]['qty']
                    exit_price = current_price
                    pnl = (exit_price - pos['entry_price']) * exit_qty
                    cash += exit_price * exit_qty

                    trades.append({
                        'symbol': symbol,
                        'entry_date': pos['entry_date'],
                        'exit_date': date,
                        'entry_price': pos['entry_price'],
                        'exit_price': exit_price,
                        'qty': exit_qty,
                        'pnl': pnl,
                        'pnl_pct': pnl_pct,
                        'days': days_held,
                        'confidence': pos['confidence'],
                        'reason': f'exit_{pnl_pct:+.1f}%'
                    })
                    closed_positions.append(symbol)

        # Remove closed positions
        for symbol in closed_positions:
            del positions[symbol]

    # Close remaining positions at end
    last_price = data.loc[dates[-1]]
    for symbol in list(positions.keys()):
        pos = positions[symbol]
        exit_price = last_price[symbol]
        pnl = (exit_price - pos['entry_price']) * pos['qty']
        trades.append({
            'symbol': symbol,
            'entry_date': pos['entry_date'],
            'exit_date': dates[-1],
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'qty': pos['qty'],
            'pnl': pnl,
            'pnl_pct': (exit_price - pos['entry_price']) / pos['entry_price'] * 100,
            'days': (dates[-1] - pos['entry_date']).days,
            'confidence': pos['confidence'],
            'reason': 'backtest_end'
        })

    # Calculate metrics
    df_trades = pd.DataFrame(trades)

    print(f"\nDebug: {spike_count} spikes detected, {pullback_count} pullbacks found")

    if len(df_trades) == 0:
        print("❌ NO TRADES EXECUTED")
        return

    total_pnl = df_trades['pnl'].sum()
    winning_trades = len(df_trades[df_trades['pnl'] > 0])
    losing_trades = len(df_trades[df_trades['pnl'] < 0])
    win_rate = winning_trades / len(df_trades) * 100
    avg_profit = df_trades[df_trades['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
    avg_loss = df_trades[df_trades['pnl'] < 0]['pnl'].mean() if losing_trades > 0 else 0

    final_capital = cash
    roi = (final_capital - TOTAL_BUDGET) / TOTAL_BUDGET * 100

    print("=" * 70)
    print("BACKTEST: PULLBACK TRACKING STRATEGY (3 months: Apr-Jul 2026)")
    print("=" * 70)
    print(f"Total Trades:        {len(df_trades)}")
    print(f"Winning Trades:      {winning_trades} ({win_rate:.1f}%)")
    print(f"Losing Trades:       {losing_trades}")
    print(f"Avg Profit/Trade:    ${avg_profit:.2f}")
    print(f"Avg Loss/Trade:      ${avg_loss:.2f}")
    print(f"Total PnL:           ${total_pnl:,.2f}")
    print(f"Final Capital:       ${final_capital:,.2f}")
    print(f"ROI:                 {roi:+.2f}%")
    print(f"Risk/Reward Ratio:   {abs(avg_profit / avg_loss):.2f}x" if avg_loss != 0 else "N/A")
    print("=" * 70)

    # Show best/worst trades
    if len(df_trades) > 0:
        best_trade = df_trades.loc[df_trades['pnl'].idxmax()]
        worst_trade = df_trades.loc[df_trades['pnl'].idxmin()]

        print(f"\n📈 Best Trade:  {best_trade['symbol']} @ ${best_trade['entry_price']:.2f} → ${best_trade['exit_price']:.2f} | +{best_trade['pnl_pct']:.1f}% | ${best_trade['pnl']:.2f}")
        print(f"📉 Worst Trade: {worst_trade['symbol']} @ ${worst_trade['entry_price']:.2f} → ${worst_trade['exit_price']:.2f} | {worst_trade['pnl_pct']:.1f}% | ${worst_trade['pnl']:.2f}")

    return {
        'trades': len(df_trades),
        'win_rate': win_rate,
        'roi': roi,
        'total_pnl': total_pnl,
        'final_capital': final_capital
    }

if __name__ == "__main__":
    backtest_pullback_tracking()
