#!/usr/bin/env python3
"""
3-month backtest of trading bot strategy (Apr-Jul 2026).
Tests Stage 1 anomaly detection + Stage 2 confidence scoring + Stage 3 execution.
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
MAX_POSITION = 500
CONFIDENCE_THRESHOLD = 55

# S&P 500 + NASDAQ-50 watchlist
WATCHLIST = [
    'NVDA', 'MSFT', 'META', 'GOOGL', 'AMZN', 'TSLA', 'AAPL', 'NFLX', 'SNPS', 'ADBE',
    'CRM', 'NOW', 'ACN', 'CDNS', 'INTU', 'BKNG', 'V', 'MA', 'AMAT', 'LRCX',
    'AMD', 'INTC', 'KEYS', 'ADI', 'MU', 'AVGO', 'AXP', 'BA', 'CAT', 'GE',
    'RTX', 'JNJ', 'PFE', 'KO', 'PEP', 'WMT', 'MCD', 'CMCSA', 'VZ', 'CVX',
    'XOM', 'COP', 'GILD', 'AMGN', 'LLY', 'AZO', 'COST', 'HD', 'PCAR', 'ENPH'
]

def backtest():
    print(f"Loading 3-month historical data ({START_DATE} to {END_DATE})...")

    # Fetch data
    data = yf.download(' '.join(WATCHLIST), start=START_DATE, end=END_DATE, progress=False)['Close']
    dates = data.index.tolist()

    trades = []
    cash = TOTAL_BUDGET
    positions = {}  # {symbol: {'entry_price': X, 'qty': Y, 'entry_date': Z}}
    daily_cash_flow = []

    print(f"Backtesting {len(dates)} trading days...\n")

    for day_idx, date in enumerate(dates[1:], start=1):  # Skip first day (no prior close)
        prev_date = dates[day_idx - 1]

        # Stage 1: Detect anomalies (daily % change > 2%)
        today_prices = data.loc[date]
        prev_prices = data.loc[prev_date]
        pct_changes = ((today_prices - prev_prices) / prev_prices * 100).dropna()

        # Find top movers (anomalies)
        top_gainers = pct_changes[pct_changes > 2].nlargest(3)  # Top 3 gainers

        if len(top_gainers) == 0:
            continue

        # Stage 2: Assign confidence to top 3 (mandate output)
        # Simple rule: map % change to confidence
        candidates = []
        for symbol, pct_change in top_gainers.items():
            confidence = min(55 + int(pct_change * 3), 85)  # Scale: +5% → 60, +9% → 82
            candidates.append({'symbol': symbol, 'confidence': confidence, 'pct': pct_change})

        # Stage 3: Execute trades (top-3 mandate)
        entry_date = date
        for candidate in candidates:
            symbol = candidate['symbol']
            confidence = candidate['confidence']

            if confidence < CONFIDENCE_THRESHOLD:
                continue

            # Skip if already holding
            if symbol in positions:
                continue

            # Calculate position size
            qty = min(MAX_POSITION // int(today_prices[symbol]), int(cash / today_prices[symbol]))
            if qty == 0 or cash < today_prices[symbol] * qty:
                continue

            # Enter trade
            entry_price = today_prices[symbol]
            cost = entry_price * qty
            cash -= cost
            positions[symbol] = {
                'entry_price': entry_price,
                'qty': qty,
                'entry_date': entry_date,
                'confidence': confidence
            }

        # Exit logic: Check if any positions hit exit targets
        closed_positions = []
        for symbol in list(positions.keys()):
            if symbol not in today_prices.index:
                continue

            pos = positions[symbol]
            current_price = today_prices[symbol]
            pnl_pct = (current_price - pos['entry_price']) / pos['entry_price'] * 100
            days_held = (date - pos['entry_date']).days

            # Exit rule: 50% exits at +2%, ride the rest to +5% or -3%
            if pnl_pct >= 2.0:  # Exit half at +2%
                exit_qty = pos['qty'] // 2
                exit_price = current_price
                pnl = (exit_price - pos['entry_price']) * exit_qty
                cash += exit_price * exit_qty

                # Reduce position (ride other half)
                positions[symbol]['qty'] -= exit_qty

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
                        'reason': 'partial_exit_+2%'
                    })

            # Ride rest to +5% or -3%
            if positions[symbol]['qty'] > 0:  # Still holding second half
                if pnl_pct >= 5.0 or pnl_pct <= -3.0 or days_held >= 2:
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

        daily_cash_flow.append({'date': date, 'cash': cash, 'positions': len(positions)})

    # Close all remaining positions at last date
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

    if len(df_trades) == 0:
        print("❌ NO TRADES EXECUTED (backtest failed)")
        return

    total_pnl = df_trades['pnl'].sum()
    winning_trades = len(df_trades[df_trades['pnl'] > 0])
    losing_trades = len(df_trades[df_trades['pnl'] < 0])
    win_rate = winning_trades / len(df_trades) * 100 if len(df_trades) > 0 else 0
    avg_profit = df_trades[df_trades['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
    avg_loss = df_trades[df_trades['pnl'] < 0]['pnl'].mean() if losing_trades > 0 else 0

    final_capital = cash
    roi = (final_capital - TOTAL_BUDGET) / TOTAL_BUDGET * 100

    print("=" * 70)
    print("BACKTEST RESULTS (3 months: Apr-Jul 2026)")
    print("=" * 70)
    print(f"Total Trades:        {len(df_trades)}")
    print(f"Winning Trades:      {winning_trades} ({win_rate:.1f}%)")
    print(f"Losing Trades:       {losing_trades}")
    print(f"Avg Win:             ${avg_profit:,.2f}")
    print(f"Avg Loss:            ${avg_loss:,.2f}")
    print(f"\nTotal P&L:           ${total_pnl:,.2f}")
    print(f"Starting Capital:    ${TOTAL_BUDGET:,.2f}")
    print(f"Final Capital:       ${final_capital:,.2f}")
    print(f"ROI:                 {roi:+.2f}%")
    print("=" * 70)

    # Top trades
    print("\nTop 5 Winning Trades:")
    top_wins = df_trades.nlargest(5, 'pnl')[['symbol', 'entry_date', 'exit_date', 'entry_price', 'exit_price', 'pnl', 'pnl_pct', 'confidence']]
    for idx, trade in top_wins.iterrows():
        print(f"  {trade['symbol']:5s} {trade['entry_date'].date()} → {trade['exit_date'].date():10s} | Entry ${trade['entry_price']:.2f} Exit ${trade['exit_price']:.2f} | P&L ${trade['pnl']:+7.2f} ({trade['pnl_pct']:+.1f}%) [Conf:{trade['confidence']}]")

    print("\nTop 5 Losing Trades:")
    top_losses = df_trades.nsmallest(5, 'pnl')[['symbol', 'entry_date', 'exit_date', 'entry_price', 'exit_price', 'pnl', 'pnl_pct', 'confidence']]
    for idx, trade in top_losses.iterrows():
        print(f"  {trade['symbol']:5s} {trade['entry_date'].date()} → {trade['exit_date'].date():10s} | Entry ${trade['entry_price']:.2f} Exit ${trade['exit_price']:.2f} | P&L ${trade['pnl']:+7.2f} ({trade['pnl_pct']:+.1f}%) [Conf:{trade['confidence']}]")

    # Verdict
    print("\n" + "=" * 70)
    if roi > 0:
        print(f"✅ STRATEGY IS PROFITABLE: +{roi:.2f}% ROI over 3 months")
    else:
        print(f"❌ STRATEGY IS LOSING: {roi:.2f}% ROI over 3 months")
    print("=" * 70)

if __name__ == '__main__':
    backtest()
