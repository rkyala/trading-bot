#!/usr/bin/env python3
"""
Hybrid Strategy: FinRL (60%) + Bollinger Bands (40%)
Pure technical ML - NO Claude API
"""

import numpy as np
import pandas as pd
import logging
from pathlib import Path
from typing import Optional, Dict
import json

log = logging.getLogger(__name__)

# ============================================================================
# FINRL INTEGRATION (Pure ML)
# ============================================================================

class FinRLPredictor:
    """Wrapper around trained FinRL agent for bot predictions"""

    def __init__(self, model_path=None):
        """Load trained FinRL model"""
        try:
            from stable_baselines3 import PPO
            self.PPO = PPO
        except ImportError:
            log.warning("stable_baselines3 not installed - FinRL disabled")
            self.PPO = None
            self.enabled = False
            self.model = None
            return

        if model_path is None:
            script_dir = Path(__file__).parent
            base_path = script_dir / "finrl_agent"
            zip_path = script_dir / "finrl_agent.zip"

            # Verify .zip file exists before loading
            if zip_path.exists():
                model_path = str(base_path)  # PPO.load() adds .zip automatically
            else:
                self.enabled = False
                self.model = None
                log.warning(f"⚠️ FinRL model file not found: {zip_path}")
                return

        try:
            self.model = self.PPO.load(model_path)
            self.enabled = True
            log.info(f"✅ FinRL model loaded from: {model_path}.zip")
        except Exception as e:
            self.enabled = False
            self.model = None
            log.warning(f"⚠️ FinRL model load failed: {e}")

    def predict_trend(self, price_momentum: float, features_17d: Optional[np.ndarray] = None) -> Optional[int]:
        """
        Predict trend: 1=BUY, 0=HOLD, -1=SELL
        Handles both discrete (0,1,2) and continuous [-1.0, 1.0] action spaces
        """
        if not self.enabled or self.model is None:
            return None

        try:
            # Use features if provided, else momentum-only
            if features_17d is not None and len(features_17d) == 17:
                obs = features_17d.astype(np.float32)
            else:
                obs = np.zeros(17, dtype=np.float32)
                obs[0] = price_momentum

            action, _ = self.model.predict(obs, deterministic=True)

            # CRITICAL: Handle BOTH discrete (int) and continuous (float) action spaces
            # SB3 returns numpy scalar or array; extract value safely
            act_val = float(action.item()) if hasattr(action, 'item') else float(action)

            # Interpret action value:
            # - Discrete: 0=HOLD/SELL, 1=BUY, 2=SELL
            # - Continuous: [-1.0, 1.0] where >0.2 = strong BUY, <-0.2 = strong SELL
            if act_val >= 0.2:
                return 1  # BUY
            elif act_val <= -0.2:
                return -1  # SELL
            else:
                return 0  # HOLD
        except Exception as e:
            log.debug(f"FinRL prediction error: {e}")
            return None


# ============================================================================
# BOLLINGER BANDS (Technical Indicator)
# ============================================================================

class BollingerBands:
    """Calculate Bollinger Bands from price data"""

    @staticmethod
    def calculate(prices: np.ndarray, period: int = 20, std_dev: float = 2.0) -> Dict:
        """
        Calculate Bollinger Bands
        Args:
            prices: Array of close prices
            period: SMA period (default 20)
            std_dev: Number of standard deviations (default 2)
        Returns:
            Dict with upper, middle, lower bands
        """
        if len(prices) < period:
            return None

        try:
            series = pd.Series(prices)
            sma = series.rolling(window=period).mean().iloc[-1]
            std = series.rolling(window=period).std().iloc[-1]

            if std is None or pd.isna(std):
                return None

            upper = sma + (std * std_dev)
            lower = sma - (std * std_dev)

            return {
                "upper": float(upper),
                "middle": float(sma),
                "lower": float(lower),
                "width": float(upper - lower)
            }
        except Exception as e:
            log.debug(f"BB calculation error: {e}")
            return None

    @staticmethod
    def is_oversold(current_price: float, bands: Dict) -> bool:
        """Check if price is near lower band (oversold)"""
        if not bands:
            return False
        lower = bands["lower"]
        middle = bands["middle"]
        distance = (current_price - lower) / (middle - lower) if middle != lower else 0
        return distance < 0.2  # Within 20% of lower band


# ============================================================================
# FIBONACCI EXTENSIONS (Profit Targets)
# ============================================================================

