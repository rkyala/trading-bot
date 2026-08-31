#!/usr/bin/env python3
"""
Gymnasium Trading Environment Trainer
Trains PPO/SAC agents on multi-asset portfolios with advanced technical features
"""

import os
import sys
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import logging
from pathlib import Path

from stable_baselines3 import PPO, SAC
from stable_baselines3.common.callbacks import EvalCallback, StopTrainingOnNoModelImprovement
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.monitor import Monitor

from gymnasium_trading_env import TradingEnv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)


class MultiAssetTrainer:
    """Train RL agents on multiple assets with technical features"""

    def __init__(
        self,
        symbols: list = None,
        lookback_years: int = 2,
        training_symbols: list = None,
        eval_symbols: list = None,
        initial_cash: float = 100000,
        model_dir: str = "./gymnasium_models"
    ):
        """
        Initialize trainer

        Args:
            symbols: List of symbols to download data for
            lookback_years: Historical data to use (default 2 years)
            training_symbols: Symbols to train on (default all)
            eval_symbols: Symbols to evaluate on (default first symbol)
            initial_cash: Starting capital per episode
            model_dir: Directory to save models
        """
        self.symbols = symbols or ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN"]
        self.training_symbols = training_symbols or self.symbols[:-1]
        self.eval_symbols = eval_symbols or [self.symbols[-1]]
        self.lookback_years = lookback_years
        self.initial_cash = initial_cash
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(exist_ok=True)

        self.train_data = {}
        self.eval_data = {}
        self.envs = {}

    def download_data(self, symbol: str) -> pd.DataFrame:
        """Download historical data for symbol"""
        log.info(f"📥 Downloading {symbol}...")

        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * self.lookback_years)

        try:
            df = yf.download(
                symbol,
                start=start_date,
                end=end_date,
                progress=False
            )

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            # Handle single symbol download returning Series
            if isinstance(df, pd.Series):
                df = pd.DataFrame(df)

            # Rename columns to standard format
            df.columns = [col.lower() for col in df.columns]
            if 'adj close' in df.columns:
                df['close'] = df['adj close']
            if 'adj close' in df.columns:
                df = df.drop('adj close', axis=1)

            # Ensure required columns
            required = ['open', 'high', 'low', 'close', 'volume']
            for col in required:
                if col not in df.columns:
                    raise ValueError(f"Missing column: {col}")

            df = df.dropna()

            if len(df) < 252 * self.lookback_years:
                raise ValueError(f"Insufficient data: {len(df)} rows")

            log.info(f"✅ {symbol}: {len(df)} days of data")
            return df

        except Exception as e:
            log.error(f"❌ Failed to download {symbol}: {e}")
            raise

    def prepare_data(self):
        """Download and prepare training/eval data"""
        log.info("\n" + "="*80)
        log.info("DATA PREPARATION")
        log.info("="*80)

        # Download training data
        for symbol in self.training_symbols:
            self.train_data[symbol] = self.download_data(symbol)

        # Download eval data
        for symbol in self.eval_symbols:
            self.eval_data[symbol] = self.download_data(symbol)

    def create_training_env(self):
        """Create training environment with all training symbols"""
        log.info("\n" + "="*80)
        log.info("CREATING TRAINING ENVIRONMENT")
        log.info("="*80)

        # Use concatenated data from all training symbols
        combined_df = pd.concat([self.train_data[s] for s in self.training_symbols])
        combined_df = combined_df.sort_index().dropna()

        env = TradingEnv(
            df=combined_df,
            initial_cash=self.initial_cash,
            max_position_pct=0.05,
            lookback_window=252,
            episode_length=60
        )

        self.envs['train'] = Monitor(env)
        log.info(f"✅ Training env created with {len(combined_df)} days")

    def create_eval_env(self):
        """Create evaluation environment"""
        log.info("\n" + "="*80)
        log.info("CREATING EVALUATION ENVIRONMENT")
        log.info("="*80)

        # Use first eval symbol's data
        eval_df = self.eval_data[self.eval_symbols[0]]

        env = TradingEnv(
            df=eval_df,
            initial_cash=self.initial_cash,
            max_position_pct=0.05,
            lookback_window=252,
            episode_length=60
        )

        self.envs['eval'] = Monitor(env)
        log.info(f"✅ Eval env created with {len(eval_df)} days ({self.eval_symbols[0]})")

    def train_ppo(
        self,
        total_timesteps: int = 100000,
        learning_rate: float = 3e-4,
        n_steps: int = 2048,
        batch_size: int = 64,
        n_epochs: int = 10,
        resume_from: str = None
    ):
        """Train PPO agent"""
        log.info("\n" + "="*80)
        log.info("TRAINING PPO AGENT")
        log.info("="*80)

        model_path = self.model_dir / "gymnasium_ppo"

        if resume_from:
            log.info(f"📂 Resuming from {resume_from}")
            model = PPO.load(resume_from, env=self.envs['train'])
        else:
            model = PPO(
                "MlpPolicy",
                self.envs['train'],
                verbose=1,
                learning_rate=learning_rate,
                n_steps=n_steps,
                batch_size=batch_size,
                n_epochs=n_epochs,
                gamma=0.99,
                gae_lambda=0.95,
                clip_range=0.2,
                tensorboard_log=self.model_dir / "tb_logs"
            )

        # Evaluation callback
        eval_callback = EvalCallback(
            self.envs['eval'],
            best_model_save_path=str(self.model_dir),
            log_path=str(self.model_dir),
            eval_freq=10000,
            n_eval_episodes=5,
            deterministic=False
        )

        # Early stopping
        stop_callback = StopTrainingOnNoModelImprovement(
            max_no_improvement_evals=5,
            min_evals=10,
            verbose=1
        )

        log.info(f"🚀 Training for {total_timesteps:,} timesteps...")

        model.learn(
            total_timesteps=total_timesteps,
            callback=[eval_callback, stop_callback],
            progress_bar=True
        )

        # Save final model
        model.save(str(model_path))
        log.info(f"✅ PPO model saved to {model_path}")

        return model

    def train_sac(
        self,
        total_timesteps: int = 100000,
        learning_rate: float = 3e-4,
        batch_size: int = 256,
        buffer_size: int = 100000,
        resume_from: str = None
    ):
        """Train SAC agent (continuous action space version)"""
        log.info("\n" + "="*80)
        log.info("TRAINING SAC AGENT")
        log.info("="*80)

        model_path = self.model_dir / "gymnasium_sac"

        if resume_from:
            log.info(f"📂 Resuming from {resume_from}")
            model = SAC.load(resume_from, env=self.envs['train'])
        else:
            model = SAC(
                "MlpPolicy",
                self.envs['train'],
                verbose=1,
                learning_rate=learning_rate,
                batch_size=batch_size,
                buffer_size=buffer_size,
                gamma=0.99,
                tensorboard_log=self.model_dir / "tb_logs"
            )

        # Evaluation callback
        eval_callback = EvalCallback(
            self.envs['eval'],
            best_model_save_path=str(self.model_dir),
            log_path=str(self.model_dir),
            eval_freq=10000,
            n_eval_episodes=5,
            deterministic=True
        )

        log.info(f"🚀 Training for {total_timesteps:,} timesteps...")

        model.learn(
            total_timesteps=total_timesteps,
            callback=eval_callback,
            progress_bar=True
        )

        # Save final model
        model.save(str(model_path))
        log.info(f"✅ SAC model saved to {model_path}")

        return model

    def evaluate_model(self, model_path: str, n_episodes: int = 10):
        """Evaluate trained model"""
        log.info("\n" + "="*80)
        log.info(f"EVALUATING MODEL: {model_path}")
        log.info("="*80)

        # Determine model type from path
        if "ppo" in model_path.lower():
            model = PPO.load(model_path, env=self.envs['eval'])
        elif "sac" in model_path.lower():
            model = SAC.load(model_path, env=self.envs['eval'])
        else:
            raise ValueError(f"Unknown model type: {model_path}")

        results = {
            'returns': [],
            'sharpe': [],
            'max_dd': [],
            'win_rate': [],
            'trades': []
        }

        for ep in range(n_episodes):
            obs, _ = self.envs['eval'].reset()
            done = False
            episode_reward = 0

            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, done, truncated, info = self.envs['eval'].step(action)
                episode_reward += reward
                done = done or truncated

            # Get backtest results
            backtest_stats = self.envs['eval'].env.get_backtest_results()
            results['returns'].append(backtest_stats.get('final_return', 0))
            results['sharpe'].append(backtest_stats.get('sharpe', 0))
            results['max_dd'].append(backtest_stats.get('max_drawdown', 0))
            results['win_rate'].append(backtest_stats.get('win_rate', 0))
            results['trades'].append(backtest_stats.get('total_trades', 0))

            log.info(f"Episode {ep+1}: Return={backtest_stats.get('final_return', 0):+.2f}%, "
                    f"Sharpe={backtest_stats.get('sharpe', 0):.2f}, "
                    f"Trades={backtest_stats.get('total_trades', 0)}")

        # Summary statistics
        log.info("\n" + "="*80)
        log.info("EVALUATION RESULTS")
        log.info("="*80)
        log.info(f"Avg Return:     {np.mean(results['returns']):+.2f}%")
        log.info(f"Avg Sharpe:     {np.mean(results['sharpe']):.2f}")
        log.info(f"Avg Max DD:     {np.mean(results['max_dd']):.2f}%")
        log.info(f"Avg Win Rate:   {np.mean(results['win_rate']):.1f}%")
        log.info(f"Avg Trades:     {np.mean(results['trades']):.0f}")

        return results


