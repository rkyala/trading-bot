"""
Volatility Filter - ATR-Based Symbol Screening
Filters out high-volatility symbols that break mean-reversion strategy

Day 1 Component: Excludes symbols with ATR > 3% of current price
Based on real data analysis showing CRWD fails with 3.5% ATR
"""

import numpy as np
import pandas as pd
import logging
from typing import Dict, Optional, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VolatilityFilter:
    """
    Average True Range (ATR) based volatility screening

    Purpose:
    - Filter out high-volatility symbols that cause whipsaws
    - CRWD (3.5% ATR) breaks mean-reversion (loses 25%)
    - ZM/JD (1.8-2.0% ATR) work perfectly (win 13-4%)

    Logic:
    - Calculate 14-period ATR
    - Convert to percentage of current price
    - Skip symbols where ATR% > 3.0%
    """

    def __init__(self, atr_window: int = 14, max_atr_pct: float = 3.0):
        """
        Args:
            atr_window: Lookback period for ATR calculation (default 14)
            max_atr_pct: Max ATR as % of price to allow (default 3%)
        """
        self.atr_window = atr_window
        self.max_atr_pct = max_atr_pct
        self.symbol_volatility_cache = {}

    @staticmethod
    def calculate_true_range(high: np.ndarray, low: np.ndarray,
                           close: np.ndarray) -> np.ndarray:
        """
        Calculate True Range for each candle

        TR = max(
            High - Low,
            |High - Previous Close|,
            |Low - Previous Close|
        )
        """
        # Handle first candle
        tr = np.zeros(len(high))

        for i in range(len(high)):
            if i == 0:
                tr[i] = high[i] - low[i]
            else:
                tr[i] = max(
                    high[i] - low[i],
                    abs(high[i] - close[i-1]),
                    abs(low[i] - close[i-1])
                )

        return tr

    def calculate_atr(self, high: np.ndarray, low: np.ndarray,
                     close: np.ndarray, window: int = 14) -> np.ndarray:
        """
        Calculate Average True Range (ATR)

        ATR = SMA of True Range over N periods
        """
        tr = self.calculate_true_range(high, low, close)

        # Simple moving average of True Range
        atr = np.zeros(len(tr))

        for i in range(len(tr)):
            if i < window:
                atr[i] = np.mean(tr[:i+1])
            else:
                atr[i] = np.mean(tr[i-window+1:i+1])

        return atr

    def calculate_atr_pct(self, high: np.ndarray, low: np.ndarray,
                         close: np.ndarray) -> float:
        """
        Calculate current ATR as percentage of current price

        Used for symbol filtering:
        - CRWD: 3.5% ATR → SKIP (too volatile)
        - ZM: 1.9% ATR → TRADE (good fit)
        - JD: 1.8% ATR → TRADE (good fit)
        """
        atr_values = self.calculate_atr(high, low, close, self.atr_window)
        current_atr = atr_values[-1]  # Latest ATR value
        current_price = close[-1]

        atr_pct = (current_atr / current_price) * 100

        return atr_pct

    def is_symbol_tradeable(self, high: np.ndarray, low: np.ndarray,
                           close: np.ndarray) -> bool:
        """
        Determine if symbol passes volatility filter

        Returns:
            True if ATR% <= max_atr_pct (symbol is tradeable)
            False if ATR% > max_atr_pct (skip this symbol)
        """
        if len(high) < self.atr_window:
            logger.warning(f"Insufficient data for ATR calculation")
            return False

        atr_pct = self.calculate_atr_pct(high, low, close)

        return atr_pct <= self.max_atr_pct

    def screen_symbols(self, symbol_data: Dict[str, Dict]) -> Dict[str, bool]:
        """
        Screen multiple symbols for volatility

        Args:
            symbol_data: Dict mapping symbol -> {'high': [...], 'low': [...], 'close': [...]}

        Returns:
            Dict mapping symbol -> True/False (tradeable)
        """
        results = {}

        for symbol, candles in symbol_data.items():
            high = np.array(candles['high'])
            low = np.array(candles['low'])
            close = np.array(candles['close'])

            atr_pct = self.calculate_atr_pct(high, low, close)
            is_tradeable = self.is_symbol_tradeable(high, low, close)

            results[symbol] = is_tradeable
            self.symbol_volatility_cache[symbol] = atr_pct

            status = "✅ PASS" if is_tradeable else "❌ SKIP"
            logger.info(f"[{symbol}] Volatility filter: {atr_pct:.2f}% ATR {status}")

        return results

    def filter_symbol_list(self, symbols: List[str],
                          symbol_data: Dict[str, Dict]) -> List[str]:
        """
        Filter symbol list to only tradeable symbols

        Args:
            symbols: List of symbols to check
            symbol_data: OHLCV data for each symbol

        Returns:
            List of symbols that pass volatility filter
        """
        tradeable = []
        skipped = []

        for symbol in symbols:
            if symbol not in symbol_data:
                logger.warning(f"[{symbol}] No data available")
                skipped.append(symbol)
                continue

            candles = symbol_data[symbol]
            high = np.array(candles['high'])
            low = np.array(candles['low'])
            close = np.array(candles['close'])

            if len(high) < self.atr_window:
                logger.warning(f"[{symbol}] Insufficient candles ({len(high)} < {self.atr_window})")
                skipped.append(symbol)
                continue

            atr_pct = self.calculate_atr_pct(high, low, close)

            if atr_pct <= self.max_atr_pct:
                tradeable.append(symbol)
                logger.info(f"✅ [{symbol}] PASS - ATR {atr_pct:.2f}%")
            else:
                skipped.append(symbol)
                logger.warning(f"❌ [{symbol}] SKIP - ATR {atr_pct:.2f}% > {self.max_atr_pct}%")

        logger.info(f"\nVolatility Screening Results:")
        logger.info(f"  Tradeable: {tradeable}")
        logger.info(f"  Skipped:   {skipped}")

        return tradeable

    def get_volatility_report(self) -> Dict:
        """Get summary of symbol volatility levels"""
        return {
            'cache': self.symbol_volatility_cache,
            'max_allowed_atr_pct': self.max_atr_pct,
            'symbols_over_limit': {
                symbol: atr for symbol, atr in self.symbol_volatility_cache.items()
                if atr > self.max_atr_pct
            }
        }