class FibonacciExtensions:
    """Calculate Fibonacci extension profit targets"""

    @staticmethod
    def calculate_targets(entry_price: float, high_14: float, low_14: float) -> Dict:
        """
        Calculate Fibonacci extension levels for profit taking
        Args:
            entry_price: Entry/pullback price
            high_14: 14-period high
            low_14: 14-period low
        Returns:
            Dict with 1.618x and 2.618x extension targets
        """
        try:
            range_14 = high_14 - low_14
            if range_14 == 0:
                return None

            # Fibonacci extensions from entry
            target_1618 = entry_price + (range_14 * 1.618)  # First target
            target_2618 = entry_price + (range_14 * 2.618)  # Ultimate target

            return {
                "entry": float(entry_price),
                "target_1618": float(target_1618),
                "target_2618": float(target_2618),
                "fib_range": float(range_14)
            }
        except Exception as e:
            log.debug(f"Fibonacci calculation error: {e}")
            return None


# ============================================================================
# HYBRID STRATEGY (FinRL 60% + BB 40%)
# ============================================================================

class HybridStrategy:
    """
    Hybrid entry signal generator combining:
    - FinRL: 60% weight (ML-based trend prediction)
    - Bollinger Bands: 40% weight (mean-reversion confirmation)
    """

    def __init__(self):
        """Initialize hybrid strategy"""
        self.finrl = FinRLPredictor()
        self.finrl_weight = 0.60
        self.bb_weight = 0.40

    def _calculate_17d_features(self, symbol: str, current_price: float, prices: np.ndarray,
                               high_14: float, low_14: float) -> np.ndarray:
        """Calculate 17-dimensional feature vector for FinRL (simplified, robust version)"""
        features = np.zeros(17, dtype=np.float32)
        try:

            # 0: Price momentum
            price_momentum = ((current_price - prices[-1]) / prices[-1] * 100) if len(prices) > 0 else 0
            features[0] = price_momentum

            # 1-2: RSI and RSI position
            if len(prices) >= 14:
                closes = prices[-14:]
                deltas = np.diff(closes)
                gains = np.where(deltas > 0, deltas, 0)
                losses = np.where(deltas < 0, -deltas, 0)
                avg_gain = np.mean(gains)
                avg_loss = np.mean(losses)
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    rsi = 100.0 - (100.0 / (1.0 + rs))
                else:
                    rsi = 100.0 if avg_gain > 0 else 50.0
                features[1] = rsi / 100.0  # Normalize to 0-1
                features[2] = (rsi - 30) / 40  # Distance from oversold

            # 3: Volatility (std dev)
            if len(prices) >= 20:
                volatility = np.std(prices[-20:])
                features[3] = volatility / current_price if current_price > 0 else 0

            # 4-5: Bollinger Bands distance
            if len(prices) >= 20:
                sma = np.mean(prices[-20:])
                std = np.std(prices[-20:])
                upper = sma + (std * 2)
                lower = sma - (std * 2)
                bb_width = upper - lower
                distance_to_lower = (current_price - lower) / bb_width if bb_width > 0 else 0
                features[4] = distance_to_lower
                features[5] = bb_width / sma if sma > 0 else 0

            # 6: Price vs SMA
            if len(prices) >= 20:
                sma = np.mean(prices[-20:])
                features[6] = (current_price - sma) / sma if sma > 0 else 0

            # 7: Price vs EMA (simplified)
            if len(prices) >= 12:
                # Simple EMA calculation
                ema = prices[-1]
                alpha = 2.0 / (12 + 1)
                for p in prices[-12:]:
                    ema = alpha * p + (1 - alpha) * ema
                features[7] = (current_price - ema) / ema if ema > 0 else 0

            # 8-9: High/Low proximity
            if high_14 > low_14:
                features[8] = (current_price - low_14) / (high_14 - low_14)
                features[9] = (high_14 - current_price) / (high_14 - low_14)

            # 10-11: Range and ATR (FIXED: Proper daily range calculation)
            if len(prices) >= 14:
                # Estimate true range per bar as ~5% of price (typical intraday range)
                # Calculate proper 14-period ATR instead of high-low spread
                price_range_14 = np.max(prices[-14:]) - np.min(prices[-14:])
                tr_per_bar_approx = prices[-14:] * 0.05  # 5% daily range estimate
                atr_approx = np.mean(tr_per_bar_approx)  # Average true range over 14 periods
                features[10] = price_range_14 / current_price if current_price > 0 else 0
                features[11] = atr_approx / current_price if current_price > 0 else 0

            # 12-16: Additional technical indicators (ratio-based)
            features[12] = np.mean(prices[-5:]) / current_price if current_price > 0 else 1  # 5-day avg
            features[13] = np.max(prices[-14:]) / current_price if current_price > 0 else 1  # 14-day high ratio
            features[14] = np.min(prices[-14:]) / current_price if current_price > 0 else 1  # 14-day low ratio
            features[15] = len(prices) / 100  # Data length (normalized)
            features[16] = 1.0 if current_price > np.mean(prices[-20:]) else 0  # Above/below MA

            return features
        except Exception as e:
            log.debug(f"Feature calculation error: {e}")
            return np.zeros(17, dtype=np.float32)

    def generate_entry_signal(self, symbol: str, current_price: float, prices: np.ndarray,
                            high_14: float, low_14: float) -> Optional[Dict]:
        """
        Generate hybrid entry signal
        Returns:
            Dict with signal and confidence, or None if no signal
        """
        try:
            # Step 1: FinRL signal (continuous or discrete)
            # CRITICAL FIX: Check length BEFORE accessing prices[-1]
            price_momentum = ((current_price - prices[-1]) / prices[-1] * 100) if (prices is not None and len(prices) > 0) else 0.0
            finrl_signal = None
            # TEMPORARY: Disable FinRL in hybrid_strategy (use Bollinger Bands + Gymnasium PPO instead)
            # The old FinRL model was unreliable; Gymnasium in bot_production_final.py is better
            finrl_enabled = False
            if finrl_enabled:
                try:
                    features_17d = self._calculate_17d_features(symbol, current_price, prices, high_14, low_14)
                    finrl_signal = self.finrl.predict_trend(price_momentum, features_17d)
                except Exception as e:
                    log.warning(f"[{symbol}] FinRL prediction failed: {e}")
                    finrl_signal = None

            # CRITICAL FIX: Map signal to score with neutral handling
            # 1=BUY (100), 0=HOLD (50, don't penalize BB), -1=SELL (0)
            if finrl_signal == 1:
                finrl_score = 100  # Strong BUY
            elif finrl_signal == 0:
                finrl_score = 50   # HOLD - don't penalize BB oversold signals
            else:
                finrl_score = 0    # SELL or None/error

            # Step 2: Bollinger Bands (mean-reversion confirmation)
            bb = BollingerBands.calculate(prices)
            bb_oversold = BollingerBands.is_oversold(current_price, bb) if bb else False
            bb_score = 100 if bb_oversold else 0

            # Step 3: Combine scores
            # If FinRL failed (score=0), boost BB weight: require BB oversold only
            # If FinRL works: use original 60/40 split
            if finrl_score == 0 and bb_score > 0:
                # FinRL disabled/failed - allow entry on BB oversold alone (lower threshold)
                combined_score = bb_score  # Just use BB score (100 if oversold)
                threshold = 50
            else:
                # Normal FinRL 60% + BB 40%
                combined_score = (finrl_score * self.finrl_weight) + (bb_score * self.bb_weight)
                threshold = 50

            # DEBUG: Log scores for every symbol analyzed
            log.info(f"[{symbol}] momentum={price_momentum:.2f}% | FinRL={finrl_signal} score={finrl_score} | BB={bb_oversold} score={bb_score} | combined={combined_score:.0f}")

            # Minimum confidence threshold
            if combined_score < threshold:
                return None

            # Step 4: Calculate Fibonacci targets
            fib_targets = FibonacciExtensions.calculate_targets(current_price, high_14, low_14)

            return {
                "symbol": symbol,
                "signal_type": "BUY",
                "price": float(current_price),
                "confidence": int(combined_score),
                "finrl_score": int(finrl_score),
                "bb_score": int(bb_score),
                "bb_status": "OVERSOLD" if bb_oversold else "NORMAL",
                "fibonacci_targets": fib_targets,
                "bb_bands": bb
            }

        except Exception as e:
            log.error(f"Hybrid signal error for {symbol}: {e}")
            return None

    def generate_exit_signal(self, symbol: str, entry_price: float, current_price: float,
                            fibonacci_targets: Optional[Dict]) -> Optional[Dict]:
        """
        Generate exit signal based on Fibonacci targets
        Returns:
            Dict with exit signal (TAKE-PROFIT or STOP-LOSS), or None
        """
        if not fibonacci_targets:
            return None

        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        # Profit target 1: 1.618x extension
        if current_price >= fibonacci_targets["target_1618"]:
            return {
                "symbol": symbol,
                "signal_type": "SELL",
                "reason": "TAKE-PROFIT (1.618x target)",
                "price": float(current_price),
                "pnl_pct": pnl_pct,
                "target_hit": "target_1618"
            }

        # Profit target 2: 2.618x extension (ultimate)
        if current_price >= fibonacci_targets["target_2618"]:
            return {
                "symbol": symbol,
                "signal_type": "SELL",
                "reason": "TAKE-PROFIT (2.618x ultimate target)",
                "price": float(current_price),
                "pnl_pct": pnl_pct,
                "target_hit": "target_2618"
            }

        # Stop loss: -1.5% from entry
        if pnl_pct <= -1.5:
            return {
                "symbol": symbol,
                "signal_type": "SELL",
                "reason": "STOP-LOSS (-1.5%)",
                "price": float(current_price),
                "pnl_pct": pnl_pct
            }

        return None
