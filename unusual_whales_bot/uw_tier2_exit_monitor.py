#!/usr/bin/env python3
"""
Tier 2 Exit Monitor: 4 Options-Based Exit Rules
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Rule #5: Flow Exhaustion (no fresh sweeps for 45 min → exit)
Rule #1: Put/Call Flip (conviction reversal → exit)
Rule #2: Dark Pool Reversal (institutions dumping → exit)
Rule #6: Market Tide Flip (macro sentiment flip → exit)

All rules run in parallel, exit on FIRST trigger.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import time

logger = logging.getLogger(__name__)


@dataclass
class ExitSignal:
    """Exit signal with reason and timestamp"""
    triggered: bool = False
    reason: str = ""  # "flow_exhaustion", "put_call_flip", "dark_pool", "market_tide"
    confidence: float = 0.0  # 0-1.0
    timestamp: float = field(default_factory=time.time)
    details: Dict = field(default_factory=dict)


@dataclass
class PositionMonitor:
    """Track a position's exit signals"""
    symbol: str
    entry_time: float
    entry_direction: str  # "CALL" or "PUT"
    last_flow_check: float = field(default_factory=time.time)
    last_pc_check: float = field(default_factory=time.time)
    last_dp_check: float = field(default_factory=time.time)
    last_tide_check: float = field(default_factory=time.time)
    flow_history: List[Dict] = field(default_factory=list)
    exit_signal: Optional[ExitSignal] = None


