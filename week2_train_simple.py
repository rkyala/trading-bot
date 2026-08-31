#!/usr/bin/env python3
"""
Week 2 Training - Simple PPO Only
Uses Schwab market data fetched via schwab_signal_fetcher
"""

import sys
sys.path.insert(0, '/Users/ramayalala/Documents/Documents - Rama\'s MacBook Pro/trading_bot')

import logging
import pandas as pd
from schwab_marketdata_fetcher import SchwabMarketDataFetcher
from gymnasium_trading_env import TradingEnv
from stable_baselines3 import PPO

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# Step 1: Fetch Schwab data
log.info("=" * 80)
log.info("FETCHING SCHWAB MARKET DATA FOR WEEK 2")
log.info("=" * 80)

fetcher = SchwabMarketDataFetcher()
symbols = ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA"]
data_dict = {}

for symbol in symbols:
    df = fetcher.get_price_history_df(symbol, frequency='thirty_min')
    if df is not None and len(df) > 100:
        data_dict[symbol] = df
        log.info(f"✅ {symbol}: {len(df)} candles")

# Step 2: Combine data
log.info("\nCombining data for training...")
combined = pd.concat([df for df in data_dict.values()])
combined = combined.sort_index().dropna()
log.info(f"✅ Total: {len(combined)} rows from {len(data_dict)} symbols")

# Step 3: Create environment
log.info("\nCreating Gymnasium environment...")
env = TradingEnv(
    df=combined,
    initial_cash=10000,
    max_position_pct=0.05,
    lookback_window=50,  # Reduced for less data
    episode_length=40
)

# Step 4: Train PPO
log.info("\n" + "=" * 80)
log.info("TRAINING PPO MODEL")
log.info("=" * 80)

model = PPO(
    "MlpPolicy",
    env,
    verbose=1,
    learning_rate=3e-4,
    n_steps=512,
    batch_size=32,
    n_epochs=10,
    gamma=0.99
)

log.info("🚀 Starting PPO training (50K timesteps)...")
model.learn(total_timesteps=50000, progress_bar=True)

# Step 5: Save model
model_path = "gymnasium_models/gymnasium_ppo_week2_schwab"
model.save(model_path)
log.info(f"\n✅ Model saved: {model_path}.zip")

log.info("\n" + "=" * 80)
log.info("WEEK 2 TRAINING COMPLETE")
log.info("=" * 80)
log.info("Next: Run backtest_hybrid_strategy_complete.py to compare against baseline")
