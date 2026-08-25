#!/usr/bin/env python3
"""
Integration layer: Main bot checks macro_triggers.json queue for parallel signals

Usage in bot_production_final.py:
    from macro_signal_integrator import MacroSignalIntegrator

    # During entry signal evaluation:
    integrator = MacroSignalIntegrator()
    macro_signal = integrator.get_signal_for_symbol(symbol)
    if macro_signal:
        if macro_signal['confidence_score'] >= 75:
            logger.info(f"Macro signal boost: {macro_signal['reason']}")
            # Optionally boost confidence or skip based on bias
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)
MACRO_TRIGGERS_FILE = Path(__file__).parent / "macro_triggers.json"


class MacroSignalIntegrator:
    """Bridge between parallel signal channel and main bot"""

    @staticmethod
    def load_triggers() -> Dict[str, Any]:
        """Load macro_triggers.json queue"""
        if MACRO_TRIGGERS_FILE.exists():
            try:
                with open(MACRO_TRIGGERS_FILE, 'r') as f:
                    return json.load(f)
            except:
                return {"active": [], "meta": {}}
        return {"active": [], "meta": {}}

    @staticmethod
    def get_signal_for_symbol(symbol: str) -> Optional[Dict[str, Any]]:
        """
        Check if macro channel has signal for symbol.
        Returns signal dict or None.
        """
        triggers = MacroSignalIntegrator.load_triggers()

        for signal in triggers.get("active", []):
            if signal.get("symbol") == symbol:
                return signal

        return None

    @staticmethod
    def check_bias_alignment(tech_bias: str, macro_signal: Dict[str, Any]) -> bool:
        """
        Check if macro and technical signals align.
        tech_bias: "BULLISH" | "BEARISH" | "NEUTRAL"
        """
        macro_bias = macro_signal.get("bias", "NEUTRAL")

        # Exact alignment
        if tech_bias == macro_bias:
            return True

        # Neutral aligns with anything
        if tech_bias == "NEUTRAL" or macro_bias == "NEUTRAL":
            return True

        return False

    @staticmethod
    def boost_confidence(
        base_confidence: float,
        macro_signal: Dict[str, Any],
        tech_bias: str
    ) -> float:
        """
        Apply macro boost to technical confidence score.
        Returns confidence capped at 95% (always leave room for risk management)
        """
        if not macro_signal:
            return base_confidence

        macro_conf = macro_signal.get("confidence_score", 0)

        # If aligned, boost by 10-15 points
        if MacroSignalIntegrator.check_bias_alignment(tech_bias, macro_signal):
            boosted = base_confidence + 10  # Conservative boost
            return min(boosted, 95)  # Cap at 95%

        # If conflicting, reduce by 10%
        else:
            logger.warning(
                f"Bias mismatch: Tech={tech_bias}, Macro={macro_signal['bias']} "
                f"| Signal: {macro_signal.get('reason', 'unknown')}"
            )
            return base_confidence * 0.9

    @staticmethod
    def filter_by_macro(symbol: str, tech_signal_valid: bool) -> bool:
        """
        Check if macro channel wants to BLOCK this entry.
        Useful for avoiding earnings, investigations, etc.
        """
        signal = MacroSignalIntegrator.get_signal_for_symbol(symbol)

        if not signal:
            return True  # No macro signal = proceed

        # If signal says block, don't enter
        if signal.get("actionable_trigger") == False and signal.get("bias") == "BEARISH":
            logger.info(
                f"Macro channel blocks {symbol}: {signal.get('reason', 'unknown')}"
            )
            return False

        return True


# ============================================================================
# EXAMPLE USAGE IN BOT
# ============================================================================

"""
Example integration in bot_production_final.py run_cycle():

    from macro_signal_integrator import MacroSignalIntegrator

    # During entry signal evaluation:
    if entry_signal_generated:
        macro_signal = MacroSignalIntegrator.get_signal_for_symbol(symbol)

        # Option 1: Boost confidence if macro aligns
        if macro_signal:
            confidence = MacroSignalIntegrator.boost_confidence(
                base_confidence=confidence,
                macro_signal=macro_signal,
                tech_bias="BULLISH"
            )
            logger.info(f"Macro boosted confidence: {confidence:.1f}% for {symbol}")

        # Option 2: Block entry if macro says no
        if not MacroSignalIntegrator.filter_by_macro(symbol, entry_signal_generated):
            logger.warning(f"Macro channel blocked entry for {symbol}")
            continue
"""
