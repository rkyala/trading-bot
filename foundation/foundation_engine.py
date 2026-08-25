"""
Foundation Engine - Orchestrates All 6 Components
Central coordination point for Foundation Phase trading logic

Day 2 Integration: Connects all 6 components in proper order
1. ATR filter → Skip high-vol symbols
2. Dynamic risk mgr → Calculate regime-specific stops
3. VWAP bands → Find entry zones
4. Macro trends → Check daily context
5. ORB detection → Skip breakout counter-trades
6. Backtest engine → Execute trades
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Dict, Optional, List, Tuple

# Import all 6 Foundation components
from backtest_framework import BacktestEngine, Position, Trade
from volatility_filter import VolatilityFilter
from risk_manager import DynamicRiskManager
from vwap_calculator import SessionAnchoredVWAP
from macro_trigger_scanner import MacroTriggerScanner
from orb_detector import OpeningRangeBreakout

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FoundationEngine:
    """
    Complete Foundation Phase trading orchestrator

    Execution Order:
    1. Symbol Screening (ATR filter)
    2. Entry Signal Detection (EMA 20>50, ADX>20, Stoch K<30)
    3. Risk Calculation (Dynamic stops by volatility)
    4. VWAP Band Confirmation (Price at -2σ)
    5. Macro Context Check (Daily trend bullish?)
    6. ORB Filter (Not breakout mode?)
    7. Trade Execution (If all pass)

    Key Design:
    - All components are optional (graceful degradation)
    - Component failures don't stop trading, just reduce confidence
    - Comprehensive logging for debugging
    """

    def __init__(self, initial_capital: float = 10000):
        """Initialize all 6 Foundation components"""
        # Core backtest engine
        self.backtest_engine = BacktestEngine(
            initial_capital=initial_capital,
            position_size_pct=0.015  # 1.5% per trade
        )

        # Component 1: Volatility filtering
        self.volatility_filter = VolatilityFilter(
            atr_window=14,
            max_atr_pct=3.0
        )

        # Component 2: Dynamic risk management
        self.risk_manager = DynamicRiskManager()

        # Component 3: Session-anchored VWAP
        self.vwap_calc = SessionAnchoredVWAP()

        # Component 4: Macro trigger scanner
        self.macro_scanner = MacroTriggerScanner()

        # Component 5: ORB detector
        self.orb_detector = OpeningRangeBreakout()

        # Execution stats
        self.signals_generated = 0
        self.signals_filtered = 0
        self.trades_executed = 0

    def filter_symbols_by_volatility(self, symbol_data: Dict[str, Dict]) -> List[str]:
        """
        STEP 1: Filter symbols by ATR

        Skips high-volatility symbols (ATR > 3%)
        that cause whipsaws on mean-reversion
        """
        logger.info("\n" + "="*70)
        logger.info("STEP 1: VOLATILITY FILTER (ATR-based screening)")
        logger.info("="*70)

        tradeable_symbols = []

        for symbol, candles in symbol_data.items():
            high = np.array(candles.get('high', []))
            low = np.array(candles.get('low', []))
            close = np.array(candles.get('close', []))

            if len(high) < 14:  # Not enough data for ATR
                logger.warning(f"[{symbol}] Insufficient data for ATR")
                continue

            atr_pct = self.volatility_filter.calculate_atr_pct(high, low, close)

            if self.volatility_filter.is_symbol_tradeable(high, low, close):
                tradeable_symbols.append(symbol)
                logger.info(f"✅ [{symbol}] PASS - ATR {atr_pct:.2f}%")
            else:
                logger.warning(f"❌ [{symbol}] SKIP - ATR {atr_pct:.2f}% > 3%")

        logger.info(f"\nSymbols passed volatility filter: {tradeable_symbols}\n")
        return tradeable_symbols

    def screen_entry_signal(self, symbol: str, current_data: Dict) -> bool:
        """
        STEP 2: Screen entry signal criteria

        Original criteria:
        - EMA 20 > EMA 50 (uptrend)
        - ADX > 20 (trend strength)
        - Stoch K < 30 (oversold)
        """
        ema_20 = current_data.get('ema_20', 0)
        ema_50 = current_data.get('ema_50', 0)
        adx = current_data.get('adx', 0)
        stoch_k = current_data.get('stoch_k', 100)

        # Check criteria
        if ema_20 <= ema_50:
            logger.debug(f"[{symbol}] Rejected: EMA 20 ({ema_20:.2f}) <= EMA 50 ({ema_50:.2f})")
            return False

        if adx < 20:
            logger.debug(f"[{symbol}] Rejected: ADX ({adx:.1f}) < 20")
            return False

        if stoch_k > 30:
            logger.debug(f"[{symbol}] Rejected: Stoch K ({stoch_k:.1f}) > 30 (not oversold)")
            return False

        logger.info(f"✅ [{symbol}] Entry signal passed (EMA OK, ADX={adx:.1f}, K={stoch_k:.1f})")
        return True

    def calculate_dynamic_stops(self, symbol: str, entry_price: float,
                               atr_pct: float) -> Tuple[float, float, str]:
        """
        STEP 3: Calculate dynamic stops based on volatility

        Returns:
            (stop_loss_price, target_price, regime)
        """
        levels = self.risk_manager.calculate_stops_and_targets(entry_price, atr_pct)

        logger.info(
            f"[{symbol}] Dynamic risk ({levels.regime}): "
            f"Stop ${levels.stop_loss:.2f} | Target ${levels.target:.2f}"
        )

        return levels.stop_loss, levels.target, levels.regime

    def check_vwap_entry_zone(self, symbol: str, current_price: float,
                             vwap_bands: Dict) -> bool:
        """
        STEP 4: Confirm price at VWAP -2σ band

        -2σ band = institutional reversal zone
        Only enter if price at or below this level
        """
        if not vwap_bands or 'lower_2s' not in vwap_bands:
            logger.warning(f"[{symbol}] VWAP bands not available, skipping check")
            return True  # Don't reject if data missing

        lower_2s = vwap_bands['lower_2s'][-1]
        vwap = vwap_bands['vwap'][-1]

        if current_price <= lower_2s:
            logger.info(
                f"✅ [{symbol}] VWAP check passed: "
                f"Price ${current_price:.2f} at -2σ (${lower_2s:.2f})"
            )
            return True
        else:
            logger.debug(
                f"[{symbol}] Price ${current_price:.2f} above -2σ "
                f"(${lower_2s:.2f}), not extreme enough"
            )
            return False

    def check_macro_context(self, symbol: str) -> Optional[bool]:
        """
        STEP 5: Check daily trend context (non-blocking)

        Returns:
            True if daily bullish, False if bearish, None if no data
        """
        trend = self.macro_scanner.get_trend_for_symbol(symbol)

        if trend is None:
            logger.warning(f"[{symbol}] Daily trend not available (macro scanner not run yet)")
            return None

        if trend == "BULLISH":
            logger.info(f"✅ [{symbol}] Daily trend bullish (full position size)")
            return True
        else:
            logger.warning(f"⚠️  [{symbol}] Daily trend bearish (reduce position size to 50%)")
            return False

    def check_orb_filter(self, symbol: str, current_price: float,
                        adx: float, orb_range: Dict) -> bool:
        """
        STEP 6: ORB filter - skip counter-trend entries on breakouts

        Skip mean-reversion when:
        - Price > ORB high + ADX > 25 (bullish breakout)
        - Price < ORB low + ADX > 25 (bearish breakdown)
        """
        if not orb_range:
            logger.debug(f"[{symbol}] ORB range not available, skip filter")
            return True  # Pass if no data

        should_skip = self.orb_detector.should_skip_mean_reversion(
            current_price, adx, orb_range
        )

        if should_skip:
            logger.warning(f"❌ [{symbol}] ORB filter: Breakout detected, skip mean-reversion")
            return False
        else:
            logger.info(f"✅ [{symbol}] ORB filter passed (within range)")
            return True

    def generate_entry_signal(self, symbol: str,
                             current_data: Dict,
                             symbol_candles: Dict,
                             vwap_bands: Dict,
                             orb_range: Dict,
                             atr_pct: float) -> Optional[Dict]:
        """
        Complete entry signal generation with all 6 components

        Returns:
            Entry signal dict if all pass, None if rejected
        """
        logger.info(f"\n{'='*70}")
        logger.info(f"EVALUATING ENTRY: {symbol}")
        logger.info(f"{'='*70}")

        current_price = current_data.get('price', 0)
        adx = current_data.get('adx', 0)

        # STEP 2: Entry signal
        if not self.screen_entry_signal(symbol, current_data):
            self.signals_filtered += 1
            return None

        # STEP 3: Dynamic stops
        stop_loss, target, regime = self.calculate_dynamic_stops(
            symbol, current_price, atr_pct
        )

        # STEP 4: VWAP confirmation
        if not self.check_vwap_entry_zone(symbol, current_price, vwap_bands):
            logger.info(f"[{symbol}] VWAP filter rejected entry")
            self.signals_filtered += 1
            return None

        # STEP 5: Macro context
        daily_bullish = self.check_macro_context(symbol)

        # STEP 6: ORB filter
        if not self.check_orb_filter(symbol, current_price, adx, orb_range):
            self.signals_filtered += 1
            return None

        # All filters passed!
        self.signals_generated += 1

        signal = {
            'symbol': symbol,
            'entry_price': current_price,
            'stop_loss': stop_loss,
            'target': target,
            'volatility_regime': regime,
            'daily_trend': 'BULLISH' if daily_bullish else 'BEARISH',
            'timestamp': datetime.utcnow()
        }

        logger.info(f"✅✅✅ SIGNAL GENERATED FOR {symbol} ✅✅✅")
        return signal

    def execute_entry(self, signal: Dict) -> bool:
        """Execute entry based on passed signal"""
        if not signal:
            return False

        success = self.backtest_engine.enter_trade(
            symbol=signal['symbol'],
            entry_price=signal['entry_price'],
            stop_loss=signal['stop_loss'],
            target=signal['target'],
            entry_time=signal['timestamp']
        )

        if success:
            self.trades_executed += 1

        return success

    def print_cycle_summary(self):
        """Print cycle execution summary"""
        print("\n" + "="*70)
        print("FOUNDATION CYCLE SUMMARY")
        print("="*70)
        print(f"Signals Generated: {self.signals_generated}")
        print(f"Signals Filtered:  {self.signals_filtered}")
        print(f"Trades Executed:   {self.trades_executed}")
        print(f"Active Positions:  {len(self.backtest_engine.positions)}")
        print(f"Completed Trades:  {len(self.backtest_engine.trades)}")
        print(f"Account Balance:   ${self.backtest_engine.current_balance:,.2f}")
        print("="*70 + "\n")


# Usage example and test
if __name__ == "__main__":
    engine = FoundationEngine(initial_capital=10000)

    # Simulated data for one cycle
    symbol_data = {
        'CRWD': {'high': np.random.randn(50) + 190, 'low': np.random.randn(50) + 188, 'close': np.random.randn(50) + 189},
        'ZM': {'high': np.random.randn(50) + 141, 'low': np.random.randn(50) + 139, 'close': np.random.randn(50) + 140},
        'JD': {'high': np.random.randn(50) + 61, 'low': np.random.randn(50) + 59, 'close': np.random.randn(50) + 60}
    }

    # STEP 1: Filter by volatility
    tradeable = engine.filter_symbols_by_volatility(symbol_data)

    print(f"\nTradeable symbols: {tradeable}")
