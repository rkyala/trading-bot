#!/usr/bin/env python3
"""
Phase 2.5: Flow + Technical Confluence Framework
Unusual Whales sweeps ONLY trigger when technical layers align

Never execute on flow alone. Require:
1. Flow Signal (Unusual Whales)
2. Price Structure (Fib + VWAP + GEX)
3. Trend Filter (ADX > 25)
4. Momentum Timing (Stochastic divergence)
"""

import json
import numpy as np
import pandas as pd
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional

# ============================================================================
# LAYER 1: PRICE STRUCTURE (Fibonacci, VWAP, GEX)
# ============================================================================

@dataclass
class PriceStructure:
    """Technical price levels that define confluence zones"""

    symbol: str
    current_price: float
    swing_high: float
    swing_low: float
    anchored_vwap: float
    gamma_flip_level: float

    def get_fibonacci_levels(self) -> Dict[str, float]:
        """Calculate Fib retracement from swing high to low"""
        diff = self.swing_high - self.swing_low

        return {
            "0%": self.swing_high,
            "23.6%": self.swing_high - diff * 0.236,
            "38.2%": self.swing_high - diff * 0.382,
            "50.0%": self.swing_high - diff * 0.5,
            "61.8%": self.swing_high - diff * 0.618,
            "100%": self.swing_low
        }

    def check_structure_alignment(self) -> Dict:
        """
        Check if price is at technical confluence:
        ✓ Above Anchored VWAP
        ✓ Above Gamma Flip level
        ✓ Near Fib retracement zones (38.2% / 61.8%)
        """
        fibs = self.get_fibonacci_levels()

        checks = {
            "above_vwap": self.current_price > self.anchored_vwap,
            "above_gamma_flip": self.current_price > self.gamma_flip_level,
            "near_fib_382": abs(self.current_price - fibs["38.2%"]) / fibs["38.2%"] < 0.01,
            "near_fib_618": abs(self.current_price - fibs["61.8%"]) / fibs["61.8%"] < 0.01,
            "dark_pool_support": self.current_price > self.swing_low * 1.02  # Within 2% of low
        }

        alignment_score = sum(checks.values()) / len(checks) * 100

        return {
            "structure_valid": alignment_score >= 60,  # Need 60%+ confluence
            "alignment_score": alignment_score,
            "checks": checks,
            "fibonacci_levels": fibs
        }


# ============================================================================
# LAYER 2: TREND & MOMENTUM (ADX, Stochastic, Divergence)
# ============================================================================

@dataclass
class TrendMomentum:
    """Momentum indicators for timing confirmation"""

    adx: float  # Average Directional Index (14)
    stochastic_k: float  # Stochastic K-line
    stochastic_d: float  # Stochastic D-line
    rsi: float  # RSI (14)
    price_low: float  # For divergence detection
    momentum_low: float  # Stochastic/RSI low point

    def check_trend_strength(self) -> Dict:
        """
        ADX > 25 = Strong trend environment
        ADX 20-25 = Emerging trend
        ADX < 20 = Choppy/ranging
        """
        return {
            "strong_trend": self.adx > 25,
            "adx_value": self.adx,
            "recommendation": (
                "Strong trend" if self.adx > 25 else
                "Emerging trend" if self.adx > 20 else
                "Low trend - risky"
            )
        }

    def check_momentum_timing(self) -> Dict:
        """
        Stochastic < 20 = Oversold
        Look for bullish divergence:
        - Price makes lower low
        - Stochastic makes higher low
        """
        oversold = self.stochastic_k < 20
        stochastic_crossover = self.stochastic_k > self.stochastic_d

        return {
            "oversold": oversold,
            "stochastic_k": self.stochastic_k,
            "crossover_up": stochastic_crossover,
            "bullish_divergence_potential": oversold and stochastic_crossover
        }


# ============================================================================
# LAYER 3: VOLUME & PARTICIPATION (Dark Pools, Institutional Flow)
# ============================================================================

