#!/usr/bin/env python3
"""
Custom Gymnasium Trading Environment
17D Technical Features + Stable-Baselines3 Compatible
Designed for PPO/SAC agents with realistic market dynamics
"""

import gymnasium as gym
from gymnasium import spaces
import numpy as np
import pandas as pd
import logging
from typing import Dict, Tuple, Optional
import yfinance as yf
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

class TradingEnv(gym.Env):
    """
    Gymnasium Trading Environment with:
    - 17D technical feature space (RSI, MACD, BB, ATR, VWAP, etc.)
    - Realistic position management
    - Risk-adjusted reward function
    - Episode windowing for efficient training
    """

    metadata = {'render_modes': []}

    def __init__(
        self,
        df: pd.DataFrame,
        initial_cash: float = 100000,
        max_position_pct: float = 0.05,  # 5% per position
        lookback_window: int = 252,  # 1 year
        episode_length: int = 60,  # ~3 months trading days
    ):
        """
        Initialize trading environment

        Args:
            df: DataFrame with OHLCV data and technical indicators
            initial_cash: Starting capital
            max_position_pct: Maximum position size as % of portfolio
            lookback_window: Historical data for feature calculation
            episode_length: Trading days per episode
        """
        super().__init__()

        self.df = df.copy()
        self.initial_cash = initial_cash
        self.current_cash = initial_cash
        self.max_position_pct = max_position_pct
        self.lookback_window = lookback_window
        self.episode_length = episode_length

        # Calculate all technical indicators
        self._calculate_indicators()

        # State tracking
        self.current_step = 0
        self.start_idx = lookback_window
        self.position = 0.0  # Current position size (fraction of cash)
        self.entry_price = 0.0
        self.highest_price = 0.0
        self.trades_made = 0
        self.portfolio_value = initial_cash
        self.daily_returns = []

        # Action space: 0=hold, 1=buy (5% position), 2=buy (10%), 3=sell all
        self.action_space = spaces.Discrete(4)

        # Observation space: 17D technical features
        # RSI (1), MACD (3), Bollinger (3), ATR (1), VWAP (1),
        # ADX (1), CCI (1), Stoch (2), Portfolio State (3)
        self.observation_space = spaces.Box(
            low=0,
            high=1,
            shape=(17,),
            dtype=np.float32
        )

    def _calculate_indicators(self):
        """Calculate all 17D technical features"""
        df = self.df.copy()

        # Normalize column names to handle both lowercase and uppercase
        df.columns = [col.capitalize() if col.lower() in ['close', 'open', 'high', 'low', 'volume', 'adj close']
                      else col for col in df.columns]

        # 1. RSI (14-period)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df['RSI'] = 100 - (100 / (1 + rs))

        # 2-4. MACD (12, 26, 9)
        ema12 = df['Close'].ewm(span=12).mean()
        ema26 = df['Close'].ewm(span=26).mean()
        df['MACD'] = ema12 - ema26
        df['Signal'] = df['MACD'].ewm(span=9).mean()
        df['MACD_Hist'] = df['MACD'] - df['Signal']

        # 5-7. Bollinger Bands
        df['BB_Mid'] = df['Close'].rolling(20).mean()
        bb_std = df['Close'].rolling(20).std()
        df['BB_Upper'] = df['BB_Mid'] + (bb_std * 2)
        df['BB_Lower'] = df['BB_Mid'] - (bb_std * 2)
        df['BB_Percent'] = (df['Close'] - df['BB_Lower']) / (df['BB_Upper'] - df['BB_Lower'] + 1e-9)

        # 8. ATR (14-period)
        high_low = df['High'] - df['Low']
        high_close = (df['High'] - df['Close'].shift()).abs()
        low_close = (df['Low'] - df['Close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(14).mean()

        # 9. VWAP (cumulative volume weighted)
        df['VWAP'] = (df['Close'] * df['Volume']).rolling(20).sum() / df['Volume'].rolling(20).sum()

        # 10. ADX (14-period trend strength)
        up_move = df['High'].diff()
        down_move = -df['Low'].diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        atr14 = df['ATR']
        plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(14).mean() / (atr14 + 1e-9))
        minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(14).mean() / (atr14 + 1e-9))
        dx = 100 * ((plus_di - minus_di).abs() / ((plus_di + minus_di) + 1e-9))
        df['ADX'] = dx.rolling(14).mean()

        # 11. CCI (20-period)
        tp = (df['High'] + df['Low'] + df['Close']) / 3
        sma_tp = tp.rolling(20).mean()
        mad = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - x.mean())))
        df['CCI'] = (tp - sma_tp) / (0.015 * (mad + 1e-9))

        # 12-13. Stochastic (14, 3, 3)
        low_min = df['Low'].rolling(14).min()
        high_max = df['High'].rolling(14).max()
        df['Stoch'] = 100 * ((df['Close'] - low_min) / (high_max - low_min + 1e-9))
        df['Stoch_SMA'] = df['Stoch'].rolling(3).mean()

        # Fill NaN with forward fill then backward fill
        df = df.fillna(method='ffill').fillna(method='bfill')

        self.df = df

    def _normalize_features(self, idx: int) -> np.ndarray:
        """Get normalized 17D feature vector at index"""
        row = self.df.iloc[idx]

        # Normalize features to [0, 1]
        features = np.array([
            # 1. RSI (0-100) -> 0-1
            row['RSI'] / 100.0,
            # 2-4. MACD (normalize using ATR)
            np.clip((row['MACD'] / (row['ATR'] + 1e-9)) + 0.5, 0, 1),
            np.clip((row['Signal'] / (row['ATR'] + 1e-9)) + 0.5, 0, 1),
            np.clip((row['MACD_Hist'] / (row['ATR'] + 1e-9)) + 0.5, 0, 1),
            # 5-7. Bollinger Bands
            np.clip(row['BB_Percent'], 0, 1),
            np.clip((row['Close'] - row['VWAP']) / (row['ATR'] + 1e-9) + 0.5, 0, 1),
            np.clip((row['BB_Mid'] - row['Close']) / (row['ATR'] + 1e-9) + 0.5, 0, 1),
            # 8. ATR (normalize log scale)
            np.clip(np.log(row['ATR'] + 1e-9) / 5.0, 0, 1),
            # 9. VWAP distance
            np.clip((row['Close'] - row['VWAP']) / (row['Close'] * 0.05 + 1e-9) + 0.5, 0, 1),
            # 10. ADX (0-100) -> 0-1
            np.clip(row['ADX'] / 100.0, 0, 1),
            # 11. CCI (normalize)
            np.clip((row['CCI'] / 200.0) + 0.5, 0, 1),
            # 12-13. Stochastic
            np.clip(row['Stoch'] / 100.0, 0, 1),
            np.clip(row['Stoch_SMA'] / 100.0, 0, 1),
            # 14-16. Portfolio state
            np.clip(self.current_cash / self.initial_cash, 0, 1),  # Cash ratio
            self.position,  # Current position
            np.clip(self.portfolio_value / self.initial_cash, 0, 2),  # Portfolio value (can be > 1)
        ], dtype=np.float32)

        return features

    def reset(self, seed: Optional[int] = None) -> Tuple[np.ndarray, Dict]:
        """Reset environment to random start within lookback window"""
        super().reset(seed=seed)

        # Adjust lookback window if dataset is smaller
        lookback = min(self.lookback_window, max(50, len(self.df) // 3))

        # Random start within valid range
        valid_range = len(self.df) - lookback - self.episode_length
        if valid_range < 1:
            raise ValueError(f"Dataset too small: {len(self.df)} rows, need {lookback + self.episode_length}")

        self.start_idx = np.random.randint(lookback, lookback + valid_range) if valid_range > 0 else lookback
        self.current_step = self.start_idx

        # Reset state
        self.current_cash = self.initial_cash
        self.position = 0.0
        self.entry_price = 0.0
        self.highest_price = self.df.iloc[self.current_step]['Close']
        self.trades_made = 0
        self.portfolio_value = self.initial_cash
        self.daily_returns = []

        obs = self._normalize_features(self.current_step)
        return obs, {}

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict]:
        """
        Execute one step in the environment

        Actions:
        0 = Hold
        1 = Buy 5% position
        2 = Buy 10% position
        3 = Sell all
        """
        self.current_step += 1

        # Check if episode is done
        done = self.current_step >= self.start_idx + self.episode_length
        truncated = done

        # Get current and previous prices
        prev_price = self.df.iloc[self.current_step - 1]['Close']
        curr_price = self.df.iloc[self.current_step]['Close']
        price_change = (curr_price - prev_price) / prev_price

        reward = 0.0

        # Execute action
        if action == 0:  # Hold
            if self.position > 0:
                # Reward for holding winning positions
                if curr_price > self.entry_price:
                    reward = (curr_price - self.entry_price) / self.entry_price * self.position * 100

        elif action in [1, 2]:  # Buy
            position_size = 0.05 if action == 1 else 0.10
            max_pos = self.initial_cash * self.max_position_pct
            position_value = self.initial_cash * position_size

            if self.current_cash >= position_value and self.position < self.max_position_pct:
                self.position += position_size
                self.current_cash -= position_value
                self.entry_price = curr_price
                self.highest_price = curr_price
                self.trades_made += 1
                reward = -0.5  # Small penalty for entry (slippage)

        elif action == 3:  # Sell all
            if self.position > 0:
                exit_value = self.position * self.initial_cash * (curr_price / self.entry_price)
                pnl = exit_value - (self.position * self.initial_cash)
                self.current_cash += pnl + (self.position * self.initial_cash)

                # Reward based on P&L
                if pnl > 0:
                    reward = (pnl / (self.position * self.initial_cash)) * 100
                else:
                    reward = (pnl / (self.position * self.initial_cash)) * 100

                self.position = 0.0
                self.entry_price = 0.0

        # Update portfolio value
        if self.position > 0:
            self.portfolio_value = self.current_cash + (self.position * self.initial_cash * (curr_price / self.entry_price))
            self.highest_price = max(self.highest_price, curr_price)
        else:
            self.portfolio_value = self.current_cash

        # Add return to history
        daily_return = (self.portfolio_value - self.initial_cash) / self.initial_cash
        self.daily_returns.append(daily_return)

        # Penalty for drawdown
        current_drawdown = (self.highest_price - curr_price) / self.highest_price if self.highest_price > 0 else 0
        if current_drawdown > 0.05:  # Penalty for > 5% drawdown
            reward -= current_drawdown * 10

        # Small reward for holding cash when market is volatile
        atr = self.df.iloc[self.current_step]['ATR']
        volatility = atr / curr_price if curr_price > 0 else 0
        if self.position == 0 and volatility > 0.02:
            reward += 0.1  # Reward for staying in cash during high volatility

        # Observation
        obs = self._normalize_features(self.current_step)

        return obs, reward, done, truncated, {}

    def get_backtest_results(self) -> Dict:
        """Get backtest statistics for episode"""
        if not self.daily_returns:
            return {}

        returns = np.array(self.daily_returns)
        final_return = returns[-1] if len(returns) > 0 else 0

        # Calculate Sharpe ratio (annualized)
        if len(returns) > 1:
            sharpe = (np.mean(returns) / (np.std(returns) + 1e-9)) * np.sqrt(252)
        else:
            sharpe = 0

        # Calculate max drawdown
        cumulative = np.cumprod(1 + np.array([r - (r_prev if i > 0 else 0)
                                              for i, (r, r_prev) in enumerate(zip(returns, [0] + list(returns[:-1])))]))
        max_dd = np.min(cumulative - np.maximum.accumulate(cumulative)) / np.maximum.accumulate(cumulative).max() if len(cumulative) > 0 else 0

        win_rate = (np.array(self.daily_returns) > 0).sum() / len(self.daily_returns) * 100 if len(self.daily_returns) > 0 else 0

        return {
            'final_return': final_return * 100,
            'sharpe': sharpe,
            'max_drawdown': max_dd * 100,
            'win_rate': win_rate,
            'total_trades': self.trades_made,
            'final_portfolio_value': self.portfolio_value
        }
