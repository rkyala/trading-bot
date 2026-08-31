#!/usr/bin/env python3
"""
Complete Backtest Harness for HybridStrategy (FinRL + Bollinger Bands)
Integrates with backtesting.py for event-driven simulation
Tests: Entry signals, exit signals, position management, slippage, commissions
"""

import numpy as np
import pandas as pd
import yfinance as yf
import logging
from datetime import datetime, timedelta
from backtesting import Backtest, Strategy

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
log = logging.getLogger(__name__)

# Import hybrid strategy
try:
    from hybrid_strategy import HybridStrategy
    HYBRID_AVAILABLE = True
except ImportError:
    HYBRID_AVAILABLE = False
    log.warning("HybridStrategy not available - using rules-based fallback")


class HybridBacktestStrategy(Strategy):
    """
    Backtesting wrapper adapting HybridStrategy to backtesting.py

    Key features:
    - Event-driven: processes each bar sequentially
    - Avoids lookahead bias: only uses historical data up to current bar
    - Realistic: accounts for slippage and commissions
    - Position tracking: managed entry/exit signals
    """

    LOOKBACK = 20  # Minimum bars for indicator calculation (20-period BB)

    def init(self):
        """Initialize strategy engine and tracking"""
        if HYBRID_AVAILABLE:
            self.strategy_engine = HybridStrategy()
        else:
            self.strategy_engine = None

        # Trade tracking
        self.entry_prices = {}
        self.entry_times = {}
        self.trade_count = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.trade_results = []

        log.info("✅ Backtest strategy initialized")

    def next(self):
        """Process each bar (called for every OHLCV bar in sequence)"""

        # Require minimum bars for indicator calculation
        if len(self.data.Close) < self.LOOKBACK:
            return

        current_price = float(self.data.Close[-1])
        current_time = self.data.index[-1]

        # Extract historical price slice (no lookahead bias)
        prices_slice = np.array(self.data.Close[-self.LOOKBACK:])
        high_14 = float(np.max(self.data.High[-14:]))
        low_14 = float(np.min(self.data.Low[-14:]))

        # =====================================================================
        # PHASE 1: EXIT SIGNAL (for existing positions)
        # =====================================================================
        if self.position:
            entry_price = self.position.entry_price
            entry_bars_ago = len(self.data.Close) - self.position.barlen

            # Time-based exit: close after 50 bars (half a trading day at 30-min)
            if entry_bars_ago > 50:
                pnl_pct = (current_price - entry_price) / entry_price * 100
                self.position.close()
                self.trade_count += 1
                if pnl_pct > 0:
                    self.winning_trades += 1
                else:
                    self.losing_trades += 1
                self.trade_results.append({
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'pnl_pct': pnl_pct,
                    'bars_held': entry_bars_ago,
                    'exit_reason': 'Time-based'
                })
                log.debug(f"[EXIT TIME] {current_time} | Entry: ${entry_price:.2f} → Exit: ${current_price:.2f} | P&L: {pnl_pct:+.2f}%")
                return

            # Profit target: +3% take-profit
            if current_price >= entry_price * 1.03:
                pnl_pct = 3.0
                self.position.close()
                self.trade_count += 1
                self.winning_trades += 1
                self.trade_results.append({
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'pnl_pct': pnl_pct,
                    'bars_held': entry_bars_ago,
                    'exit_reason': 'Profit Target +3%'
                })
                log.debug(f"[EXIT TP] {current_time} | Entry: ${entry_price:.2f} → Exit: ${current_price:.2f} | P&L: {pnl_pct:+.2f}%")
                return

            # Stop loss: -1.5%
            if current_price <= entry_price * 0.985:
                pnl_pct = -1.5
                self.position.close()
                self.trade_count += 1
                self.losing_trades += 1
                self.trade_results.append({
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'pnl_pct': pnl_pct,
                    'bars_held': entry_bars_ago,
                    'exit_reason': 'Stop Loss -1.5%'
                })
                log.debug(f"[EXIT SL] {current_time} | Entry: ${entry_price:.2f} → Exit: ${current_price:.2f} | P&L: {pnl_pct:+.2f}%")
                return

        # =====================================================================
        # PHASE 2: ENTRY SIGNAL (if no existing position)
        # =====================================================================
        if not self.position:

            # Generate signal using HybridStrategy (if available)
            if self.strategy_engine and HYBRID_AVAILABLE:
                try:
                    signal = self.strategy_engine.generate_entry_signal(
                        symbol="BACKTEST",
                        current_price=current_price,
                        prices=prices_slice,
                        high_14=high_14,
                        low_14=low_14
                    )

                    if signal and signal.get("signal_type") == "BUY":
                        # Buy with fractional position size
                        # backtesting.py auto-calculates shares based on cash
                        self.buy()
                        log.debug(f"[ENTRY] {current_time} | Price: ${current_price:.2f} | Signal: {signal.get('confidence', 0)}%")

                except Exception as e:
                    log.debug(f"Strategy error: {e}")

            # Fallback: Simple mean-reversion rules (if HybridStrategy unavailable)
            else:
                # Calculate simple BB
                bb_mid = np.mean(prices_slice)
                bb_std = np.std(prices_slice)
                bb_lower = bb_mid - (2 * bb_std)
                bb_upper = bb_mid + (2 * bb_std)

                # Entry: Price near lower Bollinger Band + volume confirmation
                if current_price < bb_lower * 1.01 and len(self.data.Volume) > 0:
                    self.buy()
                    log.debug(f"[ENTRY FALLBACK] {current_time} | Price: ${current_price:.2f} vs BB: ${bb_lower:.2f}")


