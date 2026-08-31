#!/usr/bin/env python3
"""
Week 2 Training Script - Uses Schwab Market Data
Trains PPO/SAC models on real market data from signal fetcher
"""

import sys
import os
import logging
from datetime import datetime
import pandas as pd
import numpy as np

# Add path for gymnasium modules
sys.path.insert(0, '/Users/ramayalala/Documents/Documents - Rama\'s MacBook Pro/trading_bot')

from schwab_marketdata_fetcher import SchwabMarketDataFetcher

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)


class Week2Trainer:
    """Train RL models using Schwab market data"""

    SYMBOLS = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
        "TSLA", "META", "NFLX", "ADBE", "PYPL"
    ]

    def __init__(self):
        self.fetcher = SchwabMarketDataFetcher()
        self.data = {}

    def fetch_historical_data(self, symbol: str, frequency: str = 'thirty_min'):
        """Fetch historical price data from Schwab"""
        log.info(f"📥 Fetching {symbol} ({frequency})...")

        try:
            df = self.fetcher.get_price_history_df(symbol, frequency=frequency)

            if df is None or df.empty:
                log.warning(f"⚠️ No data for {symbol}")
                return None

            log.info(f"✅ {symbol}: {len(df)} candles")
            return df

        except Exception as e:
            log.error(f"❌ Failed to fetch {symbol}: {e}")
            return None

    def prepare_training_data(self):
        """Fetch data for all symbols"""
        log.info("\n" + "="*80)
        log.info("FETCHING SCHWAB MARKET DATA")
        log.info("="*80)

        for symbol in self.SYMBOLS:
            df = self.fetch_historical_data(symbol, frequency='thirty_min')
            if df is not None and len(df) > 100:
                self.data[symbol] = df

        log.info(f"\n✅ Successfully fetched {len(self.data)}/{len(self.SYMBOLS)} symbols")

        if not self.data:
            log.error("❌ No data fetched!")
            return False

        return True

    def combine_data_for_training(self) -> pd.DataFrame:
        """Combine all symbol data for training"""
        log.info("\n" + "="*80)
        log.info("COMBINING DATA FOR TRAINING")
        log.info("="*80)

        combined = pd.concat([df for df in self.data.values()], ignore_index=False)
        combined = combined.sort_index().dropna()

        log.info(f"✅ Combined dataset: {len(combined)} rows from {len(self.data)} symbols")
        return combined

    def save_training_data(self, df: pd.DataFrame):
        """Save data to CSV for training"""
        filename = f"week2_training_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df.to_csv(filename)
        log.info(f"✅ Saved to {filename}")
        return filename

    def train_ppo(self, data_file: str):
        """Train PPO model"""
        log.info("\n" + "="*80)
        log.info("TRAINING PPO MODEL")
        log.info("="*80)

        try:
            # Import here to avoid import errors
            sys.path.insert(0, '/Users/ramayalala/Documents/Documents - Rama\'s MacBook Pro/trading_bot')
            from gymnasium_trainer import MultiAssetTrainer

            # Create trainer with downloaded data
            trainer = MultiAssetTrainer(
                symbols=list(self.data.keys()),
                lookback_years=1  # Use 1 year instead of 2
            )

            # Load data from CSV instead of yfinance
            log.info("📂 Loading training data...")
            df = pd.read_csv(data_file, index_col=0, parse_dates=True)

            # Create environment
            from gymnasium_trading_env import TradingEnv

            env = TradingEnv(
                df=df,
                initial_cash=10000,
                max_position_pct=0.05,
                lookback_window=100,
                episode_length=60
            )

            # Train PPO
            from stable_baselines3 import PPO

            log.info("🚀 Training PPO...")
            model = PPO(
                "MlpPolicy",
                env,
                verbose=1,
                learning_rate=3e-4,
                n_steps=2048,
                batch_size=64,
                n_epochs=10,
                gamma=0.99
            )

            model.learn(total_timesteps=100000, progress_bar=True)

            # Save model
            model_path = "gymnasium_models/gymnasium_ppo_week2"
            model.save(model_path)
            log.info(f"✅ PPO model saved to {model_path}.zip")

            return model_path

        except Exception as e:
            log.error(f"❌ PPO training failed: {e}", exc_info=True)
            return None

    def train_sac(self, data_file: str):
        """Train SAC model"""
        log.info("\n" + "="*80)
        log.info("TRAINING SAC MODEL")
        log.info("="*80)

        try:
            sys.path.insert(0, '/Users/ramayalala/Documents/Documents - Rama\'s MacBook Pro/trading_bot')
            from gymnasium_trading_env import TradingEnv
            from stable_baselines3 import SAC

            log.info("📂 Loading training data...")
            df = pd.read_csv(data_file, index_col=0, parse_dates=True)

            env = TradingEnv(
                df=df,
                initial_cash=10000,
                max_position_pct=0.05,
                lookback_window=100,
                episode_length=60
            )

            log.info("🚀 Training SAC...")
            model = SAC(
                "MlpPolicy",
                env,
                verbose=1,
                learning_rate=3e-4,
                batch_size=256,
                buffer_size=100000,
                gamma=0.99
            )

            model.learn(total_timesteps=100000, progress_bar=True)

            # Save model
            model_path = "gymnasium_models/gymnasium_sac_week2"
            model.save(model_path)
            log.info(f"✅ SAC model saved to {model_path}.zip")

            return model_path

        except Exception as e:
            log.error(f"❌ SAC training failed: {e}", exc_info=True)
            return None

    def run(self):
        """Execute full training pipeline"""
        log.info("\n" + "="*100)
        log.info("WEEK 2 GYMNASIUM TRAINING - USING SCHWAB MARKET DATA")
        log.info("="*100)

        # Step 1: Fetch data
        if not self.prepare_training_data():
            return False

        # Step 2: Combine data
        combined_df = self.combine_data_for_training()

        # Step 3: Save data
        data_file = self.save_training_data(combined_df)

        # Step 4: Train models
        log.info("\n" + "="*100)
        log.info("STARTING MODEL TRAINING")
        log.info("="*100)

        ppo_path = self.train_ppo(data_file)
        sac_path = self.train_sac(data_file)

        # Summary
        log.info("\n" + "="*100)
        log.info("WEEK 2 TRAINING COMPLETE")
        log.info("="*100)

        if ppo_path:
            log.info(f"✅ PPO model: {ppo_path}.zip")
        else:
            log.info("❌ PPO training failed")

        if sac_path:
            log.info(f"✅ SAC model: {sac_path}.zip")
        else:
            log.info("❌ SAC training failed")

        return ppo_path is not None or sac_path is not None


if __name__ == "__main__":
    trainer = Week2Trainer()
    success = trainer.run()
    sys.exit(0 if success else 1)
