#!/usr/bin/env python3
"""
FinRL Agent Training Pipeline
Trains PPO agent on 2-year historical data for mean-reversion trading
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

# Setup logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

SYMBOLS = [
    "INTC", "AMD", "NVDA", "LRCX", "AVGO", "KEYS", "AMAT", "TXN", "ADI",
    "CSCO", "ENPH", "JPM", "SNPS", "CRM", "NOW", "MSFT", "CDNS", "IBM",
    "BA", "MCD", "CAT", "PG", "HD", "MA", "V", "GS", "BAC"
]

INITIAL_AMOUNT = 10000
MAX_POSITION = 1500  # Scaled up from $600
LOOKBACK_DAYS = 730  # 2 years
TRAINING_EPISODES = 100_000  # ~200 trading days worth

MODEL_PATH = "trained_ppo_agent"
DATA_PATH = "training_data.pkl"

# ============================================================================
# DATA FETCHING
# ============================================================================

def fetch_training_data():
    """Fetch 2-year historical data for all symbols"""
    log.info(f"Fetching {len(SYMBOLS)} stocks, {LOOKBACK_DAYS} days...")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)

    all_data = {}

    for symbol in SYMBOLS:
        try:
            df = yf.download(symbol, start=start_date, end=end_date, progress=False)
            if not df.empty:
                # Add technical indicators
                df['SMA_20'] = df['Close'].rolling(20).mean()
                df['SMA_50'] = df['Close'].rolling(50).mean()
                df['RSI'] = calculate_rsi(df['Close'], 14)
                df['MACD'], df['Signal'] = calculate_macd(df['Close'])

                all_data[symbol] = df
                log.info(f"  ✓ {symbol}: {len(df)} days")
        except Exception as e:
            log.error(f"  ✗ {symbol}: {e}")

    # Save data
    pd.to_pickle(all_data, DATA_PATH)
    log.info(f"Saved training data to {DATA_PATH}")

    return all_data

def calculate_rsi(prices, period=14):
    """Calculate RSI indicator"""
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    gains = pd.Series(gains)
    losses = pd.Series(losses)

    avg_gain = gains.rolling(period).mean()
    avg_loss = losses.rolling(period).mean()

    rs = avg_gain / (avg_loss + 1e-10)  # Avoid division by zero
    rsi = 100 - (100 / (1 + rs))

    return rsi.values

def calculate_macd(prices, fast=12, slow=26, signal=9):
    """Calculate MACD indicator"""
    ema_fast = prices.ewm(span=fast).mean()
    ema_slow = prices.ewm(span=slow).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal).mean()

    return macd, macd_signal

# ============================================================================
# CUSTOM GYM ENVIRONMENT
# ============================================================================

class MeanReversionTradingEnv:
    """Simplified trading environment for FinRL"""

    def __init__(self, data_dict, initial_amount=10000, max_position=1500):
        self.data_dict = data_dict
        self.initial_amount = initial_amount
        self.max_position = max_position
        self.symbols = list(data_dict.keys())
        self.num_stocks = len(self.symbols)

        # Concatenate all data
        self.data = self._prepare_data()
        self.current_step = 0
        self.max_steps = len(self.data) - 1

        # Portfolio state
        self.cash = initial_amount
        self.positions = {s: 0 for s in self.symbols}  # shares held
        self.entry_prices = {s: 0 for s in self.symbols}
        self.portfolio_history = []

        # Action space: for each stock, action 0=hold, 1=buy, 2=sell
        self.action_space_size = 3 * self.num_stocks

    def _prepare_data(self):
        """Align all data to common dates"""
        dfs = []
        for s in self.symbols:
            df = self.data_dict[s]
            if 'Close' in df.columns and len(df) > 0:
                subset = df[['Close', 'SMA_20', 'RSI']].copy()
                subset.columns = [f"{s}_Close", f"{s}_SMA_20", f"{s}_RSI"]
                dfs.append(subset)

        if not dfs:
            raise ValueError("No valid data to concatenate")

        combined = pd.concat(dfs, axis=1)
        combined = combined.fillna(combined.mean())  # Fill with mean instead of ffill
        combined = combined.dropna()
        return combined

    def reset(self):
        """Reset environment"""
        self.current_step = 0
        self.cash = self.initial_amount
        self.positions = {s: 0 for s in self.symbols}
        self.entry_prices = {s: 0 for s in self.symbols}
        self.portfolio_history = []
        return self._get_state()

    def _get_state(self):
        """Get current state vector"""
        state = []

        # Portfolio state
        state.append(self.cash / self.initial_amount)  # Normalized cash

        # For each stock
        for s in self.symbols:
            current_price = self.data[f"{s}_Close"].iloc[self.current_step]
            sma_20 = self.data[f"{s}_SMA_20"].iloc[self.current_step]
            rsi = self.data[f"{s}_RSI"].iloc[self.current_step]

            # Price trend
            state.append((current_price - sma_20) / sma_20 if sma_20 > 0 else 0)

            # RSI (normalized to 0-1)
            state.append(rsi / 100.0)

            # Position info
            state.append(self.positions[s] * current_price / self.max_position)

            # Unrealized P&L
            if self.positions[s] > 0:
                pnl = (current_price - self.entry_prices[s]) / self.entry_prices[s]
                state.append(pnl)
            else:
                state.append(0)

        return np.array(state, dtype=np.float32)

    def step(self, actions):
        """Execute one step"""
        reward = 0

        # Decode and execute actions
        for i, symbol in enumerate(self.symbols):
            action = actions[i] if isinstance(actions, (list, np.ndarray)) else actions % 3
            current_price = self.data[f"{symbol}_Close"].iloc[self.current_step]

            if action == 1:  # BUY
                if self.cash >= self.max_position * 0.1 and self.positions[symbol] == 0:
                    qty = min(self.max_position / current_price, self.cash / current_price)
                    self.positions[symbol] = qty
                    self.entry_prices[symbol] = current_price
                    self.cash -= qty * current_price
                    reward += 0.01  # Small reward for action

            elif action == 2:  # SELL
                if self.positions[symbol] > 0:
                    qty = self.positions[symbol]
                    sell_price = current_price
                    pnl = (sell_price - self.entry_prices[symbol]) / self.entry_prices[symbol]

                    self.cash += qty * sell_price
                    self.positions[symbol] = 0

                    # Reward for profit, penalty for loss
                    reward += pnl * 10

        # Portfolio value reward
        portfolio_value = self.cash + sum(
            self.positions[s] * self.data[f"{s}_Close"].iloc[self.current_step]
            for s in self.symbols
        )

        return_pct = (portfolio_value - self.initial_amount) / self.initial_amount
        reward += return_pct * 0.5  # Reward portfolio growth

        self.current_step += 1
        done = self.current_step >= self.max_steps

        self.portfolio_history.append(portfolio_value)

        return self._get_state(), reward, done, {}

    def get_metrics(self):
        """Calculate performance metrics"""
        portfolio = np.array(self.portfolio_history)
        returns = np.diff(portfolio) / portfolio[:-1]

        total_return = (portfolio[-1] - self.initial_amount) / self.initial_amount
        annual_return = total_return * (252 / len(portfolio))

        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if len(returns) > 0 else 0
        max_dd = np.min(portfolio) / np.max(portfolio[:self.current_step if self.current_step > 0 else 1]) - 1

        return {
            'total_return': total_return * 100,
            'annual_return': annual_return * 100,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd * 100,
            'final_value': portfolio[-1]
        }

# ============================================================================
# TRAINING
# ============================================================================

def train_agent():
    """Train PPO agent"""
    log.info("="*70)
    log.info("  FinRL TRAINING PIPELINE")
    log.info("="*70)

    # Step 1: Fetch data
    if not os.path.exists(DATA_PATH):
        data_dict = fetch_training_data()
    else:
        log.info(f"Loading existing data from {DATA_PATH}")
        data_dict = pd.read_pickle(DATA_PATH)

    # Step 2: Create environment
    log.info(f"\nCreating trading environment...")
    env = MeanReversionTradingEnv(data_dict, INITIAL_AMOUNT, MAX_POSITION)
    log.info(f"  Stocks: {len(env.symbols)}")
    log.info(f"  State size: {env._get_state().shape[0]}")
    log.info(f"  Actions: {env.action_space_size}")

    # Step 3: Train agent
    log.info(f"\nTraining PPO agent ({TRAINING_EPISODES:,} steps)...")
    log.info("  This will take 1-2 hours on Mac GPU...")

    env_fn = lambda: env
    vec_env = DummyVecEnv([env_fn])

    model = PPO(
        "MlpPolicy",
        vec_env,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        verbose=1
    )

    model.learn(total_timesteps=TRAINING_EPISODES)

    # Step 4: Save model
    log.info(f"\nSaving model to {MODEL_PATH}")
    model.save(MODEL_PATH)

    # Step 5: Evaluate
    log.info(f"\nEvaluating agent...")
    obs = env.reset()
    done = False

    while not done:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, done, _ = env.step(action)

    metrics = env.get_metrics()

    log.info(f"\n{'='*70}")
    log.info(f"  TRAINING RESULTS")
    log.info(f"{'='*70}")
    log.info(f"  Total Return:       {metrics['total_return']:+.2f}%")
    log.info(f"  Annual Return:      {metrics['annual_return']:+.2f}%")
    log.info(f"  Sharpe Ratio:       {metrics['sharpe_ratio']:.2f}")
    log.info(f"  Max Drawdown:       {metrics['max_drawdown']:.2f}%")
    log.info(f"  Final Portfolio:    ${metrics['final_value']:,.0f}")
    log.info(f"{'='*70}\n")

    # Save metrics
    with open("training_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    log.info("✅ Training complete! Ready for paper trading.\n")

if __name__ == "__main__":
    train_agent()