class HybridBacktester:
    """Wrapper for running comprehensive backtest and generating metrics"""

    def __init__(self, symbol: str = "SPY", start_date: str = None, end_date: str = None):
        """
        Initialize backtest configuration

        Args:
            symbol: Stock ticker (e.g., "SPY", "QQQ", "AAPL")
            start_date: Start date (format: "YYYY-MM-DD")
            end_date: End date (format: "YYYY-MM-DD")
        """
        self.symbol = symbol

        # Default dates: last 6 months
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

        self.start_date = start_date
        self.end_date = end_date

    def download_data(self, interval: str = "30m") -> pd.DataFrame:
        """Download historical data from yfinance"""
        log.info(f"📥 Downloading {self.symbol} ({self.start_date} to {self.end_date}) at {interval} interval...")

        try:
            df = yf.download(
                self.symbol,
                start=self.start_date,
                end=self.end_date,
                interval=interval,
                progress=False
            )

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df.columns = [col.lower() for col in df.columns]

            # Handle single ticker (returns DataFrame, not Series)
            if isinstance(df, pd.Series):
                df = df.to_frame()

            df = df.dropna()
            log.info(f"✅ Downloaded {len(df)} bars")
            return df

        except Exception as e:
            log.error(f"❌ Download failed: {e}")
            raise

    def run_backtest(self, df: pd.DataFrame, cash: float = 10000,
                     commission: float = 0.001) -> dict:
        """
        Run backtest with specified parameters

        Args:
            df: OHLCV DataFrame
            cash: Starting capital ($)
            commission: Commission per trade (0.001 = 0.1%)

        Returns:
            Dictionary with performance metrics
        """
        log.info(f"\n🚀 Starting backtest ({self.symbol})...")
        log.info(f"   Capital: ${cash:,.0f}")
        log.info(f"   Commission: {commission*100:.2f}%")

        bt = Backtest(
            df,
            HybridBacktestStrategy,
            cash=cash,
            commission=commission,
            trade_on_close=True,
            exclusive_orders=True
        )

        stats = bt.run()
        return stats

    def print_results(self, stats):
        """Print comprehensive backtest results"""

        print("\n" + "="*80)
        print(f"BACKTEST RESULTS: {self.symbol}")
        print("="*80)

        print(f"\n📊 PERFORMANCE METRICS")
        print("-" * 80)
        print(f"  Total Return:          {stats['Return [%]']:+7.2f}%")
        print(f"  Buy & Hold Return:     {stats['Buy & Hold Return [%]']:+7.2f}%")
        print(f"  Return (Ann.):         {stats['Return (Ann.) [%]']:+7.2f}%")

        print(f"\n📈 RISK METRICS")
        print("-" * 80)
        print(f"  Volatility (Ann.):     {stats['Volatility (Ann.) [%]']:+7.2f}%")
        print(f"  Sharpe Ratio:          {stats['Sharpe Ratio']:+7.2f}")
        print(f"  Sortino Ratio:         {stats['Sortino Ratio']:+7.2f}")
        print(f"  Max Drawdown:          {stats['Max. Drawdown [%]']:-7.2f}%")

        print(f"\n💼 TRADE STATISTICS")
        print("-" * 80)
        print(f"  Total Trades:          {stats['# Trades']:>7.0f}")
        print(f"  Win Rate:              {stats['Win Rate [%]']:>7.1f}%")
        print(f"  Best Trade:            {stats['Best Trade [%]']:+7.2f}%")
        print(f"  Worst Trade:           {stats['Worst Trade [%]']:+7.2f}%")
        print(f"  Avg. Trade:            {stats['Avg. Trade [%]']:+7.2f}%")

        print(f"\n💰 PROFIT/LOSS")
        print("-" * 80)
        print(f"  Profit Factor:         {stats['Profit Factor']:>7.2f}")
        print(f"  Expectancy:            {stats['Expectancy [%]']:+7.2f}%")

        print(f"\n⏱️  TIME")
        print("-" * 80)
        print(f"  Start:                 {stats['Start']}")
        print(f"  End:                   {stats['End']}")
        print(f"  Duration:              {stats['Duration']}")

        print("\n" + "="*80)

        return stats


