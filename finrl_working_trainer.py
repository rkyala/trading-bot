#!/usr/bin/env python3
"""
Working FinRL Agent Trainer
Uses working data handling from simple_paper_trading.py
Zero cost - runs on your Mac GPU
"""

import json
import yfinance as yf
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv
import gymnasium as gym
from gymnasium import spaces

# ============================================================================
# TECHNICAL INDICATORS
# ============================================================================

def calculate_rsi(prices, period=14):
    """Calculate RSI (Relative Strength Index)"""
    if len(prices) < period + 1:
        return 50.0
    try:
        deltas = np.diff(prices[-period-1:])
        gains = np.array([d for d in deltas if d > 0])
        losses = np.array([abs(d) for d in deltas if d < 0])

        if len(gains) == 0 or len(losses) == 0:
            return 50.0

        gain = np.mean(gains)
        loss = np.mean(losses)

        if loss == 0 or np.isnan(gain) or np.isnan(loss):
            return 50.0

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return float(np.clip(rsi, 0, 100))
    except:
        return 50.0

def calculate_macd(prices, fast=12, slow=26):
    """Calculate MACD"""
    if len(prices) < slow:
        return 0.0, 0.0
    try:
        fast_ema = pd.Series(prices).ewm(span=fast).mean().iloc[-1]
        slow_ema = pd.Series(prices).ewm(span=slow).mean().iloc[-1]
        macd = float(fast_ema - slow_ema)
        if np.isnan(macd):
            return 0.0, 0.0
        return np.clip(macd, -50, 50), 0.0
    except:
        return 0.0, 0.0

def calculate_bollinger_bands(prices, period=20):
    """Calculate Bollinger Bands"""
    if len(prices) < period:
        return 50.0, 50.0, 50.0
    try:
        sma = np.mean(prices[-period:])
        std = np.std(prices[-period:])
        upper = sma + (2 * std)
        lower = sma - (2 * std)
        current = prices[-1]

        if std == 0:
            return 50.0, sma, sma

        bb_position = (current - lower) / (upper - lower + 1e-8)
        if np.isnan(bb_position):
            return 50.0, float(upper), float(lower)
        return float(np.clip(bb_position, 0, 100)), float(upper), float(lower)
    except:
        return 50.0, 0.0, 0.0

def calculate_atr(high, low, close, period=14):
    """Calculate Average True Range"""
    if len(close) < period:
        return 0.0
    try:
        tr_list = []
        for i in range(len(close)):
            if i == 0:
                tr = high[i] - low[i]
            else:
                tr = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
            tr_list.append(tr)
        atr = np.mean(tr_list[-period:])
        if np.isnan(atr) or close[-1] <= 0:
            return 0.0
        result = float(atr / close[-1])
        return float(np.clip(result, 0, 10))
    except:
        return 0.0

def calculate_momentum(prices, period=10):
    """Calculate momentum (price change %)"""
    if len(prices) < period:
        return 0.0
    try:
        if prices[-period] <= 0:
            return 0.0
        change = (prices[-1] - prices[-period]) / prices[-period]
        if np.isnan(change):
            return 0.0
        return float(np.clip(change * 100, -50, 50))
    except:
        return 0.0

def calculate_volume_indicator(volume, period=20):
    """Calculate volume strength indicator"""
    if len(volume) < period:
        return 50.0
    try:
        avg_vol = np.mean(volume[-period:])
        curr_vol = volume[-1]

        if avg_vol <= 0 or curr_vol <= 0:
            return 50.0

        vol_ratio = min(curr_vol / avg_vol, 3.0)  # Cap at 3x
        if np.isnan(vol_ratio):
            return 50.0
        return float(np.clip((vol_ratio / 3.0) * 100, 0, 100))
    except:
        return 50.0

print("\n" + "="*70)
print("  FinRL AGENT TRAINING (Working Version)")
print("="*70 + "\n")

# Configuration
SYMBOLS = ["INTC", "AMD", "NVDA", "LRCX", "AVGO", "KEYS", "AMAT", "TXN"]
INITIAL = 10000
MAX_POS = 1500
LOOKBACK_DAYS = 365
TRAINING_STEPS = 50_000

# Fetch data
print(f"Fetching {len(SYMBOLS)} stocks, {LOOKBACK_DAYS} days (live data)...\n")

end_date = datetime.now()
start_date = end_date - timedelta(days=LOOKBACK_DAYS)

data_dict = {}
for symbol in SYMBOLS:
    try:
        df = yf.download(symbol, start=start_date, end=end_date, progress=False)
        if not df.empty and len(df) > 50:
            data_dict[symbol] = df
            print(f"  ✓ {symbol}: {len(df)} days (${df['Close'].iloc[-1]:.2f})")
    except Exception as e:
        print(f"  ✗ {symbol}: {e}")

