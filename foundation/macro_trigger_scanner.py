"""
Non-Blocking Macro Trigger Scanner
Calculates daily trend flags and stores in atomic JSON

Day 2 Component 5: Daily 50-SMA trend calculation
Non-blocking (<5 seconds) to avoid cycle stalls
"""

import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta
import logging
from typing import Dict, Optional
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MacroTriggerScanner:
    """
    Non-blocking daily trend calculation

    Purpose:
    - Calculate daily 50-SMA trend status
    - Store in macro_triggers.json atomically
    - Non-blocking (<5 seconds per scan)
    - Used by foundation_engine for MTF context

    Macro Triggers:
    - "daily_bullish": Price >= daily 50-SMA (bullish trend)
    - "daily_bearish": Price < daily 50-SMA (bearish trend)
    """

    def __init__(self, cache_file: str = 'macro_triggers.json'):
        self.cache_file = cache_file
        self.sma_window = 50
        self.symbols_scanned = 0
        self.scan_duration = 0

    def calculate_daily_sma(self, daily_closes: np.ndarray,
                          window: int = 50) -> float:
        """
        Calculate 50-day simple moving average

        Args:
            daily_closes: Array of daily close prices
            window: SMA window (default 50)

        Returns:
            Current 50-SMA value
        """
        if len(daily_closes) < window:
            # Not enough data, return current price as neutral
            return daily_closes[-1] if len(daily_closes) > 0 else 0

        sma = np.mean(daily_closes[-window:])
        return sma

    def get_daily_trend(self, current_price: float,
                       sma_50: float) -> str:
        """
        Determine daily trend based on price vs 50-SMA

        Args:
            current_price: Current daily close price
            sma_50: 50-day simple moving average

        Returns:
            "BULLISH" if price >= SMA, "BEARISH" if price < SMA
        """
        if current_price >= sma_50:
            return "BULLISH"
        else:
            return "BEARISH"

    def calculate_distance_from_sma(self, current_price: float,
                                   sma_50: float) -> float:
        """
        Calculate distance from current price to 50-SMA

        Positive = price above SMA (bullish)
        Negative = price below SMA (bearish)
        """
        return ((current_price - sma_50) / sma_50) * 100

    def scan_symbol(self, symbol: str, daily_closes: np.ndarray) -> Dict:
        """
        Scan single symbol for macro triggers

        Args:
            symbol: Stock symbol (e.g., "ZM")
            daily_closes: Array of recent daily closes

        Returns:
            {
                'symbol': str,
                'current_price': float,
                'sma_50': float,
                'trend': str ('BULLISH' or 'BEARISH'),
                'distance_pct': float,
                'scan_time': str (ISO format)
            }
        """
        if len(daily_closes) == 0:
            logger.warning(f"[{symbol}] No price data available")
            return None

        current_price = daily_closes[-1]
        sma_50 = self.calculate_daily_sma(daily_closes)
        trend = self.get_daily_trend(current_price, sma_50)
        distance = self.calculate_distance_from_sma(current_price, sma_50)

        result = {
            'symbol': symbol,
            'current_price': round(current_price, 2),
            'sma_50': round(sma_50, 2),
            'trend': trend,
            'distance_pct': round(distance, 2),
            'scan_time': datetime.utcnow().isoformat()
        }

        logger.info(
            f"[{symbol}] Trend: {trend} | Price: ${current_price:.2f} | "
            f"SMA50: ${sma_50:.2f} | Distance: {distance:+.2f}%"
        )

        return result

    def scan_symbols(self, symbol_data: Dict[str, np.ndarray]) -> Dict[str, Dict]:
        """
        Scan multiple symbols non-blockingly

        Args:
            symbol_data: Dict mapping symbol -> daily_closes array

        Returns:
            Dict mapping symbol -> macro trigger info
        """
        start_time = datetime.utcnow()
        results = {}

        for symbol, daily_closes in symbol_data.items():
            result = self.scan_symbol(symbol, daily_closes)
            if result:
                results[symbol] = result

        end_time = datetime.utcnow()
        self.scan_duration = (end_time - start_time).total_seconds()
        self.symbols_scanned = len(results)

        logger.info(
            f"✅ Macro scan complete: {self.symbols_scanned} symbols in "
            f"{self.scan_duration:.2f}s"
        )

        return results

    def write_triggers_atomic(self, triggers: Dict[str, Dict]) -> bool:
        """
        Write macro triggers to JSON file atomically

        Uses temporary file + rename to prevent partial writes

        Args:
            triggers: Trigger data to write

        Returns:
            True if successful, False if error
        """
        try:
            # Create atomic write structure
            data = {
                'last_scan': datetime.utcnow().isoformat(),
                'triggers': triggers,
                'scan_duration_sec': self.scan_duration,
                'symbols_scanned': self.symbols_scanned
            }

            # Write to temp file first
            temp_file = f"{self.cache_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)

            # Atomic rename
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
            os.rename(temp_file, self.cache_file)

            logger.info(f"✅ Macro triggers written to {self.cache_file}")
            return True

        except Exception as e:
            logger.error(f"❌ Error writing macro triggers: {e}")
            return False

    def read_triggers(self) -> Optional[Dict]:
        """
        Read latest macro triggers from JSON file

        Returns:
            Triggers dict or None if file doesn't exist
        """
        try:
            if not os.path.exists(self.cache_file):
                logger.warning(f"Macro triggers file not found: {self.cache_file}")
                return None

            with open(self.cache_file, 'r') as f:
                data = json.load(f)

            return data

        except Exception as e:
            logger.error(f"Error reading macro triggers: {e}")
            return None

    def get_trend_for_symbol(self, symbol: str) -> Optional[str]:
        """
        Get cached trend for symbol

        Returns:
            "BULLISH", "BEARISH", or None if not found
        """
        triggers = self.read_triggers()
        if not triggers or 'triggers' not in triggers:
            return None

        symbol_trigger = triggers['triggers'].get(symbol)
        if symbol_trigger:
            return symbol_trigger.get('trend')

        return None

    def print_scan_report(self, triggers: Dict[str, Dict]):
        """Print formatted scan report"""
        print("\n" + "="*70)
        print("MACRO TRIGGER SCAN REPORT")
        print("="*70)
        print(f"Scan Time:        {datetime.utcnow().isoformat()}")
        print(f"Symbols Scanned:  {self.symbols_scanned}")
        print(f"Duration:         {self.scan_duration:.2f}s")
        print("\n" + "-"*70)

        bullish = []
        bearish = []

        for symbol, data in triggers.items():
            status = "✅ BULLISH" if data['trend'] == "BULLISH" else "❌ BEARISH"
            print(
                f"\n[{symbol}] {status}")
            print(f"  Price:    ${data['current_price']:.2f}")
            print(f"  SMA 50:   ${data['sma_50']:.2f}")
            print(f"  Distance: {data['distance_pct']:+.2f}%")

            if data['trend'] == "BULLISH":
                bullish.append(symbol)
            else:
                bearish.append(symbol)

        print("\n" + "="*70)
        print(f"Summary: {len(bullish)} Bullish | {len(bearish)} Bearish")
        print(f"Bullish:  {bullish}")
        print(f"Bearish:  {bearish}")
        print("="*70 + "\n")


# Test and example
if __name__ == "__main__":
    scanner = MacroTriggerScanner()

    # Simulated daily data (last 60 days)
    np.random.seed(42)

    # Create realistic daily close data
    crwd_closes = np.cumsum(np.random.randn(60) * 2) + 190  # Start at ~190
    zm_closes = np.cumsum(np.random.randn(60) * 1) + 140    # Start at ~140
    jd_closes = np.cumsum(np.random.randn(60) * 0.5) + 60   # Start at ~60

    symbol_data = {
        'CRWD': crwd_closes,
        'ZM': zm_closes,
        'JD': jd_closes
    }

    # Scan symbols
    triggers = scanner.scan_symbols(symbol_data)

    # Write to file
    success = scanner.write_triggers_atomic(triggers)

    # Print report
    if success:
        scanner.print_scan_report(triggers)

        # Test read
        cached = scanner.read_triggers()
        print(f"Cached data: {json.dumps(cached, indent=2)}")
