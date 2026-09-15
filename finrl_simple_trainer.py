#!/usr/bin/env python3
"""
Simplified FinRL Agent Training
Uses raw OHLCV data only (no custom indicators)
"""

import os
import json
import logging
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv
import gymnasium as gym
from gymnasium import spaces

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

SYMBOLS = [
    "INTC", "AMD", "NVDA", "LRCX", "AVGO", "KEYS", "AMAT", "TXN",
    "CSCO", "ENPH", "JPM", "SNPS", "CRM", "NOW", "MSFT", "CDNS"
]

INITIAL_AMOUNT = 10000
MAX_POSITION = 1500
LOOKBACK_DAYS = 730
TRAINING_EPISODES = 50_000

MODEL_PATH = "trained_ppo_agent"

# ============================================================================
# DATA FETCHING
# ============================================================================

def fetch_training_data():
    """Fetch historical data"""
    log.info(f"Fetching {len(SYMBOLS)} stocks, {LOOKBACK_DAYS} days...")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)

    all_data = {}

    for symbol in SYMBOLS:
        try:
            df = yf.download(symbol, start=start_date, end=end_date, progress=False)
            if not df.empty and len(df) > 50:
                # Normalize prices to 0-1 range
                df['Close_Norm'] = (df['Close'] - df['Close'].min()) / (df['Close'].max() - df['Close'].min())
                all_data[symbol] = df
                log.info(f"  ✓ {symbol}: {len(df)} days")
        except Exception as e:
            log.warning(f"  ✗ {symbol}: {e}")

    log.info(f"Loaded {len(all_data)} stocks\n")
    return all_data

# ============================================================================
# GYM ENVIRONMENT
# ============================================================================

class SimpleTradingEnv(gym.Env):
    """Simplified trading environment"""

    metadata = {'render.modes': ['human']}

    def __init__(self, data_dict, initial_amount=10000, max_position=1500):
        super().__init__()

        self.data_dict = data_dict
        self.symbols = list(data_dict.keys())
        self.initial_amount = initial_amount
        self.max_position = max_position
        self.num_stocks = len(self.symbols)

        # Combine data
        self.all_data = pd.concat(
            [data_dict[s][['Close']].rename(columns={'Close': f'{s}_Close'})
             for s in self.symbols],
            axis=1
        ).dropna()

        self.current_step = 0
        self.max_steps = len(self.all_data) - 1

        # Portfolio
        self.cash = initial_amount
        self.positions = {s: 0 for s in self.symbols}
        self.entry_prices = {s: 0 for s in self.symbols}
        self.portfolio_values = []

        # Action space: 0-2 for each stock (hold, buy, sell)
        self.action_space = spaces.MultiDiscrete([3] * self.num_stocks)

        # Observation space: normalized prices + portfolio state
        self.observation_space = spaces.Box(
            low=0, high=1, shape=(self.num_stocks * 2 + 1,), dtype=np.float32
        )

    def reset(self, seed=None):
        """Reset environment"""
        super().reset(seed=seed)
        self.current_step = 0
        self.cash = self.initial_amount
        self.positions = {s: 0 for s in self.symbols}
        self.entry_prices = {s: 0 for s in self.symbols}
        self.portfolio_values = []
        return self._get_obs(), {}

    def _get_obs(self):
        """Get observation"""
        obs = []

        # Cash ratio
        obs.append(float(np.clip(self.cash / self.initial_amount, 0, 1)))

        # Current prices (normalized)
        for s in self.symbols:
            price = float(self.all_data[f'{s}_Close'].iloc[self.current_step])
            all_prices = self.all_data[f'{s}_Close'].values
            normalized_price = float((price - all_prices.min()) / (all_prices.max() - all_prices.min() + 1e-8))
            obs.append(normalized_price)

        # Position ratios
        for s in self.symbols:
            price = float(self.all_data[f'{s}_Close'].iloc[self.current_step])
            position_value = self.positions[s] * price
            position_ratio = float(np.clip(position_value / self.max_position, 0, 1))
            obs.append(position_ratio)

        return np.array(obs[:self.num_stocks * 2 + 1], dtype=np.float32)

    def step(self, action):
        """Execute one step"""
        reward = 0.0
        info = {}

        # Execute actions
        for i, symbol in enumerate(self.symbols):
            action_val = int(action[i]) if isinstance(action, (list, np.ndarray)) else 0
            price = self.all_data[f'{symbol}_Close'].iloc[self.current_step]

            if action_val == 1 and self.cash >= self.max_position * 0.1:  # BUY
                qty = min(self.max_position / price, self.cash / price * 0.9)
                if qty > 0 and self.positions[symbol] == 0:
                    self.cash -= qty * price
                    self.positions[symbol] = qty
                    self.entry_prices[symbol] = price

            elif action_val == 2 and self.positions[symbol] > 0:  # SELL
                qty = self.positions[symbol]
                proceeds = qty * price
                pnl_pct = (price - self.entry_prices[symbol]) / self.entry_prices[symbol]
                self.cash += proceeds
                self.positions[symbol] = 0
                reward += pnl_pct  # Reward for profit

        # Portfolio value reward
        portfolio_value = self.cash
        for s in self.symbols:
            price = self.all_data[f'{s}_Close'].iloc[self.current_step]
            portfolio_value += self.positions[s] * price

        self.portfolio_values.append(portfolio_value)

        # Reward for portfolio growth
        if len(self.portfolio_values) > 1:
            growth = (self.portfolio_values[-1] - self.portfolio_values[-2]) / self.portfolio_values[-2]
            reward += growth * 10

        self.current_step += 1
        done = self.current_step >= self.max_steps
        terminated = done

        return self._get_obs(), reward, terminated, False, info

    def get_metrics(self):
        """Calculate performance"""
        if not self.portfolio_values:
            return {}

        pv = np.array(self.portfolio_values)
        total_return = (pv[-1] - self.initial_amount) / self.initial_amount
        annual_return = total_return * (252 / len(pv))

        if len(pv) > 1:
            returns = np.diff(pv) / pv[:-1]
            sharpe = np.mean(returns) / (np.std(returns) + 1e-8) * np.sqrt(252)
            max_dd = np.min((pv - np.maximum.accumulate(pv)) / np.maximum.accumulate(pv))
        else:
            sharpe = 0
            max_dd = 0

        return {
            'total_return': total_return * 100,
            'annual_return': annual_return * 100,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd * 100,
            'final_value': float(pv[-1])
        }