if len(data_dict) < 5:
    print("\n❌ Not enough data. Check internet connection.")
    exit(1)

print(f"\n✓ Loaded {len(data_dict)} stocks\n")

# ============================================================================
# SIMPLE TRADING ENVIRONMENT
# ============================================================================

class TradingEnv(gym.Env):
    """Simple trading environment"""

    def __init__(self, data_dict, initial=10000, max_pos=1500):
        super().__init__()

        self.data_dict = data_dict
        self.symbols = list(data_dict.keys())
        self.initial = initial
        self.max_pos = max_pos
        self.n_stocks = len(self.symbols)

        # Store full OHLCV data
        self.data = {}
        for s in self.symbols:
            df = data_dict[s]
            self.data[s] = {
                'close': df['Close'].values.astype(float),
                'high': df['High'].values.astype(float) if 'High' in df else df['Close'].values.astype(float),
                'low': df['Low'].values.astype(float) if 'Low' in df else df['Close'].values.astype(float),
                'volume': df['Volume'].values.astype(float) if 'Volume' in df else np.ones(len(df))
            }

        # Get length
        self.data_len = len(data_dict[self.symbols[0]])

        self.step_idx = 0
        self.cash = initial
        self.positions = {s: 0.0 for s in self.symbols}
        self.entry_prices = {s: 0.0 for s in self.symbols}
        self.portfolio_values = []

        # Gym spaces
        # Old: n_stocks * 2 + 1 = 17 for 8 stocks
        # New: cash + (price + position + 8 technical indicators per stock)
        # = 1 + n_stocks * (1 + 1 + 6 technical features) = 1 + n_stocks * 8
        # For 8 stocks: 1 + 64 = 65 dimensions
        self.n_features_per_stock = 8  # price, position, rsi, macd, bb, atr, momentum, volume
        obs_dim = 1 + self.n_stocks * self.n_features_per_stock

        self.action_space = spaces.MultiDiscrete([3] * self.n_stocks)
        self.observation_space = spaces.Box(low=-1, high=100, shape=(obs_dim,), dtype=np.float32)

    def reset(self, seed=None):
        super().reset(seed=seed)
        self.step_idx = 0
        self.cash = self.initial
        self.positions = {s: 0.0 for s in self.symbols}
        self.entry_prices = {s: 0.0 for s in self.symbols}
        self.portfolio_values = []
        return self._get_obs(), {}

    def _get_obs(self):
        """Get observation with technical indicators"""
        obs = [float(np.clip(self.cash / self.initial, 0, 1))]

        # Per-stock features
        for s in self.symbols:
            idx = self.step_idx
            if idx >= len(self.data[s]['close']):
                idx = len(self.data[s]['close']) - 1

            price = float(self.data[s]['close'][idx])
            prices = self.data[s]['close'][:idx+1]
            high_prices = self.data[s]['high'][:idx+1]
            low_prices = self.data[s]['low'][:idx+1]
            volumes = self.data[s]['volume'][:idx+1]

            # 1. Normalized price
            norm_price = (price - prices.min()) / (prices.max() - prices.min() + 1e-8)
            obs.append(float(np.clip(norm_price * 100, 0, 100)))

            # 2. Position ratio
            pos_value = self.positions[s] * price
            pos_ratio = np.clip(pos_value / self.max_pos, 0, 1)
            obs.append(float(pos_ratio * 100))

            # 3. RSI (14-period, 0-100)
            rsi = calculate_rsi(prices, period=14)
            obs.append(float(rsi))

            # 4. MACD (momentum indicator, -50 to 50)
            macd, _ = calculate_macd(prices)
            obs.append(float(np.clip(macd, -50, 50)))

            # 5. Bollinger Bands position (0-100)
            bb_pos, _, _ = calculate_bollinger_bands(prices, period=20)
            obs.append(float(bb_pos))

            # 6. ATR (Average True Range, volatility, 0-10)
            atr = calculate_atr(high_prices, low_prices, prices, period=14)
            obs.append(float(np.clip(atr * 100, 0, 100)))

            # 7. Momentum (price change %, -50 to 50)
            momentum = calculate_momentum(prices, period=10)
            obs.append(float(momentum))

            # 8. Volume indicator (0-100)
            vol_ind = calculate_volume_indicator(volumes, period=20)
            obs.append(float(vol_ind))

        return np.array(obs, dtype=np.float32)

    def step(self, action):
        """Execute one step"""
        reward = 0.0

        # Get current price data (clamp to valid range)
        idx = min(self.step_idx, self.data_len - 1)
        if idx < 0:
            idx = 0

        # Execute actions
        for i, symbol in enumerate(self.symbols):
            action_val = int(action[i]) if isinstance(action, (list, np.ndarray)) else 0
            price = float(self.data[symbol]['close'][idx])

            if action_val == 1 and self.cash > self.max_pos * 0.1:  # BUY
                if self.positions[symbol] == 0:
                    qty = float(min(self.max_pos / price, self.cash / price * 0.9))
                    if qty > 0:
                        cost = float(qty * price)
                        self.cash = float(self.cash - cost)
                        self.positions[symbol] = qty
                        self.entry_prices[symbol] = price

            elif action_val == 2 and self.positions[symbol] > 0:  # SELL
                qty = float(self.positions[symbol])
                entry = float(self.entry_prices[symbol])
                proceeds = float(qty * price)
                pnl_pct = (price - entry) / entry if entry > 0 else 0
                self.cash = float(self.cash + proceeds)
                self.positions[symbol] = 0
                reward += float(pnl_pct * 10)  # Reward for profit

        # Portfolio value reward
        portfolio = float(self.cash)
        for s in self.symbols:
            price = float(self.data[s]['close'][idx])
            portfolio += float(self.positions[s] * price)

        self.portfolio_values.append(portfolio)

        if len(self.portfolio_values) > 1:
            growth = (self.portfolio_values[-1] - self.portfolio_values[-2]) / self.portfolio_values[-2]
            reward += float(growth * 5)

        self.step_idx += 1
        done = self.step_idx >= self.data_len - 2  # End early to avoid edge cases

        return self._get_obs(), float(reward), done, False, {}

    def get_metrics(self):
        """Get performance metrics"""
        pv = np.array(self.portfolio_values)

        total_ret = (pv[-1] - self.initial) / self.initial if len(pv) > 0 else 0
        annual_ret = total_ret * (252 / len(pv)) if len(pv) > 0 else 0

        if len(pv) > 1:
            rets = np.diff(pv) / pv[:-1]
            sharpe = np.mean(rets) / (np.std(rets) + 1e-8) * np.sqrt(252)
            dd = np.min((pv - np.maximum.accumulate(pv)) / np.maximum.accumulate(pv))
        else:
            sharpe = 0
            dd = 0

        return {
            'total_return': float(total_ret * 100),
            'annual_return': float(annual_ret * 100),
            'sharpe': float(sharpe),
            'max_dd': float(dd * 100),
            'final_value': float(pv[-1])
        }

