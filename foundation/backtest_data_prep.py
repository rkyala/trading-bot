"""
Backtest Data Preparation
Generates synthetic 180-day backtest data with diverse market regimes

Day 2 Data Prep: Creates realistic OHLCV for CRWD, ZM, JD testing
Includes bull, bear, sideways, and volatile regimes
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict
import os
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BacktestDataGenerator:
    """
    Generates synthetic 180-day backtest data

    Includes diverse market regimes:
    1. Bull market (Days 1-45)
    2. Sideways/choppy (Days 46-90)
    3. Bear market (Days 91-135)
    4. Vol spike (Days 136-180)
    """

    def __init__(self, output_dir: str = 'backtest_data'):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.trading_days = 180

    @staticmethod
    def generate_market_regime(regime: str, days: int,
                              start_price: float,
                              volatility: float) -> np.ndarray:
        """
        Generate price movements for specific market regime

        Regimes:
        - 'bull': Uptrend with positive drift
        - 'sideways': Range-bound with low drift
        - 'bear': Downtrend with negative drift
        - 'volatile': High volatility with random walk
        """
        np.random.seed(42 + hash(regime) % 10000)

        if regime == 'bull':
            drift = 0.0015  # +0.15% daily drift (bullish)
        elif regime == 'sideways':
            drift = 0.0000  # No drift (choppy)
        elif regime == 'bear':
            drift = -0.0015  # -0.15% daily drift (bearish)
        else:  # volatile
            drift = 0.0005  # Slight upside but high vol
            volatility *= 1.5  # Increase vol spike

        returns = np.random.normal(drift, volatility, days)
        prices = start_price * np.exp(np.cumsum(returns))

        return prices

    def generate_symbol_data(self, symbol: str,
                           start_price: float,
                           avg_volatility: float) -> pd.DataFrame:
        """
        Generate complete 180-day OHLCV data for symbol

        Four regimes across 180 days:
        - Days 1-45: Bull market
        - Days 46-90: Sideways
        - Days 91-135: Bear market
        - Days 136-180: Volatile spike
        """
        all_prices = []

        # Bull market (45 days)
        bull_prices = self.generate_market_regime(
            'bull', 45, start_price, avg_volatility
        )
        all_prices.extend(bull_prices)

        # Sideways (45 days)
        sideways_prices = self.generate_market_regime(
            'sideways', 45, bull_prices[-1], avg_volatility
        )
        all_prices.extend(sideways_prices)

        # Bear market (45 days)
        bear_prices = self.generate_market_regime(
            'bear', 45, sideways_prices[-1], avg_volatility
        )
        all_prices.extend(bear_prices)

        # Volatile spike (45 days)
        volatile_prices = self.generate_market_regime(
            'volatile', 45, bear_prices[-1], avg_volatility
        )
        all_prices.extend(volatile_prices)

        prices = np.array(all_prices)

        # Generate OHLCV from daily prices
        df = pd.DataFrame()
        df['Date'] = pd.date_range(start='2026-01-02', periods=180, freq='B')  # Business days
        df['Open'] = prices * (1 + np.random.randn(180) * 0.002)
        df['High'] = prices + abs(np.random.randn(180) * avg_volatility * prices * 0.5)
        df['Low'] = prices - abs(np.random.randn(180) * avg_volatility * prices * 0.5)
        df['Close'] = prices
        df['Volume'] = np.random.randint(500000, 2000000, 180)

        # Ensure OHLC order
        df['High'] = df[['Open', 'High', 'Close']].max(axis=1)
        df['Low'] = df[['Open', 'Low', 'Close']].min(axis=1)

        return df

    def generate_30min_data(self, daily_df: pd.DataFrame) -> pd.DataFrame:
        """
        Expand daily data to 30-minute candles

        Generates intraday data from daily OHLCV
        Creates realistic 30-min candles for backtest
        """
        all_30min = []

        for idx, row in daily_df.iterrows():
            date = row['Date']
            open_price = row['Open']
            high_price = row['High']
            low_price = row['Low']
            close_price = row['Close']
            daily_volume = row['Volume']

            # Generate 13 intraday 30-min candles (9:30 AM - 4:00 PM)
            intraday_prices = np.linspace(open_price, close_price, 14)
            intraday_volumes = np.random.dirichlet(np.ones(13)) * daily_volume

            for i in range(13):
                candle_time = date.replace(hour=9, minute=30) + timedelta(minutes=30*i)

                # Add intraday noise
                o = intraday_prices[i] * (1 + np.random.randn() * 0.001)
                h = max(intraday_prices[i:i+2]) * (1 + abs(np.random.randn() * 0.002))
                l = min(intraday_prices[i:i+2]) * (1 - abs(np.random.randn() * 0.002))
                c = intraday_prices[i+1] * (1 + np.random.randn() * 0.001)

                all_30min.append({
                    'DateTime': candle_time,
                    'Open': o,
                    'High': h,
                    'Low': l,
                    'Close': c,
                    'Volume': int(intraday_volumes[i])
                })

        df_30min = pd.DataFrame(all_30min)
        return df_30min

    def generate_all_symbols(self) -> Dict[str, Dict]:
        """
        Generate complete dataset for all symbols (CRWD, ZM, JD)

        Returns:
            Dict mapping symbol -> daily and 30-min DataFrames
        """
        symbols = {
            'CRWD': {'start_price': 190, 'volatility': 0.035},  # High vol
            'ZM': {'start_price': 140, 'volatility': 0.019},    # Med vol
            'JD': {'start_price': 60, 'volatility': 0.018}      # Low vol
        }

        all_data = {}

        for symbol, params in symbols.items():
            logger.info(f"\nGenerating {symbol} data...")

            # Generate daily data
            daily_df = self.generate_symbol_data(
                symbol,
                params['start_price'],
                params['volatility']
            )

            # Generate 30-min data
            min_30_df = self.generate_30min_data(daily_df)

            all_data[symbol] = {
                'daily': daily_df,
                'intraday_30min': min_30_df
            }

            logger.info(
                f"✅ [{symbol}] Generated 180 daily + {len(min_30_df)} 30-min candles"
            )

        return all_data

    def save_data_to_csv(self, all_data: Dict[str, Dict]):
        """Save generated data to CSV files"""
        for symbol, data in all_data.items():
            # Save daily
            daily_file = os.path.join(self.output_dir, f"{symbol}_daily.csv")
            data['daily'].to_csv(daily_file, index=False)
            logger.info(f"✅ Saved {daily_file}")

            # Save 30-min
            intraday_file = os.path.join(self.output_dir, f"{symbol}_30min.csv")
            data['intraday_30min'].to_csv(intraday_file, index=False)
            logger.info(f"✅ Saved {intraday_file}")

    def validate_regime_distribution(self, df: pd.DataFrame) -> Dict:
        """Validate that data covers diverse regimes"""
        returns = df['Close'].pct_change()

        bull_days = len(df[returns > 0.01])  # Up >1%
        bear_days = len(df[returns < -0.01])  # Down >1%
        sideways_days = len(df[(returns >= -0.01) & (returns <= 0.01)])
        high_vol_days = len(df[abs(returns) > 0.02])  # Vol >2%

        total = len(df)

        return {
            'bull_days': bull_days,
            'bear_days': bear_days,
            'sideways_days': sideways_days,
            'high_vol_days': high_vol_days,
            'bull_pct': bull_days / total * 100,
            'bear_pct': bear_days / total * 100,
            'sideways_pct': sideways_days / total * 100,
            'high_vol_pct': high_vol_days / total * 100
        }

    def print_data_summary(self, all_data: Dict[str, Dict]):
        """Print summary of generated data"""
        print("\n" + "="*70)
        print("BACKTEST DATA GENERATION SUMMARY")
        print("="*70)

        for symbol, data in all_data.items():
            daily_df = data['daily']
            intraday_df = data['intraday_30min']

            print(f"\n[{symbol}]")
            print(f"  Daily candles:      {len(daily_df)}")
            print(f"  30-min candles:     {len(intraday_df)}")
            print(f"  Price range:        ${daily_df['Low'].min():.2f} - ${daily_df['High'].max():.2f}")
            print(f"  Start date:         {daily_df['Date'].min().date()}")
            print(f"  End date:           {daily_df['Date'].max().date()}")

            # Regime distribution
            regimes = self.validate_regime_distribution(daily_df)
            print(f"\n  Market Regimes:")
            print(f"    Bull (daily +1%):     {regimes['bull_days']:3d} days ({regimes['bull_pct']:5.1f}%)")
            print(f"    Bear (daily -1%):     {regimes['bear_days']:3d} days ({regimes['bear_pct']:5.1f}%)")
            print(f"    Sideways:             {regimes['sideways_days']:3d} days ({regimes['sideways_pct']:5.1f}%)")
            print(f"    High Vol (>2%):       {regimes['high_vol_days']:3d} days ({regimes['high_vol_pct']:5.1f}%)")

        print("\n" + "="*70 + "\n")


# Generate data
if __name__ == "__main__":
    generator = BacktestDataGenerator(output_dir='backtest_data')

    # Generate all symbol data
    all_data = generator.generate_all_symbols()

    # Save to CSV
    generator.save_data_to_csv(all_data)

    # Print summary
    generator.print_data_summary(all_data)

    logger.info("✅ Backtest data generation complete!")
