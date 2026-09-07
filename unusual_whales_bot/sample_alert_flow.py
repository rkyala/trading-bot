"""
Sample Alert Flow: Real UW Alert → Phase 1 → Phase 3B → Execution

Shows complete end-to-end pipeline with realistic data.
"""

import asyncio
import json
from datetime import datetime
from uw_phase1_filter import Phase1AlertFilter
from uw_api_client import UnusualWhalesMockAPI
from uw_llm_debate_engine import PortfolioDebateEngine

# Color codes for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


async def sample_alert_flow():
    """Run a realistic alert through entire pipeline."""
    
    print(f"\n{BOLD}{'='*100}")
    print(f"SAMPLE UW ALERT FLOW: LIVE PIPELINE EXECUTION")
    print(f"{'='*100}{RESET}\n")
    
    # =====================================================================
    # STEP 1: RAW UW ALERT RECEIVED
    # =====================================================================
    print(f"{CYAN}[09:42:15] RAW UNUSUAL WHALES ALERT RECEIVED{RESET}\n")
    
    raw_alert = {
        "alert_id": "UW_2026090842151234",
        "timestamp": "2026-09-08T09:42:15Z",
        "symbol": "NVDA",
        "strike_price": 125.0,
        "expiration": "2026-09-15",
        "direction": "CALL",
        "premium": 425_000,  # $425k sweep
        "volume": 1_850,
        "open_interest": 890,
        "ask_volume_pct": 0.82,  # 82% on ask side
        "bid_ask_spread": 0.05,  # $0.05 spread
        "last_trade_price": 4.35,
        "iv_rank": 0.72,
        "dte": 7,
        "source": "CBOE sweep alert",
    }
    
    print(f"{BOLD}Alert Details:{RESET}")
    print(f"  Symbol:        {raw_alert['symbol']} ${raw_alert['strike_price']:.0f} CALL (DTE {raw_alert['dte']})")
    print(f"  Premium:       ${raw_alert['premium']:,.0f}")
    print(f"  Volume:        {raw_alert['volume']:,} contracts")
    print(f"  Ask Volume %:  {raw_alert['ask_volume_pct']*100:.0f}% (aggressive buying)")
    print(f"  Spread:        ${raw_alert['bid_ask_spread']:.2f} (liquid)")
    print(f"  IV Rank:       {raw_alert['iv_rank']*100:.0f}% (elevated)")
    print()
    
    # =====================================================================
    # STEP 2: PHASE 1 - QUANTITATIVE 6-GATE FILTER
    # =====================================================================
    print(f"{YELLOW}[09:42:16] PHASE 1: QUANTITATIVE 6-GATE FILTER{RESET}\n")
    
    # Mock UW data
    market_tide = {
        "net_call_premium": 52_000_000,      # $52M bullish
        "net_put_premium": -8_000_000,       # -$8M bearish
        "net_direction": "BULLISH",
    }
    
    net_ticker_prem = {
        "ticker": "NVDA",
        "net_call_premium": 5_200_000,       # $5.2M bullish on NVDA specifically
        "net_put_premium": -800_000,         # -$800k bearish
        "net_direction": "BULLISH",
        "time_window": 60,
    }
    
    dark_pool = {
        "ticker": "NVDA",
        "dark_pool_volume": 12_300_000,      # $12.3M off-exchange
        "dark_pool_side": "BUY",              # Institutions buying stock (not dump)
        "block_trades": 34,
        "suspicious": False,
    }
    
    vol_oi = {
        "ticker": "NVDA",
        "volume": 1_850,
        "open_interest": 890,
        "vol_oi_ratio": 2.08,                # Vol/OI > 1.2 = STRONG new positioning
        "position_type": "NEW_OPENING",
        "confirmation": "STRONG",
    }
    
    # Gate logic
    gates = {
        "Gate 1 (Premium > $100k)": raw_alert["premium"] > 100_000,
        "Gate 2 (Ask vol > 70%)": raw_alert["ask_volume_pct"] > 0.70,
        "Gate 3 (Market Tide)": market_tide["net_direction"] == "BULLISH",
        "Gate 4 (Net Ticker Prem)": net_ticker_prem["net_direction"] == "BULLISH",
        "Gate 5 (Dark Pool)": not (dark_pool["suspicious"] and dark_pool["dark_pool_side"] == "SELL"),
        "Gate 6 (Vol/OI > 1.0)": vol_oi["vol_oi_ratio"] > 1.0,
    }
    
    print(f"{BOLD}Gate Evaluation:{RESET}")
    all_passed = True
    for gate_name, result in gates.items():
        status = f"{GREEN}✅ PASS{RESET}" if result else f"{RED}❌ FAIL{RESET}"
        print(f"  {gate_name}: {status}")
        if not result:
            all_passed = False
    
    print()
    
    if not all_passed:
        print(f"{RED}PHASE 1 RESULT: REJECTED (failed gate check){RESET}\n")
        return
    
    print(f"{GREEN}PHASE 1 RESULT: APPROVED ✅ (all 6 gates passed){RESET}\n")
    
    # =====================================================================
    # STEP 3: PHASE 3B - LLM MULTI-AGENT DEBATE
    # =====================================================================
    print(f"{CYAN}[09:42:17] PHASE 3B: LLM MULTI-AGENT DEBATE ENGINE{RESET}\n")
    
    debate_engine = PortfolioDebateEngine()
    
    # Enrich alert for LLM
    alert_for_llm = {
        "symbol": raw_alert["symbol"],
        "direction": raw_alert["direction"],
        "strike_price": raw_alert["strike_price"],
        "premium": raw_alert["premium"],
        "ask_volume_pct": raw_alert["ask_volume_pct"],
    }
    
    # Simulate macro news (in real system, this comes from news APIs)
    macro_news = [
        "Fed holds rates steady at 4.5% (no change)",
        "NVIDIA earnings beat: +12% guidance raise",
        "AI semiconductor demand remains strong",
    ]
    
    # Run LLM debate
    decision = await debate_engine.execute_debate(
        alert=alert_for_llm,
        market_tide=market_tide,
        gex_data={"max_call_gex_strike": 135.0, "max_put_gex_strike": 115.0},
        dark_pool_data=dark_pool,
        iv_data={"iv_crush_pct": 5.0},
        macro_news=macro_news,
    )
    
    print()
    
    # =====================================================================
    # STEP 4: EXECUTION DECISION
    # =====================================================================
    print(f"{CYAN}[09:42:19] EXECUTION DECISION{RESET}\n")
    
    print(f"{BOLD}Decision Summary:{RESET}")
    print(f"  Trade Approved:    {GREEN if decision.trade_approved else RED}{'YES ✅' if decision.trade_approved else 'NO ❌'}{RESET}")
    print(f"  Conviction Score:  {decision.final_conviction:.2f}/1.0")
    print(f"  Position Scale:    {decision.adjusted_position_scale:.2f}x")
    print(f"  Risk Summary:      {decision.risk_summary}")
    print()
    
    if not decision.trade_approved:
        print(f"{RED}EXECUTION: TRADE REJECTED{RESET}\n")
        return
    
    # =====================================================================
    # STEP 5: POSITION SIZING & EXECUTION
    # =====================================================================
    print(f"{GREEN}[09:42:20] POSITION SIZING & EXECUTION{RESET}\n")
    
    # Calculate position size
    base_position_size = 1  # 1 contract
    risk_per_trade = 0.02  # 2% risk
    account_size = 50_000  # $50k account
    
    risk_amount = account_size * risk_per_trade  # $1,000 risk
    entry_price = raw_alert["last_trade_price"]
    
    # Calculate stop (ATR-based, simplified)
    atr_14 = 8.5  # Estimated ATR for NVDA
    stop_offset = 1.5 * atr_14  # $12.75
    stop_price = entry_price - stop_offset
    
    # Target (2.5x ATR)
    target_price = entry_price + (2.5 * atr_14)
    
    # Scaled position size
    scaled_size = base_position_size * decision.adjusted_position_scale
    
    print(f"{BOLD}Position Calculation:{RESET}")
    print(f"  Base Size:         1 contract")
    print(f"  LLM Scale Factor:  {decision.adjusted_position_scale:.2f}x")
    print(f"  Final Size:        {scaled_size:.2f} contracts")
    print(f"  Entry Price:       ${entry_price:.2f}")
    print(f"  Stop Loss:         ${stop_price:.2f} ({-stop_offset:.2f} points)")
    print(f"  Target Price:      ${target_price:.2f} ({2.5 * atr_14:.2f} points)")
    print(f"  Risk/Reward:       1:{(target_price - entry_price) / (entry_price - stop_price):.2f}")
    print()
    
    # =====================================================================
    # STEP 6: ORDER SUBMISSION
    # =====================================================================
    print(f"{BOLD}[09:42:21] ORDER SUBMISSION (ROBINHOOD MCP){RESET}\n")
    
    order_details = {
        "order_id": f"UW_{datetime.now().strftime('%H%M%S')}_001",
        "symbol": raw_alert["symbol"],
        "option_chain_id": f"NVDA_20260915_125C",
        "direction": "buy_to_open",
        "quantity": int(scaled_size),
        "order_type": "limit",
        "limit_price": entry_price + 0.05,  # Limit 5 cents above market
        "time_in_force": "day",
    }
    
    print(f"{BOLD}Order Details:{RESET}")
    print(f"  Order ID:          {order_details['order_id']}")
    print(f"  Direction:         {order_details['direction']}")
    print(f"  Quantity:          {order_details['quantity']} contract(s)")
    print(f"  Order Type:        {order_details['order_type']}")
    print(f"  Limit Price:       ${order_details['limit_price']:.2f}")
    print(f"  Time in Force:     {order_details['time_in_force']}")
    print()
    
    print(f"{GREEN}[09:42:22] ORDER SUBMITTED ✅{RESET}")
    print(f"  Status:            PENDING (awaiting broker confirmation)")
    print()
    
    # =====================================================================
    # STEP 7: POSITION TRACKING
    # =====================================================================
    print(f"{BOLD}[09:42:23] POSITION TRACKING ACTIVATED{RESET}\n")
    
    print(f"{BOLD}Position State (JSON):{RESET}")
    position = {
        "position_id": f"{raw_alert['symbol']}_CALL_094215000001",
        "symbol": raw_alert["symbol"],
        "direction": "CALL",
        "entry_price": entry_price,
        "quantity": int(scaled_size),
        "entry_time": "2026-09-08T09:42:23Z",
        "underlying_stop": stop_price,
        "underlying_target": target_price,
        "option_chain_id": order_details["option_chain_id"],
        "order_id": order_details["order_id"],
        "max_hold_hours": 4,
        "eod_close_time": "15:45:00",
    }
    
    print(json.dumps(position, indent=2))
    print()
    
    # =====================================================================
    # STEP 8: DISCORD ALERT
    # =====================================================================
    print(f"{BOLD}[09:42:24] DISCORD ALERT POSTED{RESET}\n")
    
    discord_msg = f"""
🎯 **HIGH-CONVICTION ALERT EXECUTED**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**Symbol:** NVDA $125 CALL (DTE 7)
**Entry:** ${entry_price:.2f} (limit: ${order_details['limit_price']:.2f})
**Premium:** ${raw_alert['premium']:,}
**Ask Vol:** {raw_alert['ask_volume_pct']*100:.0f}% (aggressive)

**Confluence Factors:**
✅ Market Tide: BULLISH ($52M calls)
✅ Net NVDA Premium: BULLISH ($5.2M)
✅ Dark Pool: BUY ($12.3M)
✅ Vol/OI: 2.08 (STRONG new positioning)
✅ LLM Debate: APPROVED (conviction {decision.final_conviction:.2f})

**Risk Management:**
Stop: ${stop_price:.2f} | Target: ${target_price:.2f}
Risk/Reward: 1:{(target_price - entry_price) / (entry_price - stop_price):.2f}
Max Hold: 4 hours | EOD: Force close 3:45 PM

**Position:** {int(scaled_size)} contract(s) @ {decision.adjusted_position_scale:.2f}x scale
**Order ID:** {order_details['order_id']}
    """
    
    print(discord_msg)
    
    # =====================================================================
    # STEP 9: MONITORING LOOP
    # =====================================================================
    print(f"\n{BOLD}[MONITORING ACTIVATED]{RESET}")
    print(f"  Cycle time:        60 seconds")
    print(f"  Monitoring:        Price action, stop/target triggers")
    print(f"  Next check:        09:43:15")
    print()


if __name__ == "__main__":
    asyncio.run(sample_alert_flow())
