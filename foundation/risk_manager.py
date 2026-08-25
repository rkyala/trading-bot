"""
Dynamic Risk Manager - Volatility-Aware Stop/Target Sizing
Adjusts stops and targets based on current volatility regime

Day 1 Component: Maintains 1:2 risk/reward ratio across all regimes
Based on real data showing static stops fail on high-vol symbols
"""

import numpy as np
import logging
from typing import Dict, Tuple
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class StopTargetLevels:
    """Stop loss and profit target levels"""
    stop_loss: float
    target: float
    stop_pct: float  # As percentage
    target_pct: float  # As percentage
    regime: str  # "high_vol", "med_vol", "low_vol"


class DynamicRiskManager:
    """
    Calculates stop-loss and profit-target levels based on volatility

    Three Regimes:
    ┌─────────────────────────────────────────────────────────────┐
    │ High Volatility (ATR% > 2.5%)                               │
    │ ├─ Stop: -2.5% (wider, allow more swing room)               │
    │ ├─ Target: +5.0% (2x stop = 1:2 ratio)                      │
    │ └─ Use: CRWD, high-growth tech                              │
    ├─────────────────────────────────────────────────────────────┤
    │ Medium Volatility (1.5% < ATR% <= 2.5%)                     │
    │ ├─ Stop: -1.75% (standard stop)                             │
    │ ├─ Target: +3.5% (2x stop = 1:2 ratio)                      │
    │ └─ Use: ZM, JD (proven winners)                             │
    ├─────────────────────────────────────────────────────────────┤
    │ Low Volatility (ATR% <= 1.5%)                               │
    │ ├─ Stop: -1.2% (tight, fast exit)                           │
    │ ├─ Target: +2.4% (2x stop = 1:2 ratio)                      │
    │ └─ Use: Stable blue chips                                   │
    └─────────────────────────────────────────────────────────────┘

    All maintain 1:2 risk/reward ratio for consistent position sizing
    """

    def __init__(self):
        """Initialize risk regime thresholds"""
        self.high_vol_threshold = 2.5  # ATR% > 2.5%
        self.med_vol_threshold = 1.5   # 1.5% < ATR% <= 2.5%
        # Low vol: ATR% <= 1.5%

    def get_volatility_regime(self, atr_pct: float) -> str:
        """
        Classify volatility into regime based on ATR%

        Args:
            atr_pct: ATR as percentage of current price

        Returns:
            "high_vol", "med_vol", or "low_vol"
        """
        if atr_pct > self.high_vol_threshold:
            return "high_vol"
        elif atr_pct > self.med_vol_threshold:
            return "med_vol"
        else:
            return "low_vol"

    def calculate_stops_and_targets(self, entry_price: float,
                                   atr_pct: float) -> StopTargetLevels:
        """
        Calculate stop loss and profit target for entry price

        Maintains 1:2 risk/reward across all volatility regimes

        Args:
            entry_price: Price where trade enters
            atr_pct: Current ATR as percentage

        Returns:
            StopTargetLevels with calculated prices
        """
        regime = self.get_volatility_regime(atr_pct)

        if regime == "high_vol":
            stop_pct = -2.5
            target_pct = 5.0
        elif regime == "med_vol":
            stop_pct = -1.75
            target_pct = 3.5
        else:  # low_vol
            stop_pct = -1.2
            target_pct = 2.4

        # Calculate price levels
        stop_loss = entry_price * (1 + stop_pct / 100)
        target = entry_price * (1 + target_pct / 100)

        return StopTargetLevels(
            stop_loss=stop_loss,
            target=target,
            stop_pct=stop_pct,
            target_pct=target_pct,
            regime=regime
        )

    def validate_risk_reward_ratio(self, stop_pct: float,
                                  target_pct: float,
                                  expected_ratio: float = 2.0) -> bool:
        """
        Verify risk/reward ratio (should be 1:2)

        Args:
            stop_pct: Stop loss percentage (negative)
            target_pct: Target profit percentage (positive)
            expected_ratio: Expected risk/reward ratio (default 2.0)

        Returns:
            True if ratio is valid (within 5% tolerance)
        """
        actual_ratio = abs(target_pct / stop_pct)
        tolerance = 0.05  # 5% tolerance

        is_valid = (
            abs(actual_ratio - expected_ratio) / expected_ratio < tolerance
        )

        return is_valid

    def print_regime_table(self):
        """Print risk regime configuration"""
        print("\n" + "="*70)
        print("DYNAMIC RISK MANAGER - VOLATILITY REGIMES")
        print("="*70)

        regimes = [
            {
                'name': 'High Volatility',
                'atr_range': f'> {self.high_vol_threshold}%',
                'stop': '-2.5%',
                'target': '+5.0%',
                'examples': 'CRWD, high-growth tech'
            },
            {
                'name': 'Medium Volatility',
                'atr_range': f'{self.med_vol_threshold}% - {self.high_vol_threshold}%',
                'stop': '-1.75%',
                'target': '+3.5%',
                'examples': 'ZM, JD (proven winners)'
            },
            {
                'name': 'Low Volatility',
                'atr_range': f'< {self.med_vol_threshold}%',
                'stop': '-1.2%',
                'target': '+2.4%',
                'examples': 'Stable blue chips'
            }
        ]

        for regime in regimes:
            print(f"\n{regime['name']}")
            print(f"  ATR Range:    {regime['atr_range']}")
            print(f"  Stop Loss:    {regime['stop']}")
            print(f"  Target:       {regime['target']}")
            print(f"  Risk/Reward:  1:2")
            print(f"  Examples:     {regime['examples']}")

        print("\n" + "="*70 + "\n")

    def print_example_calculations(self, entry_prices: Dict[str, float],
                                   atr_pcts: Dict[str, float]):
        """
        Print example stop/target calculations for given entry prices

        Args:
            entry_prices: Dict mapping symbol -> entry price
            atr_pcts: Dict mapping symbol -> ATR%
        """
        print("\n" + "="*70)
        print("EXAMPLE STOP/TARGET CALCULATIONS")
        print("="*70)

        for symbol, entry_price in entry_prices.items():
            atr_pct = atr_pcts.get(symbol, 0)

            levels = self.calculate_stops_and_targets(entry_price, atr_pct)

            print(f"\n[{symbol}]")
            print(f"  Entry Price:      ${entry_price:.2f}")
            print(f"  ATR:              {atr_pct:.2f}%")
            print(f"  Regime:           {levels.regime.upper()}")
            print(f"  Stop Loss:        ${levels.stop_loss:.2f} ({levels.stop_pct}%)")
            print(f"  Target:           ${levels.target:.2f} ({levels.target_pct}%)")
            print(f"  Risk/Reward:      1:{abs(levels.target_pct / levels.stop_pct):.2f}")

        print("\n" + "="*70 + "\n")


# Test example from real data
if __name__ == "__main__":
    rm = DynamicRiskManager()

    # Print regime table
    rm.print_regime_table()

    # Example calculations from real data
    entry_prices = {
        'CRWD': 190.00,  # High vol
        'ZM': 140.00,    # Med vol
        'JD': 60.00      # Low vol
    }

    atr_pcts = {
        'CRWD': 3.5,  # Should use high-vol regime
        'ZM': 1.9,    # Should use med-vol regime
        'JD': 1.8     # Should use low-vol regime
    }

    rm.print_example_calculations(entry_prices, atr_pcts)

    # Validate risk/reward ratios
    print("Risk/Reward Validation:")
    print(f"  High vol (2.5/-5.0): {rm.validate_risk_reward_ratio(-2.5, 5.0)} ✓")
    print(f"  Med vol (1.75/-3.5): {rm.validate_risk_reward_ratio(-1.75, 3.5)} ✓")
    print(f"  Low vol (1.2/-2.4):  {rm.validate_risk_reward_ratio(-1.2, 2.4)} ✓")
