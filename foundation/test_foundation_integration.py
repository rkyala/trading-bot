"""
Foundation Integration Test
Validates all 6 components working together

Day 2 Final: Integration verification before backtest execution
"""

import pandas as pd
import numpy as np
from datetime import datetime
import logging

# Import all Foundation components
from backtest_framework import BacktestEngine
from volatility_filter import VolatilityFilter
from risk_manager import DynamicRiskManager
from vwap_calculator import SessionAnchoredVWAP
from macro_trigger_scanner import MacroTriggerScanner
from orb_detector import OpeningRangeBreakout
from foundation_engine import FoundationEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_component_1_backtest_engine():
    """Test Component 1: Backtest Framework"""
    print("\n" + "="*70)
    print("TEST 1: Backtest Engine")
    print("="*70)

    engine = BacktestEngine(initial_capital=10000)

    # Enter trade
    success = engine.enter_trade(
        symbol='ZM',
        entry_price=140.00,
        stop_loss=137.55,  # -1.75%
        target=144.90,     # +3.5%
        entry_time=datetime.now()
    )

    assert success, "Entry failed"
    assert 'ZM' in engine.positions, "Position not created"

    # Check exit condition (target hit)
    exit_reason = engine.check_position_exit('ZM', 145.00, datetime.now())
    assert exit_reason == "target", "Target exit not detected"

    # Exit trade
    success = engine.exit_trade('ZM', 145.00, datetime.now(), exit_reason)
    assert success, "Exit failed"
    assert len(engine.trades) == 1, "Trade not recorded"

    trade = engine.trades[0]
    assert trade.pnl > 0, "P&L should be positive"

    print(f"✅ Backtest engine works: Entry $140 → Exit $145 = ${trade.pnl:.2f} P&L")


def test_component_2_volatility_filter():
    """Test Component 2: Volatility Filter"""
    print("\n" + "="*70)
    print("TEST 2: Volatility Filter (ATR Screening)")
    print("="*70)

    vf = VolatilityFilter(max_atr_pct=3.0)

    # Simulated data: ZM (1.9% ATR) = tradeable
    zm_prices = np.linspace(140, 141, 50)
    zm_high = zm_prices + 0.5
    zm_low = zm_prices - 0.5

    is_tradeable = vf.is_symbol_tradeable(zm_high, zm_low, zm_prices)
    assert is_tradeable, "ZM should be tradeable"

    print(f"✅ Volatility filter works: ZM (1.9% ATR) = TRADEABLE")


def test_component_3_risk_manager():
    """Test Component 3: Dynamic Risk Manager"""
    print("\n" + "="*70)
    print("TEST 3: Dynamic Risk Manager")
    print("="*70)

    rm = DynamicRiskManager()

    # Test med-vol regime (ZM: 1.9%)
    levels = rm.calculate_stops_and_targets(entry_price=140.00, atr_pct=1.9)

    assert levels.regime == "med_vol", f"Expected med_vol, got {levels.regime}"
    assert levels.stop_pct == -1.75, "Stop should be -1.75%"
    assert levels.target_pct == 3.5, "Target should be +3.5%"

    # Verify 1:2 ratio
    ratio = abs(levels.target_pct / levels.stop_pct)
    assert abs(ratio - 2.0) < 0.01, f"Ratio should be 2.0, got {ratio}"

    print(f"✅ Dynamic risk manager works: Med-vol regime (1.9%) → -1.75%/+3.5% (1:2)")


def test_component_4_vwap():
    """Test Component 4: Session-Anchored VWAP"""
    print("\n" + "="*70)
    print("TEST 4: Session-Anchored VWAP")
    print("="*70)

    vwap_calc = SessionAnchoredVWAP()

    # Simulated session data
    high = np.array([140.5, 141.0, 140.8])
    low = np.array([140.0, 140.5, 140.0])
    close = np.array([140.2, 140.9, 140.5])
    volume = np.array([1000000, 1100000, 900000])

    vwap_bands = vwap_calc.calculate_vwap_bands(high, low, close, volume)

    assert 'vwap' in vwap_bands, "VWAP not calculated"
    assert 'lower_2s' in vwap_bands, "Lower 2σ not calculated"

    vwap = vwap_bands['vwap'][-1]
    lower_2s = vwap_bands['lower_2s'][-1]

    assert lower_2s < vwap, "Lower band should be below VWAP"

    print(f"✅ VWAP calculator works: VWAP=${vwap:.2f}, -2σ=${lower_2s:.2f}")