@dataclass
class VolumeParticipation:
    """Institutional execution footprint"""

    unusual_whales_premium: float  # Dollar amount of sweep
    unusual_whales_ratio: float  # Volume / Open Interest ratio
    dark_pool_volume: float  # Off-exchange volume
    total_volume: float  # On-exchange volume
    institutional_threshold: float = 500000  # $500K minimum for institutional

    def validate_flow(self) -> Dict:
        """
        Verify Unusual Whales alert is truly institutional:
        ✓ Premium > $500K
        ✓ Vol/OI ratio > 3x
        ✓ Execution at ask (bullish) or bid (bearish)
        """
        is_institutional = self.unusual_whales_premium > self.institutional_threshold
        is_sweep_ratio = self.unusual_whales_ratio > 3.0
        dark_pool_participation = self.dark_pool_volume / (self.total_volume + 1) > 0.15

        return {
            "institutional_size": is_institutional,
            "sweep_confirmed": is_sweep_ratio,
            "dark_pool_footprint": dark_pool_participation,
            "flow_valid": is_institutional and is_sweep_ratio
        }


# ============================================================================
# CONFLUENCE FRAMEWORK: All Layers Combined
# ============================================================================

class ConfluenceFramework:
    """
    Execute ONLY when all four layers align.
    Never trade on flow alone.
    """

    def __init__(self):
        self.min_alignment_threshold = 0.70  # 70% confluence required

    def evaluate_setup(
        self,
        symbol: str,
        flow_data: Dict,
        price_structure: PriceStructure,
        trend_momentum: TrendMomentum,
        volume_participation: VolumeParticipation
    ) -> Dict:
        """
        Evaluate complete confluence:
        Flow + Structure + Trend + Volume
        """

        # Layer 1: Flow
        flow_valid = volume_participation.validate_flow()

        # Layer 2: Price Structure
        structure_valid = price_structure.check_structure_alignment()

        # Layer 3: Trend Strength
        trend_valid = trend_momentum.check_trend_strength()

        # Layer 4: Momentum Timing
        momentum_valid = trend_momentum.check_momentum_timing()

        # Calculate overall confluence score
        confluence_checks = {
            "flow_institutional": flow_valid.get("flow_valid", False),
            "price_structure": structure_valid.get("structure_valid", False),
            "trend_strong": trend_valid.get("strong_trend", False),
            "momentum_bullish": momentum_valid.get("bullish_divergence_potential", False)
        }

        # Count passing checks (need 3/4 minimum = 75%)
        passing_checks = sum(confluence_checks.values())
        confluence_score = passing_checks / len(confluence_checks)

        # Execute ONLY if high confluence
        should_execute = confluence_score >= 0.75

        return {
            "symbol": symbol,
            "should_execute": should_execute,
            "confluence_score": confluence_score * 100,
            "passing_checks": passing_checks,
            "total_checks": len(confluence_checks),
            "checks": confluence_checks,
            "reason": self._generate_reason(confluence_checks, confluence_score),
            "details": {
                "flow": flow_valid,
                "price_structure": structure_valid,
                "trend": trend_valid,
                "momentum": momentum_valid
            }
        }

    def _generate_reason(self, checks: Dict, score: float) -> str:
        """Generate human-readable execution reason"""
        if score >= 0.75:
            return "HIGH CONFLUENCE: All technical layers aligned with institutional flow"
        elif score >= 0.50:
            return "PARTIAL CONFLUENCE: Some layers missing - wait for better setup"
        else:
            return "LOW CONFLUENCE: Flow signal not confirmed by technicals - SKIP"


# ============================================================================
# IMPLEMENTATION: Unusual Whales + Confluence
# ============================================================================

def phase2_5_execution_with_confluence(
    unusual_whales_alert: Dict,
    market_data: Dict
) -> Dict:
    """
    Phase 2.5 Integration:
    1. Detect sweep via Unusual Whales
    2. Verify with confluence framework
    3. Execute only if all layers align
    """

    symbol = unusual_whales_alert["symbol"]

    # Build Layer 1: Price Structure
    price_structure = PriceStructure(
        symbol=symbol,
        current_price=market_data["price"],
        swing_high=market_data["swing_high"],
        swing_low=market_data["swing_low"],
        anchored_vwap=market_data["anchored_vwap"],
        gamma_flip_level=market_data["gamma_flip_level"]
    )

    # Build Layer 2: Trend & Momentum
    trend_momentum = TrendMomentum(
        adx=market_data["adx"],
        stochastic_k=market_data["stoch_k"],
        stochastic_d=market_data["stoch_d"],
        rsi=market_data["rsi"],
        price_low=market_data["swing_low"],
        momentum_low=market_data["stoch_low"]
    )

    # Build Layer 3: Volume & Participation
    volume_participation = VolumeParticipation(
        unusual_whales_premium=unusual_whales_alert["premium"],
        unusual_whales_ratio=unusual_whales_alert["vol_oi_ratio"],
        dark_pool_volume=market_data["dark_pool_volume"],
        total_volume=market_data["total_volume"]
    )

    # Evaluate Confluence
    framework = ConfluenceFramework()
    evaluation = framework.evaluate_setup(
        symbol=symbol,
        flow_data=unusual_whales_alert,
        price_structure=price_structure,
        trend_momentum=trend_momentum,
        volume_participation=volume_participation
    )

    return evaluation


