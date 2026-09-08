#!/usr/bin/env python3
"""
Verification suite for the 10 blockers found in the structural validation.

Each test asserts the SPECIFIC defect is gone — not merely that code runs.
"""

import asyncio
import sys
import os
import logging

logging.disable(logging.CRITICAL)  # keep output readable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print(f"{'✅' if condition else '❌'} {name}" + (f"\n     {detail}" if detail else ""))


def code_only(source: str) -> str:
    """
    Strip whole-line comments so assertions test EXECUTABLE code.

    The fix comments deliberately quote the old buggy lines (e.g.
    "was `entry_price * 1.01`"), which would otherwise match the very patterns
    we are asserting are gone. Code lines are left byte-identical so substring
    checks against real code still work.
    """
    return "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )


# Realistic UW alert (schema captured from the live API)
ALERT = {
    "underlying_symbol": "NVDA",
    "option_type": "call",
    "strike": "225",
    "expiry": "2026-09-11",
    "underlying_price": "226.24",
    "nbbo_bid": "3.85",
    "nbbo_ask": "3.90",
    "premium": "192500.00",
    "volume": 3874,
    "open_interest": 12685,
    "option_chain_id": "NVDA260911C00225000",
    "delta": "0.572730982767671",
    "gamma": "0.0495097479599377",
    "tags": ["ask_side", "bullish"],
}

BEARISH_SELL = {**ALERT, "tags": ["bid_side", "bearish"]}
PUT_ALERT = {
    **ALERT,
    "option_type": "put",
    "tags": ["ask_side", "bearish"],
    "option_chain_id": "NVDA260911P00225000",
    "delta": "-0.42",
}


