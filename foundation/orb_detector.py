"""
Opening Range Breakout (ORB) Detector
Tracks first 30 minutes (9:30-10:00 AM EST) for breakout conditions

Day 2 Component 6: ORB detection to skip mean-reversion on breakouts
When ADX>25 + price breaks ORB high, skip mean-reversion entries
"""

import numpy as np
import pandas as pd
from datetime import datetime, time, timedelta
import logging
from typing import Dict, Optional, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OpeningRangeBreakout:
    """
    Detects Opening Range Breakout conditions

    Purpose:
    - Track first 30 minutes (9:30-10:00 AM EST)
    - Identify high/low range during opening period
    - Detect breakouts when ADX>25 + price exceeds ORB

    Why It Matters:
    - ORB breakouts are momentum, not mean-reversion
    - Entering mean-reversion on ORB breakout = counter-trend
    - Skip entries when ADX>25 + price > ORB high (breakout detected)

    Example:
    ├─ 9:30 AM: ORB opens at $140
    ├─ 9:45 AM: ORB high = $141.50, low = $139.50
    ├─ 10:00 AM: ORB range locked ($139.50 - $141.50)
    │
    ├─ 10:30 AM: Price = $142.00, ADX = 28
    │  └─ BREAKOUT DETECTED: Price > ORB high + ADX>25
    │  └─ SKIP mean-reversion, watch momentum instead
    │
    └─ 11:00 AM: Price = $138.00
       └─ Below ORB range, normal mean-reversion applies
    """

    def __init__(self, market_open_time: str = "09:30",
                 orb_duration_minutes: int = 30,
                 adx_breakout_threshold: float = 25):
        """
        Args:
            market_open_time: Market open time HH:MM (EST)
            orb_duration_minutes: Duration of opening range (30 min = 9:30-10:00)
            adx_breakout_threshold: ADX threshold for breakout confirmation
        """
        self.market_open_time = self._parse_time(market_open_time)
        self.orb_duration_minutes = orb_duration_minutes
        self.adx_threshold = adx_breakout_threshold
        self.orb_cache = {}

    @staticmethod
    def _parse_time(time_str: str) -> time:
        """Parse HH:MM to time object"""
        parts = time_str.split(':')
        return time(int(parts[0]), int(parts[1]))

    def is_in_opening_range(self, timestamp: datetime) -> bool:
        """
        Check if timestamp is during ORB period (9:30-10:00 AM)

        Returns:
            True if timestamp is during opening range
        """
        market_open = self.market_open_time
        market_open_end = time(
            market_open.hour,
            market_open.minute + self.orb_duration_minutes
        )

        ts_time = timestamp.time()

        return market_open <= ts_time < market_open_end

    def is_after_opening_range(self, timestamp: datetime) -> bool:
        """
        Check if timestamp is after ORB period closed (after 10:00 AM)

        Returns:
            True if after ORB period
        """
        market_open = self.market_open_time
        market_open_end = time(
            market_open.hour,
            market_open.minute + self.orb_duration_minutes
        )

        ts_time = timestamp.time()

        return ts_time >= market_open_end

    def calculate_orb_range(self, orb_candles: pd.DataFrame) -> Dict:
        """
        Calculate ORB high and low from first 30-minute candles

        Args:
            orb_candles: DataFrame with 30-min OHLCV data during 9:30-10:00

        Returns:
            {
                'orb_high': float,
                'orb_low': float,
                'orb_open': float,
                'orb_range': float (high - low),
                'candle_count': int
            }
        """
        if len(orb_candles) == 0:
            logger.warning("No ORB candles provided")
            return None

        orb_high = orb_candles['High'].max()
        orb_low = orb_candles['Low'].min()
        orb_open = orb_candles['Open'].iloc[0]
        orb_range = orb_high - orb_low

        result = {
            'orb_high': orb_high,
            'orb_low': orb_low,
            'orb_open': orb_open,
            'orb_range': orb_range,
            'candle_count': len(orb_candles)
        }

        logger.info(
            f"ORB Range calculated: High=${orb_high:.2f} | "
            f"Low=${orb_low:.2f} | Range=${orb_range:.2f} ({len(orb_candles)} candles)"
        )

        return result

    def detect_orb_breakout(self, current_price: float,
                           adx: float,
                           orb_range: Dict) -> Tuple[bool, str]:
        """
        Detect if price has broken out of ORB range

        Breakout confirmed when:
        1. Price > ORB high OR Price < ORB low
        2. ADX > threshold (trend strength)

        Args:
            current_price: Current price
            adx: Current ADX value
            orb_range: ORB range dict from calculate_orb_range()

        Returns:
            (is_breakout: bool, breakout_type: str)
            breakout_type: "bullish", "bearish", or "none"
        """
        if not orb_range:
            return False, "none"

        orb_high = orb_range['orb_high']
        orb_low = orb_range['orb_low']

        # Breakout confirmation requires ADX > threshold
        if adx <= self.adx_threshold:
            return False, "none"

        # Check bullish breakout
        if current_price > orb_high:
            logger.info(
                f"✅ BULLISH ORB BREAKOUT: Price ${current_price:.2f} > "
                f"ORB High ${orb_high:.2f} (ADX: {adx:.1f})"
            )
            return True, "bullish"

        # Check bearish breakout
        if current_price < orb_low:
            logger.info(
                f"✅ BEARISH ORB BREAKOUT: Price ${current_price:.2f} < "
                f"ORB Low ${orb_low:.2f} (ADX: {adx:.1f})"
            )
            return True, "bearish"

        return False, "none"

    def should_skip_mean_reversion(self, current_price: float,
                                  adx: float,
                                  orb_range: Dict) -> bool:
        """
        Determine if mean-reversion entry should be skipped

        Skip when:
        - ORB breakout detected (price > ORB high + ADX > 25)
        - This is momentum trade, not mean-reversion

        Returns:
            True if entry should be skipped (breakout detected)
            False if normal mean-reversion logic applies
        """
        if not orb_range:
            return False

        is_breakout, breakout_type = self.detect_orb_breakout(
            current_price, adx, orb_range
        )

        if is_breakout and breakout_type == "bullish":
            logger.warning(
                f"⛔ SKIP MEAN-REVERSION: Bullish ORB breakout detected. "
                f"This is momentum, not mean-reversion."
            )
            return True

        if is_breakout and breakout_type == "bearish":
            logger.warning(
                f"⛔ SKIP MEAN-REVERSION: Bearish ORB breakout detected. "
                f"Market in breakout mode, skip counter-trend entries."
            )
            return True

        return False

    def print_orb_analysis(self, symbol: str, current_price: float,
                          adx: float, orb_range: Dict):
        """Print ORB analysis visualization"""
        if not orb_range:
            print(f"[{symbol}] No ORB data available")
            return

        print("\n" + "="*70)
        print(f"OPENING RANGE BREAKOUT (ORB) ANALYSIS - {symbol}")
        print("="*70)

        orb_high = orb_range['orb_high']
        orb_low = orb_range['orb_low']
        orb_range_size = orb_range['orb_range']

        print(f"\nCurrent Price:    ${current_price:.2f}")
        print(f"ADX:              {adx:.1f}")
        print(f"\nORB Range (9:30-10:00 AM):")
        print(f"  High:           ${orb_high:.2f}")
        print(f"  Low:            ${orb_low:.2f}")
        print(f"  Range:          ${orb_range_size:.2f}")
        print(f"  Candles:        {orb_range['candle_count']}")

        # Visualization
        print("\nPrice Position:")
        if current_price > orb_high:
            print(f"  ↑ Above ORB High (BREAKOUT ZONE)")
            if adx > self.adx_threshold:
                print(f"  ⚠️  ADX={adx:.1f} > {self.adx_threshold} → BREAKOUT CONFIRMED")
            else:
                print(f"  ⚠️  ADX={adx:.1f} < {self.adx_threshold} → Weak breakout")
        elif current_price < orb_low:
            print(f"  ↓ Below ORB Low (BREAKDOWN ZONE)")
            if adx > self.adx_threshold:
                print(f"  ⚠️  ADX={adx:.1f} > {self.adx_threshold} → BREAKDOWN CONFIRMED")
            else:
                print(f"  ⚠️  ADX={adx:.1f} < {self.adx_threshold} → Weak breakdown")
        else:
            print(f"  ↔ Within ORB Range (NORMAL TRADING)")

        # Skip decision
        skip = self.should_skip_mean_reversion(current_price, adx, orb_range)
        if skip:
            print(f"\n❌ SKIP MEAN-REVERSION ENTRY (Breakout detected)")
        else:
            print(f"\n✅ ALLOW MEAN-REVERSION ENTRY (ORB filter passed)")

        print("="*70 + "\n")


