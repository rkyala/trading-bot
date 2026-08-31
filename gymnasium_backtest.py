#!/usr/bin/env python3
"""
Gymnasium Backtest Framework
Backtests trained RL models vs. buy-and-hold and rules-based strategies
"""

import os
import sys
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import logging
from pathlib import Path
import json

from stable_baselines3 import PPO, SAC

from gymnasium_trading_env import TradingEnv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)


class TradingBacktester:
    """Backtest RL and rules-based strategies"""

    def __init__(
        self,
        symbols: list = None,
        lookback_years: int = 2,
        test_start_date: str = None,
        test_end_date: str = None,
        initial_cash: float = 100000,
        model_dir: str = "./gymnasium_models"
    ):
        """
        Initialize backtest

        Args:
            symbols: Symbols to backtest
            lookback_years: Historical data to use for training/features
            test_start_date: Backtest start date (format: YYYY-MM-DD)
            test_end_date: Backtest end date
            initial_cash: Starting capital
            model_dir: Directory with trained models
        """
        self.symbols = symbols or ["AAPL", "NVDA", "TSLA", "MSFT", "SPY"]
        self.lookback_years = lookback_years
        self.initial_cash = initial_cash
        self.model_dir = Path(model_dir)

        # Default dates
        if test_end_date is None:
            test_end_date = datetime.now().strftime("%Y-%m-%d")
        if test_start_date is None:
            test_start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        self.test_start_date = test_start_date
        self.test_end_date = test_end_date
        self.data = {}

    def download_data(self, symbol: str) -> pd.DataFrame:
        """Download data for symbol"""
        log.info(f"📥 Downloading {symbol}...")

        end_date = datetime.strptime(self.test_end_date, "%Y-%m-%d")
        # Get extra data for lookback window
        lookback_start = end_date - timedelta(days=365 * self.lookback_years + 365)
        start_date = max(
            datetime.strptime(self.test_start_date, "%Y-%m-%d"),
            lookback_start
        )

        df = yf.download(
            symbol,
            start=start_date,
            end=end_date,
            progress=False
        )

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if isinstance(df, pd.Series):
            df = pd.DataFrame(df)

        df.columns = [col.lower() for col in df.columns]
        if 'adj close' in df.columns:
            df['close'] = df['adj close']
        df = df.drop('adj close', axis=1, errors='ignore')

        df = df.dropna()
        log.info(f"✅ {symbol}: {len(df)} days")
        return df

    def prepare_data(self):
        """Download data for all symbols"""
        log.info("\n" + "="*100)
        log.info("BACKTEST DATA PREPARATION")
        log.info("="*100)

        for symbol in self.symbols:
            self.data[symbol] = self.download_data(symbol)

    def backtest_rl_model(self, symbol: str, model_type: str = "ppo") -> Dict:
        """Backtest trained RL model on symbol"""
        log.info(f"\n📊 Backtesting {model_type.upper()} on {symbol}...")

        df = self.data[symbol].copy()

        # Load model
        model_path = self.model_dir / f"gymnasium_{model_type}"
        if not model_path.exists():
            log.warning(f"⚠️ Model not found: {model_path}")
            return None

        if model_type == "ppo":
            model = PPO.load(str(model_path))
        else:
            model = SAC.load(str(model_path))

        # Create environment
        env = TradingEnv(
            df=df,
            initial_cash=self.initial_cash,
            max_position_pct=0.05,
            lookback_window=252,
            episode_length=len(df) - 252 - 1
        )

        # Run backtest
        obs, _ = env.reset()
        done = False
        episode_reward = 0
        actions_taken = []
        prices = []
        portfolio_values = []

        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, done, truncated, info = env.step(action)
            episode_reward += reward
            actions_taken.append(int(action))
            prices.append(df.iloc[env.current_step]['Close'])
            portfolio_values.append(env.portfolio_value)
            done = done or truncated

        # Get stats
        stats = env.get_backtest_results()
        stats['model'] = model_type.upper()
        stats['symbol'] = symbol
        stats['episode_reward'] = episode_reward

        return stats

    def backtest_buy_and_hold(self, symbol: str) -> Dict:
        """Backtest simple buy-and-hold strategy"""
        log.info(f"\n📊 Backtesting BUY-AND-HOLD on {symbol}...")

        df = self.data[symbol].copy()

        # Calculate returns
        start_price = df.iloc[0]['Close']
        end_price = df.iloc[-1]['Close']
        total_return = (end_price - start_price) / start_price

        # Calculate Sharpe
        df['returns'] = df['Close'].pct_change()
        returns = df['returns'].dropna()
        sharpe = (returns.mean() / (returns.std() + 1e-9)) * np.sqrt(252)

        # Calculate max drawdown
        cumulative = (1 + returns).cumprod()
        max_dd = (cumulative.min() - 1)

        win_rate = (returns > 0).sum() / len(returns) * 100

        return {
            'model': 'BUY-HOLD',
            'symbol': symbol,
            'final_return': total_return * 100,
            'sharpe': sharpe,
            'max_drawdown': max_dd * 100,
            'win_rate': win_rate,
            'total_trades': 1
        }

    def backtest_rules_based(self, symbol: str) -> Dict:
        """Backtest rules-based mean-reversion strategy"""
        log.info(f"\n📊 Backtesting RULES-BASED on {symbol}...")

        df = self.data[symbol].copy()

        # Calculate indicators
        df['RSI'] = self._calculate_rsi(df['Close'], 14)
        df['BB_Mid'] = df['Close'].rolling(20).mean()
        df['BB_Std'] = df['Close'].rolling(20).std()
        df['BB_Lower'] = df['BB_Mid'] - (df['BB_Std'] * 2)

        # Trading logic
        positions = np.zeros(len(df))
        pos_state = 0
        entry_price = 0

        for i in range(50, len(df)):
            if pos_state == 0:
                # Entry: RSI < 20 (oversold) and price near BB lower band
                if df['RSI'].iloc[i] < 20 and df['Close'].iloc[i] < df['BB_Lower'].iloc[i]:
                    pos_state = 1
                    entry_price = df['Close'].iloc[i]

            elif pos_state > 0:
                # Exit: RSI > 70 (overbought) or -2% stop loss
                if df['RSI'].iloc[i] > 70 or df['Close'].iloc[i] < entry_price * 0.98:
                    pos_state = 0

            positions[i] = 0.5 if pos_state > 0 else 0

        # Calculate returns
        df['Strategy_Returns'] = df['Close'].pct_change() * pd.Series(positions).shift(1)
        returns = df['Strategy_Returns'].dropna()

        if len(returns) == 0:
            log.warning(f"No trades executed for {symbol}")
            return None

        final_return = (1 + returns).prod() - 1
        sharpe = (returns.mean() / (returns.std() + 1e-9)) * np.sqrt(252)

        cumulative = (1 + returns).cumprod()
        max_dd = (cumulative.min() - 1) / cumulative.max()

        win_rate = (returns > 0).sum() / len(returns) * 100
        trades = (np.diff(positions) != 0).sum()

        return {
            'model': 'RULES-BASED',
            'symbol': symbol,
            'final_return': final_return * 100,
            'sharpe': sharpe,
            'max_drawdown': max_dd * 100,
            'win_rate': win_rate,
            'total_trades': trades
        }

    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-9)
        return 100 - (100 / (1 + rs))

    def run_full_backtest(self, models: list = None) -> pd.DataFrame:
        """Run comprehensive backtest across all symbols and models"""
        if models is None:
            models = ["ppo", "buy-hold", "rules-based"]

        log.info("\n" + "="*100)
        log.info("RUNNING COMPREHENSIVE BACKTEST")
        log.info("="*100)

        all_results = []

        for symbol in self.symbols:
            log.info(f"\n{'='*100}")
            log.info(f"Symbol: {symbol}")
            log.info(f"{'='*100}")

            # PPO model
            if "ppo" in models:
                result = self.backtest_rl_model(symbol, "ppo")
                if result:
                    all_results.append(result)

            # SAC model
            if "sac" in models:
                result = self.backtest_rl_model(symbol, "sac")
                if result:
                    all_results.append(result)

            # Buy and hold
            if "buy-hold" in models:
                result = self.backtest_buy_and_hold(symbol)
                all_results.append(result)

            # Rules-based
            if "rules-based" in models:
                result = self.backtest_rules_based(symbol)
                if result:
                    all_results.append(result)

        # Create summary DataFrame
        results_df = pd.DataFrame(all_results)

        # Print summary
        log.info("\n" + "="*100)
        log.info("BACKTEST RESULTS SUMMARY")
        log.info("="*100)

        for model in results_df['model'].unique():
            model_results = results_df[results_df['model'] == model]
            avg_return = model_results['final_return'].mean()
            avg_sharpe = model_results['sharpe'].mean()
            avg_dd = model_results['max_drawdown'].mean()
            avg_wr = model_results['win_rate'].mean()

            log.info(f"\n{model}")
            log.info(f"  Avg Return:     {avg_return:+.2f}%")
            log.info(f"  Avg Sharpe:     {avg_sharpe:.2f}")
            log.info(f"  Avg Max DD:     {avg_dd:.2f}%")
            log.info(f"  Avg Win Rate:   {avg_wr:.1f}%")

        # Per-symbol summary
        log.info("\n" + "="*100)
        log.info("PER-SYMBOL RESULTS")
        log.info("="*100)

        for symbol in self.symbols:
            symbol_results = results_df[results_df['symbol'] == symbol]
            log.info(f"\n{symbol}")
            for _, row in symbol_results.iterrows():
                log.info(f"  {row['model']:12} | "
                        f"Return: {row['final_return']:+7.2f}% | "
                        f"Sharpe: {row['sharpe']:6.2f} | "
                        f"DD: {row['max_drawdown']:7.2f}% | "
                        f"WR: {row['win_rate']:5.1f}%")

        return results_df

    def save_results(self, results_df: pd.DataFrame, output_file: str = "gymnasium_backtest_results.csv"):
        """Save results to CSV"""
        results_df.to_csv(output_file, index=False)
        log.info(f"\n✅ Results saved to {output_file}")


def main():
    """Main backtest pipeline"""
    import argparse

    parser = argparse.ArgumentParser(description="Backtest RL trading models")
    parser.add_argument("--symbols", nargs="+", default=["AAPL", "NVDA", "TSLA", "MSFT", "SPY"],
                        help="Symbols to backtest")
    parser.add_argument("--models", nargs="+", default=["ppo", "buy-hold", "rules-based"],
                        help="Models to test (ppo, sac, buy-hold, rules-based)")
    parser.add_argument("--start-date", type=str, default=None,
                        help="Backtest start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default=None,
                        help="Backtest end date (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, default="gymnasium_backtest_results.csv",
                        help="Output CSV file")

    args = parser.parse_args()

    # Initialize backtest
    backtest = TradingBacktester(
        symbols=args.symbols,
        test_start_date=args.start_date,
        test_end_date=args.end_date
    )

    # Prepare data
    backtest.prepare_data()

    # Run backtest
    results = backtest.run_full_backtest(models=args.models)

    # Save results
    backtest.save_results(results, args.output)


if __name__ == "__main__":
    main()