# Example usage and test
if __name__ == "__main__":
    # Create sample data (simulating CRWD, ZM, JD)
    np.random.seed(42)

    # CRWD: High volatility (3.5% ATR)
    crwd_close = np.array([190 + np.random.randn() * 5 for _ in range(50)])
    crwd_high = crwd_close + abs(np.random.randn(50))
    crwd_low = crwd_close - abs(np.random.randn(50))

    # ZM: Moderate volatility (1.9% ATR)
    zm_close = np.array([140 + np.random.randn() * 1.5 for _ in range(50)])
    zm_high = zm_close + abs(np.random.randn(50) * 0.5)
    zm_low = zm_close - abs(np.random.randn(50) * 0.5)

    # JD: Mild volatility (1.8% ATR)
    jd_close = np.array([60 + np.random.randn() * 0.8 for _ in range(50)])
    jd_high = jd_close + abs(np.random.randn(50) * 0.3)
    jd_low = jd_close - abs(np.random.randn(50) * 0.3)

    # Test filter
    vf = VolatilityFilter(max_atr_pct=3.0)

    symbol_data = {
        'CRWD': {'high': crwd_high, 'low': crwd_low, 'close': crwd_close},
        'ZM': {'high': zm_high, 'low': zm_low, 'close': zm_close},
        'JD': {'high': jd_high, 'low': jd_low, 'close': jd_close}
    }

    results = vf.screen_symbols(symbol_data)
    print(f"\nScreening Results: {results}")
    print(f"Volatility Report: {vf.get_volatility_report()}")