# ============================================================================
# TRAIN
# ============================================================================

print("Creating environment...")
env = TradingEnv(data_dict, INITIAL, MAX_POS)
print(f"  Stocks: {env.n_stocks}")
print(f"  State size: {env.observation_space.shape[0]}")
print(f"  Action space: {env.action_space}\n")

print(f"Training PPO agent ({TRAINING_STEPS:,} steps)...")
print(f"  Running on Mac GPU (no cost)...\n")

vec_env = DummyVecEnv([lambda: env])

model = PPO(
    "MlpPolicy",
    vec_env,
    learning_rate=1e-3,
    n_steps=256,
    batch_size=32,
    n_epochs=5,
    gamma=0.99,
    verbose=0  # Silent
)

# Train
model.learn(total_timesteps=TRAINING_STEPS)

# Evaluate
print("Evaluating agent on full dataset...\n")
obs, _ = env.reset()
done = False

while not done:
    action, _ = model.predict(obs, deterministic=True)
    obs, reward, done, _, _ = env.step(action)

metrics = env.get_metrics()

# Save
model.save("finrl_agent")

print("="*70)
print("  FINRL TRAINING RESULTS")
print("="*70)
print(f"\nFinal Value:       ${metrics['final_value']:,.0f}")
print(f"Total Return:      {metrics['total_return']:+.2f}%")
print(f"Annualized:        {metrics['annual_return']:+.2f}%")
print(f"Sharpe Ratio:      {metrics['sharpe']:.2f}")
print(f"Max Drawdown:      {metrics['max_dd']:.2f}%\n")

print("="*70)
print("✅ Training Complete!")
print("="*70 + "\n")

# Save metrics
with open("finrl_metrics.json", "w") as f:
    json.dump(metrics, f, indent=2)

# Compare to paper trading
print("COMPARISON TO PAPER TRADING:")
print(f"  Paper Trading (mean-reversion rules): +39.09% annualized")
print(f"  FinRL Agent:                          {metrics['annual_return']:+.2f}% annualized\n")

if metrics['annual_return'] > 39:
    print("✅ FinRL outperforms rule-based strategy!")
elif metrics['annual_return'] > 30:
    print("✅ FinRL competitive with rules-based strategy")
else:
    print("⚠️  FinRL underperforms (needs more tuning)")

print()
