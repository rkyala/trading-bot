#!/usr/bin/env python3
"""
Backtest: Regime-Switching Strategy
Compares:
1. Pure Mean-Reversion
2. Pure Breakout (VCP)
3. Regime-Switching (Mean-Reversion in RANGING + Breakout in TRENDING)
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from regime_router import RegimeRouter
import json

class RegimeSwitchingBacktest:
    """Backtest regime-switching performance"""

    def __init__(self):
        self.router = RegimeRouter()
        self.lookback_days = 60
        self.profit_target = 0.015  # +1.5% for MR, +15% for BO
        self.stop_loss_mr = -0.015  # -1.5% for mean-reversion
        self.stop_loss_bo = -0.05   # -5% for breakout
        self.time_exit_hours_mr = 4  # 4 hours for mean-reversion
        self.time_exit_days_bo = 40  # 40 days for breakout

    def get_mean_reversion_signal(self, hist):
        """RSI > 70 = overbought"""
        close = hist['Close']
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss if loss.iloc[-1] != 0 else 1
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1] > 70, rsi.iloc[-1]

    def get_breakout_signal(self, hist):
        """Price > 20-day high on volume"""
        close = hist['Close'].iloc[-1]
        high_20d = hist['High'].iloc[-20:].max()
        volume = hist['Volume'].iloc[-1]
        vol_50d_avg = hist['Volume'].rolling(50).mean().iloc[-1]
        is_breakout = (close > high_20d) and (volume >= vol_50d_avg * 1.5)
        return is_breakout, close

    def get_regime_data(self, hist):
        """Get regime detection data"""
        current_price = hist['Close'].iloc[-1]
        high_52w = hist['High'].iloc[-252:].max()
        low_52w = hist['Low'].iloc[-252:].min()
        current_vol = hist['Close'].pct_change().iloc[-20:].std()
        avg_vol = hist['Close'].pct_change().iloc[-60:].std()
        return current_price, high_52w, low_52w, current_vol, avg_vol

    def simulate_trade(self, hist, entry_idx, entry_price, strategy="mr"):
        """Simulate trade outcome"""
        exit_price = None
        exit_reason = None

        if strategy == "mr":
            profit_target = self.profit_target
            stop_loss = self.stop_loss_mr
            max_hours = self.time_exit_hours_mr
        else:  # breakout
            profit_target = 0.15  # +15% for breakout
            stop_loss = self.stop_loss_bo
            max_hours = self.time_exit_days_bo * 24  # Convert to hours

        entry_time = hist.index[entry_idx]

        for i in range(entry_idx + 1, len(hist)):
            current_price = hist['Close'].iloc[i]
            current_time = hist.index[i]
            hours_held = (current_time - entry_time).total_seconds() / 3600

            pnl_pct = (current_price - entry_price) / entry_price

            if pnl_pct >= profit_target:
                exit_price = current_price
                exit_reason = "PROFIT_TARGET"
                break
            elif pnl_pct <= stop_loss:
                exit_price = current_price
                exit_reason = "STOP_LOSS"
                break
            elif hours_held >= max_hours:
                exit_price = current_price
                exit_reason = "TIME_EXIT"
                break

        if exit_price is None:
            exit_price = hist['Close'].iloc[-1]
            exit_reason = "END_OF_DATA"

        pnl_pct = (exit_price - entry_price) / entry_price
        return pnl_pct, exit_reason

    def backtest_symbol(self, symbol):
        """Backtest all three strategies on one symbol"""
        try:
            hist = yf.Ticker(symbol).history(period="6m")
            if len(hist) < 100:
                return None

            trades_mr = []  # Mean-reversion only
            trades_bo = []  # Breakout only
            trades_rs = []  # Regime-switching

            for i in range(60, len(hist) - 1):
                # Get signals
                is_mr, rsi = self.get_mean_reversion_signal(hist.iloc[:i+1])
                is_bo, _ = self.get_breakout_signal(hist.iloc[:i+1])

                if not (is_mr or is_bo):
                    continue

                # Get regime
                curr_price, h52w, l52w, curr_vol, avg_vol = self.get_regime_data(hist.iloc[:i+1])
                regime, confidence = self.router.regime_filter.detect_regime(
                    curr_price, h52w, l52w, curr_vol, avg_vol
                )

                entry_price = hist['Close'].iloc[i]

                # Strategy 1: Pure Mean-Reversion (execute all MR signals)
                if is_mr:
                    pnl, reason = self.simulate_trade(hist, i, entry_price, "mr")
                    trades_mr.append({
                        'symbol': symbol,
                        'pnl_pct': pnl,
                        'exit_reason': reason,
                        'win': 1 if pnl > 0 else 0,
                        'regime': regime,
                        'rsi': rsi
                    })

                # Strategy 2: Pure Breakout (execute all BO signals)
                if is_bo:
                    pnl, reason = self.simulate_trade(hist, i, entry_price, "bo")
                    trades_bo.append({
                        'symbol': symbol,
                        'pnl_pct': pnl,
                        'exit_reason': reason,
                        'win': 1 if pnl > 0 else 0,
                        'regime': regime
                    })

                # Strategy 3: Regime-Switching
                should_exec_mr, _, _ = self.router.should_execute_trade(
                    "MEAN_REVERSION", curr_price, h52w, l52w, curr_vol, avg_vol
                )
                should_exec_bo, _, _ = self.router.should_execute_trade(
                    "BREAKOUT", curr_price, h52w, l52w, curr_vol, avg_vol
                )

                if is_mr and should_exec_mr:
                    pnl, reason = self.simulate_trade(hist, i, entry_price, "mr")
                    trades_rs.append({
                        'symbol': symbol,
                        'pnl_pct': pnl,
                        'exit_reason': reason,
                        'win': 1 if pnl > 0 else 0,
                        'regime': regime,
                        'strategy': 'MR'
                    })
                elif is_bo and should_exec_bo:
                    pnl, reason = self.simulate_trade(hist, i, entry_price, "bo")
                    trades_rs.append({
                        'symbol': symbol,
                        'pnl_pct': pnl,
                        'exit_reason': reason,
                        'win': 1 if pnl > 0 else 0,
                        'regime': regime,
                        'strategy': 'BO'
                    })

            return {
                'pure_mr': trades_mr,
                'pure_bo': trades_bo,
                'regime_switching': trades_rs
            }

        except:
            return None

    def calculate_stats(self, trades):
        """Calculate performance metrics"""
        if not trades:
            return None

        wins = sum(1 for t in trades if t['win'] == 1)
        losses = len(trades) - wins
        win_rate = (wins / len(trades) * 100) if trades else 0
        total_pnl = sum(t['pnl_pct'] for t in trades) * 100

        return {
            'total_trades': len(trades),
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_trade': (total_pnl / len(trades)) if trades else 0
        }


if __name__ == "__main__":
    backtest = RegimeSwitchingBacktest()

    symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "AMZN"]

    print("=" * 120)
    print("BACKTEST: PURE MEAN-REVERSION vs PURE BREAKOUT vs REGIME-SWITCHING")
    print("=" * 120)
    print()

    all_results = {
        'pure_mr': [],
        'pure_bo': [],
        'regime_switching': []
    }

    for symbol in symbols:
        print(f"Testing {symbol}...", end=" ", flush=True)
        result = backtest.backtest_symbol(symbol)

        if result:
            all_results['pure_mr'].extend(result['pure_mr'])
            all_results['pure_bo'].extend(result['pure_bo'])
            all_results['regime_switching'].extend(result['regime_switching'])
            print("✅")
        else:
            print("❌")

    # Calculate aggregate stats
    stats_mr = backtest.calculate_stats(all_results['pure_mr'])
    stats_bo = backtest.calculate_stats(all_results['pure_bo'])
    stats_rs = backtest.calculate_stats(all_results['regime_switching'])

    print("\n" + "=" * 120)
    print("RESULTS COMPARISON")
    print("=" * 120)

    if stats_mr:
        print(f"\n📊 PURE MEAN-REVERSION:")
        print(f"  Trades: {stats_mr['total_trades']:3d}  |  Win Rate: {stats_mr['win_rate']:5.1f}%  |  Total P&L: {stats_mr['total_pnl']:+7.0f} bps  |  Avg: {stats_mr['avg_trade']:+5.2f}%")

    if stats_bo:
        print(f"\n📊 PURE BREAKOUT (VCP):")
        print(f"  Trades: {stats_bo['total_trades']:3d}  |  Win Rate: {stats_bo['win_rate']:5.1f}%  |  Total P&L: {stats_bo['total_pnl']:+7.0f} bps  |  Avg: {stats_bo['avg_trade']:+5.2f}%")

    if stats_rs:
        print(f"\n📊 REGIME-SWITCHING (MR + BO):")
        print(f"  Trades: {stats_rs['total_trades']:3d}  |  Win Rate: {stats_rs['win_rate']:5.1f}%  |  Total P&L: {stats_rs['total_pnl']:+7.0f} bps  |  Avg: {stats_rs['avg_trade']:+5.2f}%")

    # Comparison
    if stats_mr and stats_rs:
        print("\n" + "=" * 120)
        print("🚀 REGIME-SWITCHING vs PURE MEAN-REVERSION:")
        print("=" * 120)
        wr_delta = stats_rs['win_rate'] - stats_mr['win_rate']
        pnl_delta = stats_rs['total_pnl'] - stats_mr['total_pnl']
        print(f"  Win Rate Improvement: {wr_delta:+.1f}% (from {stats_mr['win_rate']:.1f}% → {stats_rs['win_rate']:.1f}%)")
        print(f"  Profit Improvement: {pnl_delta:+.0f} bps")
        print(f"  Trade Efficiency: {(stats_rs['avg_trade'] - stats_mr['avg_trade']):+.2f}% per trade")

    # Save results
    results = {
        'timestamp': str(datetime.now()),
        'pure_mr': stats_mr,
        'pure_bo': stats_bo,
        'regime_switching': stats_rs
    }

    with open('backtest_regime_switching.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("\n✅ Results saved to: backtest_regime_switching.json")
