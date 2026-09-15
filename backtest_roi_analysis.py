#!/usr/bin/env python3
"""
ROI Backtest Analysis: Mean-Reversion Strategy with $2000 Budget
Tests historical performance over 12-24 months of data
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json

# Configuration
TOTAL_BUDGET = 2000
MAX_POSITION = 600
CONFIDENCE_THRESHOLD = 55

# Mean-reversion parameters (optimized from backtests)
SPIKE_MIN_PCT = 5.0
SPIKE_MAX_PCT = 8.0
PULLBACK_MIN_PCT = 1.0
PULLBACK_MAX_PCT = 4.0

# Exit parameters
EXIT_1_PCT = 0.0075   # 50% @ +0.75%
EXIT_2_PCT = 0.02     # 50% @ +2%
STOP_LOSS_PCT = -0.005  # -0.5% protection

class MeanReversionBacktester:
    def __init__(self, budget=2000, max_position=600):
        self.budget = budget
        self.max_position = max_position
        self.cash = budget
        self.positions = {}  # {symbol: {qty, entry_price, entry_date}}
        self.trades = []
        self.daily_values = []

    def get_historical_data(self, symbol, start_date, end_date):
        """Fetch historical data"""
        try:
            df = yf.download(symbol, start=start_date, end=end_date, progress=False)
            return df
        except:
            return None

    def detect_spike_and_pullback(self, df, symbol):
        """
        Detect mean-reversion opportunities:
        - Spike up 5-8%
        - Pull back 1-4%
        Returns list of (date, entry_price)
        """
        entries = []

        for i in range(1, len(df)):
            prev_close = float(df['Close'].iloc[i-1])
            curr_high = float(df['High'].iloc[i])
            curr_low = float(df['Low'].iloc[i])
            curr_close = float(df['Close'].iloc[i])

            # Spike: high vs previous close
            spike_pct = (curr_high - prev_close) / prev_close

            # Pullback: low vs high
            pullback_pct = (curr_low - curr_high) / curr_high

            # Entry condition
            if SPIKE_MIN_PCT/100 <= spike_pct <= SPIKE_MAX_PCT/100:
                if -PULLBACK_MAX_PCT/100 <= pullback_pct <= -PULLBACK_MIN_PCT/100:
                    entry_price = curr_low * 1.001  # Entry at pullback low
                    entries.append({
                        'date': df.index[i],
                        'entry_price': entry_price,
                        'spike_pct': spike_pct,
                        'pullback_pct': pullback_pct
                    })

        return entries

    def simulate_exit(self, df, entry_date, entry_price):
        """
        Simulate exit fills after entry.
        Returns (exit_type, exit_price, exit_date, pnl_pct)
        """
        try:
            entry_idx = df.index.get_loc(entry_date)
        except:
            return None

        exit_1_price = entry_price * (1 + EXIT_1_PCT)
        exit_2_price = entry_price * (1 + EXIT_2_PCT)
        stop_loss_price = entry_price * (1 + STOP_LOSS_PCT)

        # Look forward 5 days for exit
        for i in range(entry_idx + 1, min(entry_idx + 6, len(df))):
            high = float(df['High'].iloc[i])
            low = float(df['Low'].iloc[i])
            exit_date = df.index[i]

            # Stop loss first
            if low <= stop_loss_price:
                return {
                    'type': 'stop_loss',
                    'price': stop_loss_price,
                    'date': exit_date,
                    'pnl_pct': STOP_LOSS_PCT
                }

            # Exit 1 (50% @ +0.75%)
            if high >= exit_1_price:
                return {
                    'type': 'exit_1',
                    'price': exit_1_price,
                    'date': exit_date,
                    'pnl_pct': EXIT_1_PCT
                }

            # Exit 2 (50% @ +2%)
            if high >= exit_2_price:
                return {
                    'type': 'exit_2',
                    'price': exit_2_price,
                    'date': exit_date,
                    'pnl_pct': EXIT_2_PCT
                }

        # No exit in 5 days
        if entry_idx + 5 < len(df):
            return {
                'type': 'timeout',
                'price': df['Close'].iloc[entry_idx + 5],
                'date': df.index[entry_idx + 5],
                'pnl_pct': (df['Close'].iloc[entry_idx + 5] - entry_price) / entry_price
            }

        return None

    def run_backtest(self, symbols, start_date, end_date):
        """Run backtest on multiple symbols"""
        print(f"\n{'='*70}")
        print(f"  MEAN-REVERSION BACKTEST")
        print(f"  Period: {start_date} to {end_date}")
        print(f"  Initial Budget: ${self.budget}")
        print(f"  Max Position: ${self.max_position}")
        print(f"{'='*70}\n")

        all_trades = []

        for symbol in symbols:
            print(f"  {symbol}...", end='', flush=True)

            df = self.get_historical_data(symbol, start_date, end_date)
            if df is None or df.empty:
                print(" [SKIP - no data]")
                continue

            entries = self.detect_spike_and_pullback(df, symbol)
            print(f" {len(entries)} opportunities")

            symbol_profit = 0
            symbol_trades = 0

            for entry in entries:
                # Check if we have enough budget
                if self.cash < self.max_position * 0.5:  # Need at least 50% to trade
                    break

                entry_price = entry['entry_price']
                qty = self.max_position / entry_price

                exit_info = self.simulate_exit(df, entry['date'], entry_price)
                if not exit_info:
                    continue

                # Calculate P&L
                pnl_pct = exit_info['pnl_pct']
                pnl_dollars = self.max_position * pnl_pct

                self.cash -= self.max_position
                self.cash += self.max_position * (1 + pnl_pct)

                symbol_profit += pnl_dollars
                symbol_trades += 1

                all_trades.append({
                    'symbol': symbol,
                    'entry_date': entry['date'],
                    'entry_price': entry_price,
                    'qty': qty,
                    'exit_date': exit_info['date'],
                    'exit_type': exit_info['type'],
                    'exit_price': exit_info['price'],
                    'pnl_pct': pnl_pct,
                    'pnl_dollars': pnl_dollars,
                    'spike_pct': entry['spike_pct'],
                    'pullback_pct': entry['pullback_pct']
                })

        return all_trades

    def calculate_metrics(self, trades):
        """Calculate performance metrics"""
        if not trades:
            return {}

        df_trades = pd.DataFrame(trades)

        total_invested = len(trades) * self.max_position
        total_profit = df_trades['pnl_dollars'].sum()

        winning_trades = (df_trades['pnl_dollars'] > 0).sum()
        losing_trades = (df_trades['pnl_dollars'] < 0).sum()

        win_rate = winning_trades / len(trades) if len(trades) > 0 else 0

        # Profit factor
        gross_profit = df_trades[df_trades['pnl_dollars'] > 0]['pnl_dollars'].sum()
        gross_loss = abs(df_trades[df_trades['pnl_dollars'] < 0]['pnl_dollars'].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # Max drawdown (simplified)
        cumulative_pnl = df_trades['pnl_dollars'].cumsum()
        running_max = cumulative_pnl.cummax()
        drawdown = (cumulative_pnl - running_max) / running_max
        max_drawdown = drawdown.min() if len(drawdown) > 0 else 0

        # Sharpe ratio (simplified)
        returns = df_trades['pnl_pct']
        if len(returns) > 1:
            sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
        else:
            sharpe = 0

        final_balance = self.budget + total_profit
        roi_pct = (total_profit / self.budget) * 100

        return {
            'total_trades': len(trades),
            'total_invested': total_invested,
            'total_profit': total_profit,
            'final_balance': final_balance,
            'roi_pct': roi_pct,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate * 100,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown * 100,
            'sharpe_ratio': sharpe,
            'avg_win': df_trades[df_trades['pnl_dollars'] > 0]['pnl_dollars'].mean() if winning_trades > 0 else 0,
            'avg_loss': df_trades[df_trades['pnl_dollars'] < 0]['pnl_dollars'].mean() if losing_trades > 0 else 0,
            'best_trade': df_trades['pnl_dollars'].max(),
            'worst_trade': df_trades['pnl_dollars'].min(),
        }

# Run backtest
if __name__ == "__main__":
    # Use S&P 500 top movers (tech-heavy for mean reversion)
    symbols = [
        "INTC", "AMD", "NVDA", "LRCX", "AVGO", "KEYS", "AMAT", "TXN", "ADI",
        "CSCO", "ENPH", "JPM", "SNPS", "CRM", "NOW", "MSFT", "CDNS", "IBM",
        "BA", "MCD", "CAT", "PG", "HD", "MA", "V", "GS", "BAC", "WFC",
        "XOM", "CVX", "MRK", "JNJ", "PFE", "ABBV"
    ]

    # Backtest periods
    end_date = datetime.now()
    start_date = end_date - timedelta(days=730)  # 2 years

    print(f"\nBacktesting {len(symbols)} stocks over 24 months")
    print(f"Date range: {start_date.date()} to {end_date.date()}")

    backtester = MeanReversionBacktester(budget=2000, max_position=600)
    trades = backtester.run_backtest(symbols, start_date, end_date)

    metrics = backtester.calculate_metrics(trades)

    # Print results
    print(f"\n{'='*70}")
    print(f"  BACKTEST RESULTS")
    print(f"{'='*70}\n")

    print(f"  Initial Investment:      ${metrics['total_invested']:,.2f}")
    print(f"  Total Profit:            ${metrics['total_profit']:+,.2f}")
    print(f"  Final Balance:           ${metrics['final_balance']:,.2f}")
    print(f"  ROI:                     {metrics['roi_pct']:+.2f}%")
    print(f"\n  Trades:")
    print(f"    Total:                 {metrics['total_trades']}")
    print(f"    Winning:               {metrics['winning_trades']} ({metrics['win_rate']:.1f}%)")
    print(f"    Losing:                {metrics['losing_trades']}")
    print(f"\n  Risk Metrics:")
    print(f"    Profit Factor:         {metrics['profit_factor']:.2f}")
    print(f"    Max Drawdown:          {metrics['max_drawdown']:.2f}%")
    print(f"    Sharpe Ratio:          {metrics['sharpe_ratio']:.2f}")
    print(f"\n  Trade Statistics:")
    print(f"    Best Trade:            ${metrics['best_trade']:+,.2f}")
    print(f"    Worst Trade:           ${metrics['worst_trade']:+,.2f}")
    print(f"    Avg Win:               ${metrics['avg_win']:+,.2f}")
    print(f"    Avg Loss:              ${metrics['avg_loss']:+,.2f}")

    # Annual projection
    days_in_backtest = (end_date - start_date).days
    annual_roi = metrics['roi_pct'] * (365 / days_in_backtest)
    annual_profit = metrics['total_profit'] * (365 / days_in_backtest)

    print(f"\n  Annualized (if sustained):")
    print(f"    Annual ROI:            {annual_roi:+.2f}%")
    print(f"    Annual Profit:         ${annual_profit:+,.2f}")

    print(f"\n{'='*70}\n")

    # Summary statistics
    if trades:
        df = pd.DataFrame(trades)
        print(f"  Trade Summary by Exit Type:")
        print(f"    {df['exit_type'].value_counts().to_dict()}\n")

        print(f"  Top 5 Winners:")
        for idx, row in df.nlargest(5, 'pnl_dollars').iterrows():
            print(f"    {row['symbol']} ({row['exit_type']:12s}): ${row['pnl_dollars']:+7.2f}")

        print(f"\n  Top 5 Losers:")
        for idx, row in df.nsmallest(5, 'pnl_dollars').iterrows():
            print(f"    {row['symbol']} ({row['exit_type']:12s}): ${row['pnl_dollars']:+7.2f}")