# Test and example
if __name__ == "__main__":
    detector = OpeningRangeBreakout()

    # Simulate ORB period candles (9:30-10:00 AM)
    orb_data = pd.DataFrame({
        'Time': [
            datetime(2026, 8, 24, 9, 30),
            datetime(2026, 8, 24, 9, 45),
            datetime(2026, 8, 24, 10, 0)
        ],
        'Open': [140.00, 140.50, 141.00],
        'High': [140.80, 141.50, 141.20],
        'Low': [139.80, 140.20, 140.80],
        'Close': [140.50, 141.00, 141.10],
        'Volume': [1000000, 1200000, 900000]
    })

    # Calculate ORB range
    orb_range = detector.calculate_orb_range(orb_data)
    print(f"\nORB Range: {orb_range}")

    # Test breakout scenarios
    print("\n--- Scenario 1: Bullish Breakout (Price > ORB High, ADX > 25) ---")
    detector.print_orb_analysis("ZM", current_price=142.00, adx=28, orb_range=orb_range)

    print("\n--- Scenario 2: Within Range (Normal Trading) ---")
    detector.print_orb_analysis("ZM", current_price=140.50, adx=22, orb_range=orb_range)

    print("\n--- Scenario 3: Weak Breakout (Price > ORB High, but ADX < 25) ---")
    detector.print_orb_analysis("ZM", current_price=142.00, adx=18, orb_range=orb_range)