async def main():
    print("=" * 78)
    print("BLOCKER FIX VERIFICATION")
    print("=" * 78 + "\n")

    from uw_bot import UnusualWhalesBot
    from uw_execution_safeguards import ExecutionSafeguards, now_eastern, EOD_FORCE_CLOSE_TIME
    from uw_position_manager import PositionManager
    from uw_robinhood_mcp import RobinhoodMCPClient

    # ---------------------------------------------------------------- #1
    print("--- #1 Symbol field ---")
    bot = UnusualWhalesBot.__new__(UnusualWhalesBot)  # no __init__ side effects
    import inspect
    src = code_only(inspect.getsource(UnusualWhalesBot.execute_trade))
    check(
        "#1 execute_trade reads underlying_symbol (not the nonexistent 'symbol')",
        'alert.get("underlying_symbol")' in src and 'alert.get("symbol", "SPX")' not in src,
    )

    # ---------------------------------------------------------------- #2
    print("\n--- #2 Hardcoded price ---")
    check(
        "#2 hardcoded `current_price = 4500` removed",
        "4500" not in src,
    )

    # ---------------------------------------------------------------- #3
    print("\n--- #3 Direction-aware stops ---")
    sg = ExecutionSafeguards()
    call_plan = sg.generate_execution_plan(
        symbol="NVDA", entry_price=3.87, quantity=1,
        underlying_current_price=226.24, atr_14=5.0, direction="CALL",
    )
    put_plan = sg.generate_execution_plan(
        symbol="NVDA", entry_price=3.87, quantity=1,
        underlying_current_price=226.24, atr_14=5.0, direction="PUT",
    )
    check(
        "#3 CALL stop below spot, target above",
        call_plan.underlying_stop_price < 226.24 < call_plan.underlying_target_price,
        f"stop={call_plan.underlying_stop_price:.2f} target={call_plan.underlying_target_price:.2f}",
    )
    check(
        "#3 PUT stop ABOVE spot, target BELOW (was inverted)",
        put_plan.underlying_stop_price > 226.24 > put_plan.underlying_target_price,
        f"stop={put_plan.underlying_stop_price:.2f} target={put_plan.underlying_target_price:.2f}",
    )

    pm = PositionManager(positions_file="/tmp/_test_positions.json")
    pm.positions.clear()
    pid = pm.add_position(
        symbol="NVDA", direction="PUT", entry_price=3.87, quantity=1,
        underlying_stop=put_plan.underlying_stop_price,
        underlying_target=put_plan.underlying_target_price,
        option_chain_id="NVDA260911P00225000", entry_underlying=226.24, delta=-0.42,
    )
    # Price FALLS -> a PUT is winning -> must read TARGET_HIT, not STOP_HIT
    exits = pm.check_positions_against_price("NVDA", 210.0)
    check(
        "#3 falling price on a PUT books TARGET_HIT (was STOP_HIT)",
        exits and exits[0][1] == "TARGET_HIT",
        f"got {exits}",
    )

    # ---------------------------------------------------------------- #4
    print("\n--- #4 Paper mode actually executes ---")
    paper = RobinhoodMCPClient(use_mock=False, paper_trading=True)
    resp = await paper.place_option_order(
        symbol="NVDA", option_chain_id="NVDA260911C00225000", quantity=1,
        limit_price=3.87, nbbo_bid=3.85, nbbo_ask=3.90,
    )
    check("#4 PAPER mode fills orders (was success=False on every trade)",
          resp.success and resp.fill_price, f"fill=${resp.fill_price}")

    live = RobinhoodMCPClient(use_mock=False, paper_trading=False)
    live_resp = await live.place_option_order(
        symbol="NVDA", option_chain_id="X", quantity=1, limit_price=1.0
    )
    check("#4 LIVE without MCP fails LOUDLY with a clear reason",
          not live_resp.success and "MCP" in live_resp.message)

    # ---------------------------------------------------------------- #5
    print("\n--- #5 option_chain_id ---")
    check("#5 real OCC id used, never synthesized '_mock'",
          "_mock" not in src and 'alert.get("option_chain_id")' in src)

    # ---------------------------------------------------------------- #7
    print("\n--- #7 Technical gates ---")
    from uw_market_data import get_async_market_data
    from uw_technical_gates import TechnicalGates
    tg = TechnicalGates(get_async_market_data())
    conf = await tg.calculate_technical_confidence("NVDA", "CALL", 226.24)
    check("#7 gates run against real data and return a usable confidence",
          isinstance(conf, float) and 0.0 <= conf <= 1.0, f"confidence={conf}")

    md = get_async_market_data()
    candles = await md.get_historical_candles("NVDA", "day", 30)
    check("#7 get_historical_candles now EXISTS and returns real candles",
          len(candles) > 10, f"{len(candles)} candles")

    from uw_phase1_filter import Phase1AlertFilter
    from uw_phase1_technical_integration import Phase1TechnicalWrapper
    wrapper = Phase1TechnicalWrapper(Phase1AlertFilter(), get_async_market_data())
    approved, wconf = await wrapper.filter_alert_with_technicals(ALERT, current_price=226.24)
    check("#7 wrapper calls filter_alert (evaluate_alert did not exist)",
          approved is True, f"approved={approved} conf={wconf:.2f}")

    # ---------------------------------------------------------------- #8
    print("\n--- #8 Real P&L ---")
    up = RobinhoodMCPClient.estimate_option_value(3.87, 226.24, 236.24, 0.57, 0.049, "CALL")
    down = RobinhoodMCPClient.estimate_option_value(3.87, 226.24, 216.24, 0.57, 0.049, "CALL")
    check("#8 CALL gains when underlying rises, loses when it falls",
          up > 3.87 > down, f"+10 -> ${up}, -10 -> ${down}")
    put_up = RobinhoodMCPClient.estimate_option_value(3.87, 226.24, 216.24, -0.42, 0.04, "PUT")
    check("#8 PUT gains when underlying FALLS", put_up > 3.87, f"-10 -> ${put_up}")
    check("#8 no fixed +1% exit remains in the bot",
          "* 1.01" not in code_only(inspect.getsource(sys.modules["uw_bot"])))

    # ---------------------------------------------------------------- #9
    print("\n--- #9 Risk limits ---")
    bot_src = code_only(inspect.getsource(sys.modules["uw_bot"]))
    check("#9 MAX_OPEN_POSITIONS enforced", "MAX_OPEN_POSITIONS" in src)
    check("#9 daily-loss circuit breaker implemented", "MAX_DAILY_LOSS_PCT" in bot_src and "self.halted" in bot_src)

    # ---------------------------------------------------------------- #10
    print("\n--- #10 Entry dedup ---")
    check("#10 has_open_position() exists", hasattr(pm, "has_open_position"))
    check("#10 open symbol is detected", pm.has_open_position("NVDA") is True)
    check("#10 execute_trade consults it", "has_open_position" in src)

    # ---------------------------------------------------------------- direction
    print("\n--- Direction classification (UW tags) ---")
    check("ask_side + bullish CALL is actionable",
          UnusualWhalesBot.classify_alert(ALERT) == {"direction": "CALL", "bias": "BULLISH"})
    check("bid_side (seller-initiated) CALL is SKIPPED, not treated as bullish",
          UnusualWhalesBot.classify_alert(BEARISH_SELL) is None)
    check("ask_side + bearish PUT is actionable",
          UnusualWhalesBot.classify_alert(PUT_ALERT) == {"direction": "PUT", "bias": "BEARISH"})

    # ---------------------------------------------------------------- EOD tz
    print("\n--- EOD timezone ---")
    from uw_execution_safeguards import MARKET_TZ
    check("EOD anchored to US/Eastern, not host CDT",
          MARKET_TZ is not None and str(MARKET_TZ) == "America/New_York",
          f"now ET = {now_eastern().strftime('%H:%M')} , trigger {EOD_FORCE_CLOSE_TIME}")

    # ---------------------------------------------------------------- atomic
    print("\n--- Atomic writes ---")
    check("position saves are atomic (tmp + os.replace)",
          "os.replace" in inspect.getsource(PositionManager._save_positions))

    # ---------------------------------------------------------------- spread
    print("\n--- Spread threshold alignment ---")
    from uw_config import EXECUTION_SAFEGUARDS_CONFIG
    from uw_phase1_filter import Phase1AlertFilter as P1
    import inspect as _i
    default_spread = _i.signature(P1.__init__).parameters["max_spread_pct"].default
    check("Phase 1 and execution use the same max spread",
          abs(EXECUTION_SAFEGUARDS_CONFIG["max_bid_ask_spread_pct"] - default_spread) < 1e-9,
          f"phase1={default_spread}, execution={EXECUTION_SAFEGUARDS_CONFIG['max_bid_ask_spread_pct']}")

    pm.positions.clear()
    pm._save_positions()

    print("\n" + "=" * 78)
    print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        for f in FAIL:
            print(f"   ❌ {f}")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
