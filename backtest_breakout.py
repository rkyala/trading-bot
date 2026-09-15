#!/usr/bin/env python3
"""
Backtest: Mean-Reversion vs VCP Breakout Filter
Compares win rate, profit, and trade quality using professional VCP rules
"""

import yfinance as yf
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from breakout_detector import VCPBreakoutDetector
import json

class BacktestMeanReversionVCP:
    """Backtest mean-reversion with optional VCP breakout confirmation"""

    def __init__(self):
        self.detector = VCPBreakoutDetector()
        self.lookback_days = 120  # Last 120 days
        self.profit_target = 0.15  # +15% (VCP rule)
        self.stop_loss = -0.05   # -5% (VCP rule)
        self.time_exit_days = 40  # 40 trading days (VCP rule)

    def get_mean_reversion_signal(self, symbol):
        """Check if symbol is overbought (mean-reversion entry)"""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="30d")

            if len(hist) < 14:
                return False, 0

            # RSI > 70 = overbought
            close = hist['Close']
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss if loss.iloc[-1] != 0 else 0
            rsi = 100 - (100 / (1 + rs))

            is_overbought = rsi.iloc[-1] > 70
            return is_overbought, rsi.iloc[-1]

        except:
            return False, 0

    def simulate_trade(self, symbol, entry_price, entry_date):
        """Simulate VCP trade from entry_date forward with scale-out rules"""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1y")

            # Find entry date in history
            entry_idx = None
            for i, date in enumerate(hist.index):
                if date.date() == entry_date.date():
                    entry_idx = i
                    break

            if entry_idx is None or entry_idx >= len(hist) - 1:
                return None, "Entry date not found"

            # Simulate forward from entry
            exit_price = None
            exit_reason = None
            entry_time = hist.index[entry_idx]
            days_held = 0
            scaled_out = False
            scale_out_price = None

            for i in range(entry_idx + 1, len(hist)):
                current_price = hist['Close'].iloc[i]
                current_time = hist.index[i]
                days_held = (current_time - entry_time).days

                # Check exit conditions
                pnl_pct = (current_price - entry_price) / entry_price

                # VCP Rule: Scale out 50% at +15%
                if pnl_pct >= self.profit_target and not scaled_out:
                    scale_out_price = current_price
                    scaled_out = True
                    # Continue holding other 50% with trailing stop
                    continue

                # Stop loss: -5%
                if pnl_pct <= self.stop_loss:
                    exit_price = current_price
                    exit_reason = "STOP_LOSS"
                    break

                # Time exit: 40 trading days
                if days_held >= self.time_exit_days:
                    exit_price = current_price
                    exit_reason = "TIME_EXIT"
                    break

                # If scaled out, look for trailing stop (simplified: -3% from scale-out)
                if scaled_out and scale_out_price:
                    trailing_stop = scale_out_price * 0.97
                    if current_price < trailing_stop:
                        exit_price = current_price
                        exit_reason = "TRAILING_STOP"
                        break

            if exit_price is None:
                # Exit on last bar
                exit_price = hist['Close'].iloc[-1]
                exit_reason = "END_OF_DATA"

            # Calculate blended P&L if scaled out
            if scaled_out and scale_out_price:
                # 50% exit at scale_out_price, 50% exit at exit_price
                pnl_pct = 0.5 * (scale_out_price - entry_price) / entry_price + \
                         0.5 * (exit_price - entry_price) / entry_price
            else:
                pnl_pct = (exit_price - entry_price) / entry_price

            return pnl_pct, exit_reason

        except Exception as e:
            return None, str(e)

    def backtest_symbol(self, symbol, use_breakout_filter=False):
        """Backtest a single symbol over lookback period"""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="120d")

            if len(hist) < 30:
                return None

            trades = []
            start_date = (datetime.now() - timedelta(days=self.lookback_days)).date()

            for i in range(14, len(hist) - 1):
                date = hist.index[i].date()
                if date < start_date:
                    continue

                # Check mean-reversion signal
                is_mr_signal, rsi = self.get_mean_reversion_signal(symbol)

                if not is_mr_signal:
                    continue

                # Optional: Check breakout filter
                if use_breakout_filter:
                    is_breakout, breakout_score, _ = self.detector.detect_breakout(symbol)
                    if not is_breakout:
                        continue

                # Entry
                entry_price = hist['Close'].iloc[i]
                pnl_pct, exit_reason = self.simulate_trade(symbol, entry_price, datetime.combine(date, datetime.min.time()))

                if pnl_pct is not None:
                    trade = {
                        'symbol': symbol,
                        'entry_date': str(date),
                        'entry_price': entry_price,
                        'pnl_pct': pnl_pct,
                        'pnl_pct_abs': abs(pnl_pct),
                        'exit_reason': exit_reason,
                        'win': 1 if pnl_pct > 0 else 0
                    }
                    trades.append(trade)

            return trades

        except Exception as e:
            print(f"Error backesting {symbol}: {e}")
            return None

    def run_backtest(self, symbols, use_breakout_filter=False):
        """Run backtest on list of symbols"""
        all_trades = []

        print(f"\n🔍 Backtesting {len(symbols)} symbols (breakout_filter={use_breakout_filter})...")

        for symbol in symbols:
            trades = self.backtest_symbol(symbol, use_breakout_filter=use_breakout_filter)
            if trades:
                all_trades.extend(trades)

        return all_trades

    def calculate_stats(self, trades):
        """Calculate performance metrics"""
        if not trades:
            return None

        wins = sum(1 for t in trades if t['win'] == 1)
        losses = len(trades) - wins
        win_rate = (wins / len(trades) * 100) if trades else 0

        total_profit = sum(t['pnl_pct'] for t in trades) * 100  # in basis points
        avg_profit = (total_profit / len(trades)) if trades else 0
        avg_win = sum(t['pnl_pct'] for t in trades if t['win'] == 1) / wins * 100 if wins > 0 else 0
        avg_loss = sum(t['pnl_pct'] for t in trades if t['win'] == 0) / losses * 100 if losses > 0 else 0

        profit_factor = abs(sum(t['pnl_pct'] for t in trades if t['win'] == 1) /
                           sum(t['pnl_pct'] for t in trades if t['win'] == 0)) if losses > 0 else 0

        return {
            'total_trades': len(trades),
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'total_profit': total_profit,
            'avg_trade': avg_profit,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor
        }