class Tier2ExitMonitor:
    """Monitor 4 options-based exit rules in parallel"""

    def __init__(self, api_client):
        from uw_config import EXIT_RULES_CONFIG
        self.cfg = EXIT_RULES_CONFIG
        self.api_client = api_client
        self.positions: Dict[str, PositionMonitor] = {}
        self.market_tide_cache: Dict = {}
        self.market_tide_update_time: float = 0
        self.tide_cache_ttl = 180  # 3 min cache for market tide

    async def check_all_exits(self, positions: Dict) -> Dict[str, ExitSignal]:
        """
        Check all positions for exit signals across 4 rules.

        Returns: {symbol: ExitSignal} for positions that should exit
        """
        exit_signals = {}

        for symbol, position in positions.items():
            # Create position monitor if new
            if symbol not in self.positions:
                self.positions[symbol] = PositionMonitor(
                    symbol=symbol,
                    entry_time=position.get("entry_time", time.time()),
                    entry_direction=position.get("entry_direction", "CALL")
                )

            monitor = self.positions[symbol]

            # An exit rule must not close a trade the entry rules just opened.
            min_hold = self.cfg.get("min_hold_minutes_before_exit", 20)
            age_min = (time.time() - monitor.entry_time) / 60.0
            if age_min < min_hold:
                logger.debug(f"{symbol}: {age_min:.0f}min old, below {min_hold}min Tier 2 floor")
                continue

            # Check all 4 rules in parallel
            signals = await asyncio.gather(
                self._check_flow_exhaustion(symbol, monitor),
                self._check_put_call_flip(symbol, monitor),
                self._check_dark_pool_reversal(symbol, monitor),
                self._check_market_tide_flip(symbol, monitor),
                return_exceptions=True
            )

            # Find first triggered signal
            for signal in signals:
                if isinstance(signal, ExitSignal) and signal.triggered:
                    exit_signals[symbol] = signal
                    monitor.exit_signal = signal
                    logger.info(f"✅ EXIT SIGNAL: {symbol} - {signal.reason} (confidence: {signal.confidence:.0%})")
                    break

        return exit_signals

    async def _check_flow_exhaustion(self, symbol: str, monitor: PositionMonitor) -> ExitSignal:
        """
        Rule #5: Flow Exhaustion
        No fresh sweeps for 45 minutes = signal is exhausted
        """
        signal = ExitSignal()

        try:
            # Check every 5 minutes
            now = time.time()
            if now - monitor.last_flow_check < 300:  # 5 min
                return signal

            monitor.last_flow_check = now

            # Fetch recent flow on this symbol
            flow_data = await self.api_client.get_symbol_flow_recent(symbol)

            if not flow_data:
                return signal

            # Check if any flows in last 45 minutes
            cutoff_time = now - (45 * 60)  # 45 min ago
            recent_flows = [
                f for f in flow_data
                if f.get("timestamp", 0) > cutoff_time
            ]

            # LOGIC FIX: the previous version assigned monitor.flow_history =
            # recent_flows and THEN tested `len(recent_flows)==0 and
            # len(monitor.flow_history)>0`. Both can never hold at once, so the
            # rule could not fire even with working data. Capture the prior
            # history before overwriting it.
            had_flow_before = len(monitor.flow_history) > 0
            monitor.flow_history = recent_flows

            # Exhaustion means we HAD flow and it has now stopped.
            if len(recent_flows) == 0 and had_flow_before:
                signal.triggered = True
                signal.reason = "flow_exhaustion"
                signal.confidence = 0.85  # High confidence
                signal.details = {"minutes_since_last_flow": 45}
                logger.warning(f"⚠️ Flow Exhaustion on {symbol}: No activity for 45+ min")

        except Exception as e:
            logger.error(f"❌ Flow exhaustion check error on {symbol}: {e}")

        return signal

    async def _check_put_call_flip(self, symbol: str, monitor: PositionMonitor) -> ExitSignal:
        """
        Rule #1: Put/Call Flip
        Conviction reverses (puts > calls or calls > puts) = exit
        """
        signal = ExitSignal()

        try:
            # Check every 2 minutes
            now = time.time()
            if now - monitor.last_pc_check < 120:  # 2 min
                return signal

            monitor.last_pc_check = now

            # Fetch net premium ticks
            net_prem = await self.api_client.get_net_premium_ticks(symbol)

            if not net_prem:
                return signal

            net_calls = net_prem.get("net_calls", 0)
            net_puts = net_prem.get("net_puts", 0)

            # Determine current conviction
            if net_calls + net_puts == 0:
                return signal

            put_call_ratio = net_puts / (net_calls + net_puts)

            # Check for flip
            if monitor.entry_direction == "CALL":
                # We're bullish, check if it flipped bearish
                if put_call_ratio > 0.55:  # More puts than calls (flipped)
                    signal.triggered = True
                    signal.reason = "put_call_flip"
                    signal.confidence = min(0.9, put_call_ratio)
                    signal.details = {
                        "put_call_ratio": put_call_ratio,
                        "net_calls": net_calls,
                        "net_puts": net_puts
                    }
                    logger.warning(f"⚠️ Put/Call Flip on {symbol}: {put_call_ratio:.1%} puts (entry was bullish)")

            elif monitor.entry_direction == "PUT":
                # We're bearish, check if it flipped bullish
                if put_call_ratio < 0.45:  # More calls than puts (flipped)
                    signal.triggered = True
                    signal.reason = "put_call_flip"
                    signal.confidence = min(0.9, 1 - put_call_ratio)
                    signal.details = {
                        "put_call_ratio": put_call_ratio,
                        "net_calls": net_calls,
                        "net_puts": net_puts
                    }
                    logger.warning(f"⚠️ Put/Call Flip on {symbol}: {1-put_call_ratio:.1%} calls (entry was bearish)")

        except Exception as e:
            logger.error(f"❌ Put/Call flip check error on {symbol}: {e}")

        return signal

    async def _check_dark_pool_reversal(self, symbol: str, monitor: PositionMonitor) -> ExitSignal:
        """
        Rule #2: Dark Pool Reversal
        Institutions dumping ($1M+ on sell side) = exit
        """
        signal = ExitSignal()

        try:
            # Check every 1 minute
            now = time.time()
            if now - monitor.last_dp_check < 60:  # 1 min
                return signal

            monitor.last_dp_check = now

            # Fetch dark pool volume
            dp_data = await self.api_client.get_dark_pool_volume(symbol)

            if not dp_data:
                return signal

            side = dp_data.get("side", "").upper()
            notional = dp_data.get("notional_value", 0)

            # Check for large dumps
            if monitor.entry_direction == "CALL":
                # We're bullish, check for sells
                if side == "SELL" and notional > 1_000_000:
                    signal.triggered = True
                    signal.reason = "dark_pool_reversal"
                    signal.confidence = min(0.95, notional / 5_000_000)  # Higher confidence for bigger dumps
                    signal.details = {
                        "dark_pool_side": side,
                        "notional_value": notional
                    }
                    logger.warning(f"⚠️ Dark Pool Dump on {symbol}: ${notional/1e6:.1f}M sell (institutions leaving)")

            elif monitor.entry_direction == "PUT":
                # We're bearish, check for buys
                if side == "BUY" and notional > 1_000_000:
                    signal.triggered = True
                    signal.reason = "dark_pool_reversal"
                    signal.confidence = min(0.95, notional / 5_000_000)
                    signal.details = {
                        "dark_pool_side": side,
                        "notional_value": notional
                    }
                    logger.warning(f"⚠️ Dark Pool Reversal on {symbol}: ${notional/1e6:.1f}M buy (institutions covering)")

        except Exception as e:
            logger.error(f"❌ Dark pool check error on {symbol}: {e}")

        return signal

    async def _check_market_tide_flip(self, symbol: str, monitor: PositionMonitor) -> ExitSignal:
        """
        Rule #6: Market Tide Flip
        Macro sentiment reverses (bullish to bearish or vice versa) = exit
        """
        signal = ExitSignal()

        try:
            # Check every 3 minutes (shared cache)
            now = time.time()
            if now - monitor.last_tide_check < 180 and self.market_tide_cache:  # 3 min
                tide_data = self.market_tide_cache
            else:
                monitor.last_tide_check = now
                tide_data = await self.api_client.get_market_tide()
                if tide_data:
                    self.market_tide_cache = tide_data
                    self.market_tide_update_time = now

            if not tide_data:
                return signal

            bullish_ratio = tide_data.get("bullish_ratio", 0.5)

            # Check for flip
            flip_threshold = self.cfg.get("market_tide_flip_threshold", 0.30)

            if monitor.entry_direction == "CALL":
                # We're bullish, check if market flipped decisively bearish
                if bullish_ratio < flip_threshold:
                    signal.triggered = True
                    signal.reason = "market_tide_flip"
                    signal.confidence = min(0.9, 0.5 - bullish_ratio + 0.5)  # Higher for more extreme flips
                    signal.details = {
                        "bullish_ratio": bullish_ratio,
                        "market_sentiment": "BEARISH" if bullish_ratio < 0.5 else "BULLISH"
                    }
                    logger.warning(f"⚠️ Market Tide Flip on {symbol}: {bullish_ratio:.1%} bullish (macro headwind)")

            elif monitor.entry_direction == "PUT":
                # We're bearish, check if market flipped decisively bullish
                if bullish_ratio > (1.0 - flip_threshold):
                    signal.triggered = True
                    signal.reason = "market_tide_flip"
                    signal.confidence = min(0.9, bullish_ratio - 0.5 + 0.5)
                    signal.details = {
                        "bullish_ratio": bullish_ratio,
                        "market_sentiment": "BEARISH" if bullish_ratio < 0.5 else "BULLISH"
                    }
                    logger.warning(f"⚠️ Market Tide Flip on {symbol}: {bullish_ratio:.1%} bullish (macro headwind)")

        except Exception as e:
            logger.error(f"❌ Market tide check error on {symbol}: {e}")

        return signal

    def cleanup_position(self, symbol: str) -> None:
        """Remove position from monitoring"""
        if symbol in self.positions:
            del self.positions[symbol]
            logger.info(f"📭 Cleanup: {symbol} removed from exit monitor")


# Async wrapper for sync calling
async def async_check_all_exits(monitor: Tier2ExitMonitor, positions: Dict) -> Dict[str, ExitSignal]:
    """Async wrapper for exit checking"""
    return await monitor.check_all_exits(positions)