# ============================================================================
# TRAINING
# ============================================================================

def train_agent():
    """Train agent"""
    log.info("="*70)
    log.info("  FinRL TRAINING (Simplified)")
    log.info("="*70 + "\n")

    # Fetch data
    data_dict = fetch_training_data()

    if len(data_dict) < 5:
        log.error("Not enough data. Please check your internet connection.")
        return

    # Create environment
    log.info("Creating environment...")
    env = SimpleTradingEnv(data_dict, INITIAL_AMOUNT, MAX_POSITION)
    log.info(f"  Symbols: {env.num_stocks}")
    log.info(f"  State size: {env.observation_space.shape[0]}")
    log.info(f"  Action space: {env.action_space}\n")

    # Train
    log.info(f"Training PPO agent ({TRAINING_EPISODES:,} steps)...")
    log.info("  This will take 10-30 minutes on your Mac...\n")

    vec_env = DummyVecEnv([lambda: env])

    model = PPO(
        "MlpPolicy",
        vec_env,
        learning_rate=1e-3,
        n_steps=512,
        batch_size=32,
        n_epochs=5,
        gamma=0.99,
        verbose=1
    )

    model.learn(total_timesteps=TRAINING_EPISODES)

    # Save
    log.info(f"\nSaving model...")
    model.save(MODEL_PATH)

    # Evaluate
    log.info("Evaluating...")
    obs, _ = env.reset()
    done = False

    while not done:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated

    metrics = env.get_metrics()

    log.info("\n" + "="*70)
    log.info("  TRAINING COMPLETE")
    log.info("="*70)
    log.info(f"  Total Return:       {metrics['total_return']:+.2f}%")
    log.info(f"  Annual Return:      {metrics['annual_return']:+.2f}%")
    log.info(f"  Sharpe Ratio:       {metrics['sharpe_ratio']:.2f}")
    log.info(f"  Max Drawdown:       {metrics['max_drawdown']:.2f}%")
    log.info(f"  Final Value:        ${metrics['final_value']:,.0f}")
    log.info("="*70 + "\n")

    # Save metrics
    with open("training_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    log.info("✅ Ready for paper trading!\n")
    log.info("Next: python3 paper_trading.py\n")

if __name__ == "__main__":
    train_agent()