# ============================================================================
# EXAMPLE: High-Probability Setup
# ============================================================================

def example_nvda_setup():
    """
    Example from documentation:
    NVDA $1.8M call sweep at $128.50
    All confluence layers aligned ✓
    """

    unusual_whales_alert = {
        "symbol": "NVDA",
        "side": "CALL",
        "premium": 1800000,  # $1.8M
        "vol_oi_ratio": 4.17,  # 4.17x sweep
        "execution": "BUY_AT_ASK"
    }

    market_data = {
        "price": 128.50,  # At 61.8% Fib retracement ✓
        "swing_high": 145.00,
        "swing_low": 110.00,
        "anchored_vwap": 127.10,  # Price above VWAP ✓
        "gamma_flip_level": 125.00,  # Price above Gamma Flip ✓
        "adx": 28.5,  # Strong trend ✓
        "stoch_k": 22.0,  # Oversold
        "stoch_d": 18.5,  # Crossover signal ✓
        "rsi": 35.0,  # Oversold
        "swing_low": 110.00,
        "stoch_low": 12.0,  # Divergence signal ✓
        "dark_pool_volume": 45000,
        "total_volume": 280000
    }

    # Evaluate
    result = phase2_5_execution_with_confluence(unusual_whales_alert, market_data)

    print("\n" + "="*100)
    print("PHASE 2.5 CONFLUENCE FRAMEWORK: Example NVDA Setup")
    print("="*100)
    print(f"\n[UNUSUAL WHALES ALERT]")
    print(f"  Symbol: {unusual_whales_alert['symbol']}")
    print(f"  Premium: ${unusual_whales_alert['premium']:,.0f}")
    print(f"  Vol/OI Ratio: {unusual_whales_alert['vol_oi_ratio']:.2f}x")

    print(f"\n[CONFLUENCE EVALUATION]")
    print(f"  Overall Score: {result['confluence_score']:.0f}%")
    print(f"  Checks Passed: {result['passing_checks']}/{result['total_checks']}")
    print(f"  Decision: {'✅ EXECUTE' if result['should_execute'] else '❌ SKIP'}")

    print(f"\n[TECHNICAL VERIFICATION]")
    for check_name, passed in result['checks'].items():
        status = "✓" if passed else "✗"
        print(f"  {status} {check_name.replace('_', ' ').title()}: {passed}")

    print(f"\n[REASON]")
    print(f"  {result['reason']}")

    if result['should_execute']:
        print(f"\n[EXECUTION]")
        print(f"  Stop Loss: Below Fib 61.8% level (${market_data['anchored_vwap'] - 2:.2f})")
        print(f"  Target: Above Fib 38.2% level (${(market_data['swing_high'] - market_data['swing_low']) * 0.382 + market_data['swing_low']:.2f})")
        print(f"  Position Size: 0.625% of account ($62.50 for $10K)")

    print("\n" + "="*100 + "\n")

    return result


# ============================================================================
# GOLDEN RULE: Don't Stack Correlated Indicators
# ============================================================================

CONFLUENCE_ANTI_PATTERNS = """
❌ WRONG (Correlated indicators):
├─ RSI + MACD + Stochastic (all measure rate of change)
├─ SMA(20) + SMA(50) + EMA(12) (all moving averages)
└─ Momentum + Rate of Change + CCI (all measuring same thing)

✅ CORRECT (Non-correlated layers):
├─ Flow Layer: Unusual Whales (institutional behavior)
├─ Structure Layer: Fibonacci + VWAP + GEX (price levels)
├─ Trend Layer: ADX (trend strength, not direction)
└─ Momentum Layer: Stochastic (overbought/oversold timing)

Key Insight:
Flow (WHAT institutions are doing)
+ Structure (WHERE price is)
+ Trend (IS there a trend?)
+ Momentum (WHEN to enter?)
= High-probability setup
"""

if __name__ == "__main__":
    # Run example
    example_nvda_setup()

    # Print anti-patterns
    print(CONFLUENCE_ANTI_PATTERNS)
