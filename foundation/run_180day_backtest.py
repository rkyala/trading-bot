"""
180-Day Foundation Backtest Executor
Runs complete backtest with all 6 components integrated

Day 3: Gate 1 validation (win rate >= 55%, PF > 1.5)
"""

import pandas as pd
import numpy as np
from datetime import datetime
import logging
import os
import sys

# Import all Foundation components
from backtest_framework import BacktestEngine
from foundation_engine import FoundationEngine
from macro_trigger_scanner import MacroTriggerScanner
from volatility_filter import VolatilityFilter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BacktestExecutor:
    """
    Executes complete 180-day backtest on Foundation strategy
    """

    def __init__(self, data_dir: str = 'backtest_data', initial_capital: float = 10000):
        self.data_dir = data_dir
        self.initial_capital = initial_capital
        self.engine = FoundationEngine(initial_capital=initial_capital)
        self.all_data = {}
        self.cycle_number = 0

    def load_backtest_data(self) -> bool:
        """Load 30-min backtest data for all symbols"""
        symbols = ['CRWD', 'ZM', 'JD']

        for symbol in symbols:
            try:
                # Load 30-min data
                file_path = os.path.join(self.data_dir, f"{symbol}_30min.csv")
                if not os.path.exists(file_path):
                    logger.error(f"Data file not found: {file_path}")
                    return False

                df = pd.read_csv(file_path)
                df['DateTime'] = pd.to_datetime(df['DateTime'])
                self.all_data[symbol] = df

                logger.info(f"✅ Loaded {symbol}: {len(df)} candles")

            except Exception as e:
                logger.error(f"Error loading {symbol} data: {e}")
                return False

        return True

    def get_technical_indicators(self, symbol: str, row_idx: int) -> dict:
        """
        Calculate technical indicators for current candle

        Simplified calculation for backtest
        """
        df = self.all_data[symbol]

        if row_idx < 50:
            # Not enough data for full calculation
            return {
                'price': df.iloc[row_idx]['Close'],
                'ema_20': df.iloc[row_idx]['Close'],
                'ema_50': df.iloc[row_idx]['Close'],
                'adx': 20,
                'stoch_k': 50
            }

        # Get window
        window = df.iloc[max(0, row_idx - 50):row_idx + 1]

        # EMA 20 (simplified)
        ema_20 = window['Close'].ewm(span=20).mean().iloc[-1]
        ema_50 = window['Close'].ewm(span=50).mean().iloc[-1]

        # ADX (simplified - use trend)
        closes = window['Close'].values
        uptrend_days = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
        adx = (uptrend_days / len(closes)) * 50  # Scale to 0-50

        # Stoch K (simplified)
        low = window['Low'].min()
        high = window['High'].max()
        current = df.iloc[row_idx]['Close']
        stoch_k = ((current - low) / (high - low)) * 100 if high > low else 50

        return {
            'price': df.iloc[row_idx]['Close'],
            'ema_20': ema_20,
            'ema_50': ema_50,
            'adx': adx,
            'stoch_k': stoch_k
        }

    def get_vwap_bands(self, symbol: str, start_idx: int, end_idx: int) -> dict:
        """Get VWAP bands for a session (simplified for backtest)"""
        from vwap_calculator import SessionAnchoredVWAP

        df = self.all_data[symbol]
        window = df.iloc[start_idx:end_idx]

        vwap_calc = SessionAnchoredVWAP()
        vwap_bands = vwap_calc.calculate_vwap_bands(
            window['High'].values,
            window['Low'].values,
            window['Close'].values,
            window['Volume'].values
        )

        return vwap_bands

    def get_orb_range(self, symbol: str, row_idx: int) -> dict:
        """
        Get ORB range for current session

        Simplified: use first 5 candles of day as opening range
        """
        from orb_detector import OpeningRangeBreakout

        df = self.all_data[symbol]
        # Get start of day (simplified - just last 5 candles)
        day_start = max(0, row_idx - 5)
        window = df.iloc[day_start:row_idx + 1]

        detector = OpeningRangeBreakout()
        orb_range = detector.calculate_orb_range(window[['Open', 'High', 'Low', 'Close', 'Volume']])

        return orb_range

    def get_atr_pct(self, symbol: str, row_idx: int) -> float:
        """Calculate ATR % for symbol"""
        from volatility_filter import VolatilityFilter

        df = self.all_data[symbol]
        if row_idx < 14:
            return 2.0  # Default

        window = df.iloc[max(0, row_idx - 13):row_idx + 1]

        vf = VolatilityFilter()
        atr_pct = vf.calculate_atr_pct(
            window['High'].values,
            window['Low'].values,
            window['Close'].values
        )

        return atr_pct

    def run_backtest(self) -> bool:
        """Execute 180-day backtest"""
        logger.info("\n" + "="*70)
        logger.info("STARTING 180-DAY FOUNDATION BACKTEST")
        logger.info("="*70 + "\n")

        # Get min length
        min_rows = min(len(self.all_data[s]) for s in self.all_data.keys())
        logger.info(f"Backtesting {min_rows} candles per symbol\n")

        # Simulate daily cycles (every 13 candles = 1 trading day)
        for day_num in range(0, min_rows, 13):  # 13 candles per day
            self.cycle_number = day_num // 13

            # Check each symbol
            tradeable_symbols = ['ZM', 'JD']  # Filter out CRWD (high vol)

            for symbol in tradeable_symbols:
                if day_num >= len(self.all_data[symbol]):
                    continue

                row_idx = day_num

                # Check position exit first
                if symbol in self.engine.backtest_engine.positions:
                    current_price = self.all_data[symbol].iloc[row_idx]['Close']
                    exit_reason = self.engine.backtest_engine.check_position_exit(
                        symbol,
                        current_price,
                        self.all_data[symbol].iloc[row_idx]['DateTime']
                    )

                    if exit_reason:
                        self.engine.backtest_engine.exit_trade(
                            symbol,
                            current_price,
                            self.all_data[symbol].iloc[row_idx]['DateTime'],
                            exit_reason
                        )

                # Skip if already have position
                if symbol in self.engine.backtest_engine.positions:
                    continue

                # Get technical indicators
                current_data = self.get_technical_indicators(symbol, row_idx)

                # Get VWAP bands
                vwap_start = max(0, row_idx - 50)
                vwap_bands = self.get_vwap_bands(symbol, vwap_start, row_idx + 1)

                # Get ORB range
                orb_range = self.get_orb_range(symbol, row_idx)

                # Get ATR %
                atr_pct = self.get_atr_pct(symbol, row_idx)

                # Generate signal
                signal = self.engine.generate_entry_signal(
                    symbol=symbol,
                    current_data=current_data,
                    symbol_candles={},
                    vwap_bands=vwap_bands,
                    orb_range=orb_range,
                    atr_pct=atr_pct
                )

                if signal:
                    # Execute entry
                    self.engine.execute_entry(signal)

            # Increment cycle counters
            self.engine.backtest_engine.increment_cycle_count()

            # Print progress every 20 cycles
            if self.cycle_number % 20 == 0:
                metrics = self.engine.backtest_engine.calculate_metrics()
                logger.info(
                    f"Cycle {self.cycle_number}: "
                    f"Trades={metrics['total_trades']}, "
                    f"Win%={metrics['win_rate']:.1f}, "
                    f"PF={metrics['profit_factor']:.2f}, "
                    f"Balance=${self.engine.backtest_engine.current_balance:,.2f}"
                )

        # Final results
        self.print_backtest_results()
        return True

    def print_backtest_results(self):
        """Print comprehensive backtest results"""
        metrics = self.engine.backtest_engine.calculate_metrics()

        print("\n" + "="*70)
        print("180-DAY BACKTEST RESULTS (GATE 1 VALIDATION)")
        print("="*70)
        print(f"\nInitial Capital:     ${self.initial_capital:,.2f}")
        print(f"Final Balance:       ${self.engine.backtest_engine.current_balance:,.2f}")
        print(f"Total P&L:           ${metrics['total_pnl']:,.2f}")
        print(f"Total Return:        {(metrics['total_pnl']/self.initial_capital)*100:.2f}%")

        print(f"\nTrade Statistics:")
        print(f"  Total Trades:      {metrics['total_trades']}")
        print(f"  Winners:           {metrics['win_count']} ({metrics['win_rate']:.1f}%)")
        print(f"  Losers:            {metrics['loss_count']}")
        print(f"  Avg Win:           ${metrics['avg_win']:.2f}")
        print(f"  Avg Loss:          ${metrics['avg_loss']:.2f}")
        print(f"  Profit Factor:     {metrics['profit_factor']:.2f}")
        print(f"  Max Drawdown:      {metrics['max_drawdown']:.2f}%")
        print(f"  Sharpe Ratio:      {metrics['sharpe_ratio']:.2f}")

        # Gate 1 Validation
        print(f"\n" + "="*70)
        print(f"GATE 1 VALIDATION (Success Criteria)")
        print(f"="*70)

        gate1_checks = {
            'Win Rate >= 55%': {
                'value': metrics['win_rate'],
                'threshold': 55,
                'passed': metrics['win_rate'] >= 55
            },
            'Profit Factor > 1.5': {
                'value': metrics['profit_factor'],
                'threshold': 1.5,
                'passed': metrics['profit_factor'] > 1.5
            },
            'Total Trades >= 40': {
                'value': metrics['total_trades'],
                'threshold': 40,
                'passed': metrics['total_trades'] >= 40
            }
        }

        all_passed = True
        for check_name, check_data in gate1_checks.items():
            status = "✅ PASS" if check_data['passed'] else "❌ FAIL"
            print(f"{check_name:25} {check_data['value']:8.1f} (>= {check_data['threshold']:5.1f}) {status}")
            if not check_data['passed']:
                all_passed = False

        print(f"\n{'='*70}")
        if all_passed:
            print(f"✅✅✅ GATE 1 PASSED - Foundation strategy validated! ✅✅✅")
        else:
            print(f"❌ Gate 1 NOT PASSED - Adjustments needed")
        print(f"{'='*70}\n")

        return all_passed

    def save_trades_csv(self):
        """Save trade log to CSV"""
        self.engine.backtest_engine.export_trades_csv('backtest_results.csv')


# Run backtest
if __name__ == "__main__":
    executor = BacktestExecutor(initial_capital=10000)

    # Load data
    if not executor.load_backtest_data():
        logger.error("Failed to load backtest data")
        sys.exit(1)

    # Run backtest
    if executor.run_backtest():
        executor.save_trades_csv()
        logger.info("✅ Backtest complete!")
    else:
        logger.error("Backtest failed")
        sys.exit(1)