def test_component_5_macro_scanner():
    """Test Component 5: Macro Trigger Scanner"""
    print("\n" + "="*70)
    print("TEST 5: Macro Trigger Scanner")
    print("="*70)

    scanner = MacroTriggerScanner()

    # Simulated daily closes (uptrend)
    daily_closes = np.cumsum(np.random.randn(60) * 0.5) + 140

    result = scanner.scan_symbol('ZM', daily_closes)

    assert result is not None, "Scan failed"
    assert 'trend' in result, "Trend not calculated"
    assert result['trend'] in ['BULLISH', 'BEARISH'], "Invalid trend"

    print(f"✅ Macro scanner works: ZM trend = {result['trend']}")


def test_component_6_orb():
    """Test Component 6: ORB Detector"""
    print("\n" + "="*70)
    print("TEST 6: Opening Range Breakout Detector")
    print("="*70)

    detector = OpeningRangeBreakout()

    # Simulated ORB range
    orb_data = pd.DataFrame({
        'Open': [140.0],
        'High': [141.5],
        'Low': [139.5],
        'Close': [140.5],
        'Volume': [1000000]
    })

    orb_range = detector.calculate_orb_range(orb_data)

    # Test breakout
    is_breakout, breakout_type = detector.detect_orb_breakout(
        current_price=142.0,
        adx=28,
        orb_range=orb_range
    )

    assert is_breakout, "Breakout should be detected"
    assert breakout_type == "bullish", "Should be bullish breakout"

    print(f"✅ ORB detector works: Bullish breakout detected at $142")


def test_integration_engine():
    """Test complete Foundation Engine integration"""
    print("\n" + "="*70)
    print("TEST 7: Complete Foundation Engine Integration")
    print("="*70)

    engine = FoundationEngine(initial_capital=10000)

    # Simulated trading data
    symbol_data = {
        'ZM': {
            'high': np.linspace(140, 142, 50) + np.random.randn(50) * 0.2,
            'low': np.linspace(140, 142, 50) - np.random.randn(50) * 0.2,
            'close': np.linspace(140, 142, 50) + np.random.randn(50) * 0.1
        }
    }

    current_data = {
        'price': 139.7,  # At VWAP -2σ level
        'ema_20': 140.3,
        'ema_50': 139.0,
        'adx': 22,
        'stoch_k': 25
    }

    # VWAP bands
    vwap_bands = {
        'vwap': np.array([140.5]),
        'lower_2s': np.array([139.8])
    }

    # ORB range
    orb_range = {
        'orb_high': 141.0,
        'orb_low': 139.5,
        'orb_range': 1.5
    }

    # Generate signal
    signal = engine.generate_entry_signal(
        symbol='ZM',
        current_data=current_data,
        symbol_candles=symbol_data['ZM'],
        vwap_bands=vwap_bands,
        orb_range=orb_range,
        atr_pct=1.9
    )

    assert signal is not None, "Signal generation failed"
    assert signal['symbol'] == 'ZM', "Wrong symbol"
    assert 'entry_price' in signal, "Entry price missing"

    print(f"✅ Foundation engine generates signals: {signal}")


def run_all_tests():
    """Run all integration tests"""
    print("\n" + "="*70)
    print("FOUNDATION INTEGRATION TEST SUITE")
    print("="*70)

    try:
        test_component_1_backtest_engine()
        test_component_2_volatility_filter()
        test_component_3_risk_manager()
        test_component_4_vwap()
        test_component_5_macro_scanner()
        test_component_6_orb()
        test_integration_engine()

        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED - Foundation ready for backtest!")
        print("="*70 + "\n")

        return True

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return False
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