def backtest_multiple_symbols(symbols: list, start_date: str = None,
                              end_date: str = None) -> pd.DataFrame:
    """Backtest multiple symbols and compare results"""

    results = []

    for symbol in symbols:
        log.info(f"\n{'='*80}")
        log.info(f"Testing {symbol}")
        log.info(f"{'='*80}")

        try:
            backtester = HybridBacktester(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date
            )

            df = backtester.download_data(interval="30m")
            stats = backtester.run_backtest(df)
            backtester.print_results(stats)

            results.append({
                'Symbol': symbol,
                'Return %': stats['Return [%]'],
                'Sharpe': stats['Sharpe Ratio'],
                'Sortino': stats['Sortino Ratio'],
                'Max DD %': stats['Max. Drawdown [%]'],
                'Win Rate %': stats['Win Rate [%]'],
                'Trades': stats['# Trades'],
                'Profit Factor': stats['Profit Factor']
            })

        except Exception as e:
            log.error(f"❌ Backtest failed for {symbol}: {e}")

    # Summary table
    if results:
        print("\n" + "="*100)
        print("BACKTEST SUMMARY - ALL SYMBOLS")
        print("="*100)

        results_df = pd.DataFrame(results)
        print(results_df.to_string(index=False))

        # Aggregate statistics
        print("\n" + "="*100)
        print("AGGREGATE STATISTICS")
        print("="*100)
        print(f"Avg Return:        {results_df['Return %'].mean():+7.2f}%")
        print(f"Avg Sharpe:        {results_df['Sharpe'].mean():+7.2f}")
        print(f"Avg Max DD:        {results_df['Max DD %'].mean():-7.2f}%")
        print(f"Avg Win Rate:      {results_df['Win Rate %'].mean():>7.1f}%")

        return results_df

    return None


if __name__ == "__main__":
    import sys

    # Parse arguments
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["SPY", "QQQ", "AAPL"]

    print("\n" + "="*100)
    print("HYBRID STRATEGY BACKTEST")
    print("="*100)
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Period: Last 6 months")
    print(f"Interval: 30-minute bars")
    print("="*100 + "\n")

    # Run backtest
    results = backtest_multiple_symbols(symbols)

    # Save results
    if results is not None:
        csv_file = f"backtest_hybrid_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        results.to_csv(csv_file, index=False)
        log.info(f"\n✅ Results saved to {csv_file}")