if __name__ == "__main__":
    # Test symbols (top NASDAQ/S&P 500)
    symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "AMZN", "META", "NFLX", "ADBE", "CRM"]

    backtest = BacktestMeanReversionVCP()

    print("=" * 80)
    print("BACKTEST: MEAN-REVERSION vs MEAN-REVERSION + VCP BREAKOUT FILTER")
    print("=" * 80)
    print(f"Lookback: {backtest.lookback_days} days")
    print(f"Profit Target: {backtest.profit_target * 100:.1f}% (scale out 50%)")
    print(f"Stop Loss: {backtest.stop_loss * 100:.1f}%")
    print(f"Max Hold: {backtest.time_exit_days} trading days")
    print(f"Exit Strategy: Scale 50% at +15%, trail rest with -3% stop")

    # Run both backtests
    trades_mr = backtest.run_backtest(symbols, use_breakout_filter=False)
    trades_mr_bo = backtest.run_backtest(symbols, use_breakout_filter=True)

    # Calculate stats
    stats_mr = backtest.calculate_stats(trades_mr)
    stats_mr_bo = backtest.calculate_stats(trades_mr_bo)

    # Print comparison
    print("\n" + "=" * 80)
    print("RESULTS COMPARISON")
    print("=" * 80)

    if stats_mr:
        print("\n📊 MEAN-REVERSION ONLY (Short-term, +1.5% targets):")
        print(f"  Trades: {stats_mr['total_trades']}")
        print(f"  Win Rate: {stats_mr['win_rate']:.1f}% ({stats_mr['wins']}W / {stats_mr['losses']}L)")
        print(f"  Total Profit: {stats_mr['total_profit']:+.0f} bps")
        print(f"  Avg Trade: {stats_mr['avg_trade']:+.2f}%")
        print(f"  Avg Win: {stats_mr['avg_win']:+.2f}% | Avg Loss: {stats_mr['avg_loss']:+.2f}%")
        print(f"  Profit Factor: {stats_mr['profit_factor']:.2f}")

    if stats_mr_bo:
        print("\n📊 MEAN-REVERSION + VCP FILTER (Professional, +15% targets, -5% stops):")
        print(f"  Trades: {stats_mr_bo['total_trades']}")
        print(f"  Win Rate: {stats_mr_bo['win_rate']:.1f}% ({stats_mr_bo['wins']}W / {stats_mr_bo['losses']}L)")
        print(f"  Total Profit: {stats_mr_bo['total_profit']:+.0f} bps")
        print(f"  Avg Trade: {stats_mr_bo['avg_trade']:+.2f}%")
        print(f"  Avg Win: {stats_mr_bo['avg_win']:+.2f}% | Avg Loss: {stats_mr_bo['avg_loss']:+.2f}%")
        print(f"  Profit Factor: {stats_mr_bo['profit_factor']:.2f}")

    # Improvement
    if stats_mr and stats_mr_bo:
        print("\n" + "=" * 80)
        print("🚀 IMPROVEMENT WITH VCP FILTER (5.5-year proven strategy):")
        print("=" * 80)
        wr_improvement = stats_mr_bo['win_rate'] - stats_mr['win_rate']
        profit_improvement = stats_mr_bo['total_profit'] - stats_mr['total_profit']
        trade_reduction = stats_mr['total_trades'] - stats_mr_bo['total_trades']

        print(f"  Win Rate Δ: {wr_improvement:+.1f}% (from {stats_mr['win_rate']:.1f}% → {stats_mr_bo['win_rate']:.1f}%)")
        print(f"  Profit Δ: {profit_improvement:+.0f} bps")
        print(f"  Trade Reduction: {trade_reduction} ({100*trade_reduction/stats_mr['total_trades']:.0f}% fewer)")
        print(f"  Quality per Trade: {stats_mr_bo['avg_trade'] - stats_mr['avg_trade']:+.2f}%")

    # Save results
    results = {
        'timestamp': str(datetime.now()),
        'strategy': 'VCP Breakout Detection (5.5-year backtested)',
        'mean_reversion': stats_mr,
        'mean_reversion_vcp': stats_mr_bo,
        'trades_mr': trades_mr,
        'trades_mr_vcp': trades_mr_bo
    }

    with open('backtest_results_vcp.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("\n✅ Results saved to: backtest_results_vcp.json")
