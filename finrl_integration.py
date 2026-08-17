#!/usr/bin/env python3
"""
FinRL Model Integration
Load and use trained FinRL model for trading predictions
"""

import os
import json
from pathlib import Path

def load_finrl_model():
    """
    Load trained FinRL model

    Returns:
        FinRL model object or None if not available
    """
    try:
        # Try local model first
        model_path = Path("finrl_agent")
        if model_path.exists():
            from stable_baselines3 import PPO
            model = PPO.load(str(model_path))
            print("✅ Loaded local FinRL model")
            return model

        # Try Railway deployed model
        model_path = Path("/app/finrl_agent")
        if model_path.exists():
            from stable_baselines3 import PPO
            model = PPO.load(str(model_path))
            print("✅ Loaded Railway FinRL model")
            return model

        print("⚠️  FinRL model not found")
        return None

    except Exception as e:
        print(f"⚠️  Error loading FinRL model: {e}")
        return None


def get_finrl_prediction(model, observation):
    """
    Get FinRL prediction for given observation

    Args:
        model: FinRL PPO model
        observation: numpy array of state features

    Returns:
        action: predicted action (0=hold, 1=buy, 2=sell)
        confidence: confidence score 0-1
    """
    if model is None:
        return None, 0

    try:
        action, _ = model.predict(observation, deterministic=True)

        # Convert to action name and confidence
        if isinstance(action, (list, tuple)):
            action = action[0]

        # Confidence based on action certainty
        confidence = 0.6 if action == 1 else 0.3  # BUY is more confident

        return int(action), confidence

    except Exception as e:
        print(f"⚠️  Prediction error: {e}")
        return None, 0


def get_finrl_metrics():
    """Get latest FinRL training metrics"""
    try:
        metrics_path = Path("finrl_metrics.json")
        if metrics_path.exists():
            with open(metrics_path) as f:
                return json.load(f)
        return None
    except:
        return None


if __name__ == "__main__":
    print("\n" + "="*70)
    print("  FINRL INTEGRATION TEST")
    print("="*70 + "\n")

    model = load_finrl_model()

    if model:
        print("✅ FinRL model loaded successfully!")
        metrics = get_finrl_metrics()
        if metrics:
            print(f"\nLast training metrics:")
            print(f"  Sharpe Ratio:  {metrics.get('sharpe', 0):.2f}")
            print(f"  Annual Return: {metrics.get('annual_return', 0):+.2f}%")
            print(f"  Max Drawdown:  {metrics.get('max_dd', 0):.2f}%")
    else:
        print("⚠️  FinRL model not available (optional)")

    print("\n" + "="*70 + "\n")