def main():
    """Main training pipeline"""
    import argparse

    parser = argparse.ArgumentParser(description="Train RL agents for trading")
    parser.add_argument("--model", choices=["ppo", "sac"], default="ppo",
                        help="Model type to train (ppo or sac)")
    parser.add_argument("--timesteps", type=int, default=100000,
                        help="Total training timesteps")
    parser.add_argument("--symbols", nargs="+", default=["AAPL", "NVDA", "TSLA", "MSFT", "SPY"],
                        help="Symbols to train on")
    parser.add_argument("--eval-only", action="store_true",
                        help="Only evaluate existing model")
    parser.add_argument("--model-path", type=str, default=None,
                        help="Path to trained model for evaluation")
    parser.add_argument("--resume-from", type=str, default=None,
                        help="Resume training from checkpoint")

    args = parser.parse_args()

    # Initialize trainer
    trainer = MultiAssetTrainer(
        symbols=args.symbols,
        lookback_years=2,
        training_symbols=args.symbols[:-1] if len(args.symbols) > 1 else args.symbols,
        eval_symbols=[args.symbols[-1]] if len(args.symbols) > 1 else args.symbols
    )

    # Prepare data
    trainer.prepare_data()
    trainer.create_training_env()
    trainer.create_eval_env()

    if args.eval_only:
        # Evaluate only
        if not args.model_path:
            model_path = trainer.model_dir / f"gymnasium_{args.model}"
            if not model_path.exists():
                raise FileNotFoundError(f"Model not found: {model_path}")
        else:
            model_path = args.model_path

        trainer.evaluate_model(str(model_path), n_episodes=10)

    else:
        # Train model
        if args.model == "ppo":
            trainer.train_ppo(
                total_timesteps=args.timesteps,
                resume_from=args.resume_from
            )
        else:
            trainer.train_sac(
                total_timesteps=args.timesteps,
                resume_from=args.resume_from
            )

        # Evaluate
        model_path = trainer.model_dir / f"gymnasium_{args.model}"
        trainer.evaluate_model(str(model_path), n_episodes=5)


if __name__ == "__main__":
    main()
