#!/usr/bin/env python3
"""
FinRL Integration for Trading Bot
Loads trained FinRL agent and provides entry/exit predictions
"""

import numpy as np
from stable_baselines3 import PPO
import logging
import os
import sys

log = logging.getLogger(__name__)

class FinRLPredictor:
    """Wrapper around trained FinRL agent for bot predictions"""
    
    def __init__(self, model_path=None):
        """Load trained model
        
        Args:
            model_path: Path to model (without .zip extension). 
                       If None, looks in script directory.
        """
        if model_path is None:
            # Try to find the model in the current directory or script directory
            script_dir = os.path.dirname(os.path.abspath(__file__))
            model_path = os.path.join(script_dir, "finrl_agent")
        
        # Debug logging
        full_zip_path = model_path + ".zip"
        log.info(f"DEBUG: Script dir = {os.path.dirname(os.path.abspath(__file__))}")
        log.info(f"DEBUG: Model path = {model_path}")
        log.info(f"DEBUG: Full zip path = {full_zip_path}")
        log.info(f"DEBUG: Zip exists = {os.path.exists(full_zip_path)}")
        log.info(f"DEBUG: CWD = {os.getcwd()}")
        log.info(f"DEBUG: Files in script dir: {os.listdir(os.path.dirname(os.path.abspath(__file__)))[:10]}")
        
        try:
            self.model = PPO.load(model_path)
            self.enabled = True
            log.info(f"✅ FinRL agent loaded from: {model_path}.zip")
        except FileNotFoundError as e:
            self.enabled = False
            log.error(f"❌ FinRL agent file not found at {full_zip_path}")
            log.error(f"DEBUG: FileNotFoundError: {e}")
            self.model = None
        except Exception as e:
            self.enabled = False
            log.error(f"❌ FinRL agent load error: {type(e).__name__}: {str(e)}")
            import traceback
            log.error(f"DEBUG: Traceback: {traceback.format_exc()}")
            self.model = None
    
    def predict_action(self, observation):
        """
        Get FinRL prediction for next action
        
        Returns: 0=hold, 1=buy, 2=sell
        """
        if not self.enabled or self.model is None:
            return None
        
        try:
            action, _ = self.model.predict(observation, deterministic=True)
            return int(action)
        except Exception as e:
            log.debug("FinRL prediction error: %s", e)
            return None
    
    def should_buy(self, symbol, price, portfolio_state):
        """
        Predict if this is a good BUY opportunity
        
        Args:
            symbol: Stock symbol
            price: Current price
            portfolio_state: Dict with cash, positions, etc.
        
        Returns: True if agent predicts action=1 (buy)
        """
        if not self.enabled:
            return None
        
        try:
            # Build observation (simplified version)
            obs = np.array([
                portfolio_state.get("cash_ratio", 0.5),  # % cash available
                (price - portfolio_state.get("entry_prices", {}).get(symbol, price)) / price if symbol in portfolio_state.get("entry_prices", {}) else 0,  # Price momentum
                portfolio_state.get("positions", {}).get(symbol, 0) / portfolio_state.get("max_pos", 1),  # Current position ratio
            ], dtype=np.float32)
            
            action = self.predict_action(obs)
            return action == 1  # Buy action
        except Exception as e:
            log.debug("FinRL buy prediction error: %s", e)
            return None
    
    def should_sell(self, symbol, pnl_pct):
        """
        Predict if this is a good SELL opportunity
        
        Args:
            symbol: Stock symbol
            pnl_pct: Current P&L percentage
        
        Returns: True if agent predicts action=2 (sell)
        """
        if not self.enabled:
            return None
        
        try:
            obs = np.array([pnl_pct], dtype=np.float32)
            action = self.predict_action(obs)
            return action == 2  # Sell action
        except Exception as e:
            log.debug("FinRL sell prediction error: %s", e)
            return None

# Global predictor instance
finrl_predictor = None

def initialize_finrl():
    """Initialize FinRL predictor at bot startup"""
    global finrl_predictor
    finrl_predictor = FinRLPredictor()
    return finrl_predictor.enabled

def get_finrl_buy_confidence(symbol, price, portfolio_state):
    """
    Get confidence score (0-100) from FinRL for BUY
    Falls back to 0 if FinRL disabled
    """
    if not finrl_predictor or not finrl_predictor.enabled:
        return None
    
    should_buy = finrl_predictor.should_buy(symbol, price, portfolio_state)
    return 75 if should_buy else 0  # High confidence if agent says buy, else skip
