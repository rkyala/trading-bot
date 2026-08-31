#!/usr/bin/env python3
"""
Gymnasium Environment Quick Start
Test the environment and run a quick training demo
"""

import sys
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import logging

from gymnasium_trading_env import TradingEnv
from stable_baselines3 import PPO

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def download_test_data(symbol: str = "AAPL", years: int = 2) -> pd.DataFrame:
    """Download test data"""
    log.info(f"📥 Downloading {symbol}...")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=365 * years)

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
    log.info(f"✅ Downloaded {len(df)} days of data")
    return df


def test_environment():
    """Test the Gymnasium environment"""
    log.info("\n" + "="*100)
    log.info("TESTING GYMNASIUM TRADING ENVIRONMENT")
    log.info("="*100)

    # Download data
    df = download_test_data("AAPL", years=2)

    # Create environment
    log.info("🏗️  Creating environment...")
    env = TradingEnv(
        df=df,
        initial_cash=100000,
        max_position_pct=0.05,
        lookback_window=252,
        episode_length=60
    )

    log.info(f"✅ Environment created")
    log.info(f"   Observation space: {env.observation_space}")
    log.info(f"   Action space: {env.action_space}")

    # Run one episode
    log.info("\n🎬 Running test episode...")
    obs, _ = env.reset()
    done = False
    step = 0
    total_reward = 0

    while not done:
        # Random action
        action = env.action_space.sample()
        obs, reward, done, truncated, info = env.step(action)
        total_reward += reward
        step += 1

        if step % 10 == 0 or done:
            log.info(f"   Step {step}: Action={action}, Reward={reward:.2f}, Portfolio=${env.portfolio_value:,.0f}")

        done = done or truncated

    # Get results
    stats = env.get_backtest_results()

    log.info("\n" + "="*100)
    log.info("EPISODE RESULTS")
    log.info("="*100)
    log.info(f"Total Steps:        {step}")
    log.info(f"Total Reward:       {total_reward:.2f}")
    log.info(f"Final Return:       {stats['final_return']:+.2f}%")
    log.info(f"Sharpe Ratio:       {stats['sharpe']:.2f}")
    log.info(f"Max Drawdown:       {stats['max_drawdown']:.2f}%")
    log.info(f"Win Rate:           {stats['win_rate']:.1f}%")
    log.info(f"Trades Made:        {stats['total_trades']}")
    log.info(f"Final Portfolio:    ${stats['final_portfolio_value']:,.0f}")

    return env


def quick_train_demo():
    """Quick training demo (5 minutes)"""
    log.info("\n" + "="*100)
    log.info("QUICK TRAINING DEMO (100K timesteps)")
    log.info("="*100)

    # Download data
    df = download_test_data("AAPL", years=2)

    # Create environment
    env = TradingEnv(
        df=df,
        initial_cash=100000,
        max_position_pct=0.05,
        lookback_window=252,
        episode_length=60
    )

    # Train PPO
    log.info("\n🚀 Training PPO agent...")
    model = PPO(
        "MlpPolicy",
        env,
        verbose=1,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=64,
        gamma=0.99
    )

    model.learn(total_timesteps=10000, progress_bar=True)

    log.info("✅ Training complete")

    # Test trained model
    log.info("\n🧪 Testing trained model...")
    obs, _ = env.reset()
    done = False
    episode_reward = 0

    while not done:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, done, truncated, info = env.step(action)
        episode_reward += reward
        done = done or truncated

    stats = env.get_backtest_results()

    log.info(f"Episode Reward:     {episode_reward:.2f}")
    log.info(f"Final Return:       {stats['final_return']:+.2f}%")
    log.info(f"Sharpe Ratio:       {stats['sharpe']:.2f}")
    log.info(f"Win Rate:           {stats['win_rate']:.1f}%")

    # Save model
    model.save("gymnasium_quickstart_demo")
    log.info("✅ Model saved to gymnasium_quickstart_demo.zip")


def main():
    """Run quickstart"""
    import argparse

    parser = argparse.ArgumentParser(description="Gymnasium quickstart")
    parser.add_argument("--test", action="store_true", help="Test environment only")
    parser.add_argument("--train", action="store_true", help="Run quick training demo")
    parser.add_argument("--both", action="store_true", help="Test and train")

    args = parser.parse_args()

    if not args.train and not args.test and not args.both:
        args.both = True

    if args.test or args.both:
        try:
            test_environment()
        except Exception as e:
            log.error(f"❌ Test failed: {e}", exc_info=True)
            return 1

    if args.train or args.both:
        try:
            quick_train_demo()
        except Exception as e:
            log.error(f"❌ Training failed: {e}", exc_info=True)
            return 1

    log.info("\n✅ Quickstart complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
