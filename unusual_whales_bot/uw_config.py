"""
Phase 2/3 Configuration: Unusual Whales Trading Bot

This config file controls execution modes, feature toggles, and tuning parameters.

KEY TOGGLES:
- EXECUTION_MODE: mock/paper/live trading
- SENTIMENT_ENABLED: Phase 3B Trading-Hero sentiment (requires Redis)
- DEBATE_ENGINE_ENABLED: Deterministic debate engine (confidence gating)
"""

import os
from datetime import time

# ===========================================================================
# EXECUTION MODE (Phase 2)
# ===========================================================================
EXECUTION_MODE = {
    # Use mock Robinhood responses (no real trading, testing only)
    "mock_mode": False,

    # Use Robinhood paper trading (real account, simulated capital)
    # ⏳ PAPER TRADING MODE: 2-day validation cycle
    # After review → switch to False for live trading
    "paper_trading": True,  # ✅ PAPER TRADING ENABLED (validation phase)

    # Log what would happen without actually executing
    "log_orders_only": False,  # Orders actually placed (in paper account)

    # Notional account equity used to evaluate the daily-loss circuit breaker
    "session_equity": 25000.0,

    # Used by uw_robinhood_mcp.py to determine behavior
}

# ===========================================================================
# PHASE 3B: SENTIMENT SERVICE (Optional)
# ===========================================================================
SENTIMENT_CONFIG = {
    # Enable Trading-Hero sentiment analysis (requires Redis + FinBERT)
    "sentiment_enabled": False,  # Toggle to True when ready for Phase 3B

    # Redis connection details
    "redis_host": os.getenv("REDIS_HOST", "localhost"),
    "redis_port": int(os.getenv("REDIS_PORT", 6379)),

    # How long to cache sentiment before refresh (seconds)
    "sentiment_ttl": 900,  # 15 minutes

    # Use FinBERT for sentiment (True) or fallback to keyword matching (False)
    "use_finbert": True,
}

# ===========================================================================
# DEBATE ENGINE (Phase 3B)
# ===========================================================================
DEBATE_ENGINE_CONFIG = {
    # Enable deterministic debate engine (gating + sizing)
    "enabled": True,

    # Minimum confidence to execute trade
    "min_confidence_threshold": 0.75,

    # Include sentiment confluence in confidence adjustment
    "use_sentiment": SENTIMENT_CONFIG["sentiment_enabled"],
}

# ===========================================================================
# EXIT RULES (Tier 2: Options-Based)
# ===========================================================================
EXIT_RULES_CONFIG = {
    # Use Tier 2 exit monitor (4 options-based rules)
    "tier2_enabled": True,

    # ---------------------------------------------------------------------
    # SHADOW MODE — Tier 2 runs and LOGS what it would do, but does not close
    # positions.
    #
    # Sep 8: Tier 2 had never actually run. Two of the four methods it calls
    # did not exist on the API client and the rest were hardcoded placeholders,
    # so check_all_exits() returned {} every cycle while the bot logged
    # "Tier 2 exits: ACTIVE". Now wired to real endpoints.
    #
    # On its first live test it immediately signalled market_tide_flip at 71%
    # confidence, because market-wide bullish_ratio was 29.3%. That rule is
    # MARKET-WIDE, so acting on it would have closed EVERY long position at
    # once, seconds after entry. Enabling an untested mass-liquidation path on
    # the same day it first became capable of firing is not a good trade.
    #
    # Shadow for one session, compare its would-be exits against what actually
    # happened, then decide. Flip to False to let it act.
    # ---------------------------------------------------------------------
    "tier2_shadow_mode": True,

    # Individual rule toggles
    "flow_exhaustion_enabled": True,  # #5: 45 min no sweeps
    "put_call_flip_enabled": True,   # #1: Conviction reversal
    "dark_pool_enabled": True,        # #2: Institutional dump

    # ---------------------------------------------------------------------
    # DISABLED Sep 10 2026 on the shadow session's own evidence.
    #
    # market_tide reads a MARKET-WIDE bullish ratio, so its output is the same
    # number for every open position. It cannot discriminate between them - by
    # construction it either exits nothing or exits the entire book.
    #
    # Sep 10 shadow log, 212 signals over 9 positions in 37 batches:
    #   market_tide_flip     147  (69% of all signals)
    #   put_call_flip         35
    #   dark_pool_reversal    30
    # 17 of the 37 batches signalled 8 or 9 positions AT ONCE. At 09:33:51 and
    # again at 09:34:56, one cycle apart, it called exit on every open long.
    # Live, that is a full liquidation of the book twice in two minutes.
    #
    # Raising the threshold does not fix this. The defect is that a market-wide
    # reading is being used as a PER-POSITION exit. If this signal is worth
    # anything it belongs upstream - as a position-size input or a market-wide
    # entry halt - not as an exit rule. Re-enabling it as an exit without that
    # redesign just reinstates the mass-liquidation path.
    # ---------------------------------------------------------------------
    "market_tide_enabled": False,     # #6: Macro sentiment flip

    # ---------------------------------------------------------------------
    # MINIMUM CONFIDENCE TO ACT ON A TIER 2 EXIT
    #
    # Sep 10: nothing consulted signal.confidence. The dispatcher acted on
    # signal.triggered alone, so a 31%-confidence dark_pool_reversal on INTC
    # would have closed the position exactly like a 95% one. Confidence was
    # computed, logged to tier2_shadow.jsonl, printed in every alert - and
    # consumed by nothing. Same shape as the rule toggles and the startup
    # banner: a number that describes instead of controls.
    #
    # 0.0 preserves the current behaviour exactly (act on every trigger), so
    # enabling the gate is a separate, deliberate decision from wiring it.
    # Today's distribution over 327 signals: min 0.31, p25 0.84, median 0.84,
    # max 0.95 - only 2 below 0.50. So a gate anywhere under ~0.80 is close to
    # a no-op on this data, and there is not yet evidence for where to put it:
    # the confidence-vs-outcome backtest has n=18 closed signalled positions,
    # which is far too few to site a threshold.
    # ---------------------------------------------------------------------
    "tier2_min_exit_confidence": 0.0,

    # Thresholds
    "flow_exhaustion_minutes": 45,    # No activity for X minutes = exit
    "put_call_flip_threshold": 0.55,  # >55% puts for bullish = flip
    "dark_pool_min_notional": 1_000_000,  # $1M threshold for dump
    # Market tide is a MARKET-WIDE reading, so this threshold decides whether
    # every long exits at once. 0.50 is a coin flip — it fired at 29.3% on the
    # first live test and would fire on any mildly soft tape. Requires a
    # decisive flip, not a marginal one.
    "market_tide_flip_threshold": 0.30,

    # Tier 2 may not exit a position younger than this. Prevents an exit rule
    # from closing a trade moments after the entry rules opened it.
    "min_hold_minutes_before_exit": 20,

    # Fall back to ATR if no options trigger
    "fallback_to_atr": True,  # Use ATR target/stop if no other exit
}

# ===========================================================================
# TECHNICAL GATES (Gates 9-11: Price Confirmation for Tier 2)
# ===========================================================================
TECHNICAL_GATES_CONFIG = {
    # Enable technical confirmation gates
    "enabled": True,  # ✅ GATES 9-11 ACTIVE

    # Individual gates
    "gate_9_ma_enabled": True,      # #9: Moving average alignment
    "gate_10_rsi_enabled": True,    # #10: RSI momentum check
    "gate_11_vwap_enabled": True,   # #11: VWAP profitability check

    # Position sizing based on confidence.
    #
    # Sep 8: raised 0.50 -> 0.55 after replacing the gate scoring. The old
    # "0.75 baseline + nudge" formula produced only 0.90-1.00 in live use and
    # rejected nothing, so the floor never bound. Continuous ATR-normalised
    # scoring now spans ~0.00-0.92 (stdev 0.38 vs 0.02), so the floor does real
    # work: it rejects setups that previously scored 0.96 and took full size.
    "position_sizing_enabled": True,  # Scale 0.5x-1.5x by confidence
    "min_confidence_to_trade": 0.55,
    "min_confidence_full_size": 0.85,
}

# ===========================================================================
# PRICE DATA SOURCE
# ===========================================================================
# "uw"       — Unusual Whales OHLC. Same source as the flow data, so bar and
#              alert timestamps come from one clock. Provides the 15m/1h bars
#              the screener's trend gates need, which yfinance covers poorly.
# "yfinance" — previous behaviour, kept as a fallback.
#
# Verified 2026-09-08 against yfinance: prices agree 6/6 within 1%, ATR within
# ~3%. Two bugs were found and fixed getting there — UW returns THREE rows per
# period (pre/regular/post) and mixing them understated ATR by 25-35%, and the
# regular-hours filter means indicator windows must over-request ~4x.
PRICE_SOURCE = "uw"

# ===========================================================================
# CAPACITY — how the position cap allocates slots
# ===========================================================================
# Sep 8: with the cap at 10/10 the bot held TQQQ at 70% confidence while
# turning away SPCX at 94%. The cap was first-come-first-served, so capital was
# allocated by ARRIVAL TIME rather than quality. That was invisible under the
# old gate scoring (everything scored 90-100%, so slot order did not matter);
# it only became visible once confidence actually discriminated.
#
# Rotation is deliberately conservative. Every swap pays spread twice, so a
# too-eager threshold bleeds. The guards below exist to stop it churning:
#   - a wide confidence margin, so only clear upgrades fire
#   - a minimum hold, so fresh positions are not thrashed
#   - winners are protected, since dumping a working position to chase a
#     marginally better signal is exactly the behaviour that loses money
CAPACITY_CONFIG = {
    # Re-enabled 2026-09-08 EOD for Wednesday, after both Sep 8 defects were
    # fixed and regression-tested:
    #   1. unrecorded confidence read as worst-possible -> closed ORCL(96%),
    #      CRWV(100%), NVDA(96%) to buy BE(54%), SKHY(60%), TQQQ(70%).
    #      FIX: a position with no recorded confidence is never a rotation
    #      candidate. Unknown is not worst.
    #   2. rotation ran BEFORE the duplicate/exposure/sizing checks, so FSLR
    #      (73%) was liquidated "to make room" for TSLA — which was then
    #      rejected as already held. FIX: capacity is evaluated LAST, once the
    #      trade is otherwise certain to be placed.
    # The book starts empty Wednesday, so every position will carry a recorded
    # confidence and the comparison finally has data to work with.
    # WATCH the first rotations rather than assuming they are correct.
    "quality_rotation_enabled": True,
    "rotation_margin": 0.15,        # candidate must beat the weakest by 15 pts
    "min_hold_minutes": 30,         # a position is not rotatable before this
    "protect_winners_pct": 1.0,     # never rotate out a position up > +1%
    "max_rotations_per_day": 6,
}

# ===========================================================================
# INSTRUMENT — what the bot actually BUYS
# ===========================================================================
# Sep 8 decision: the bot ANALYSES stocks (gates 9-11 read MA20/RSI/VWAP on the
# underlying, ATR sizing is on the underlying, stop/target levels are underlying
# prices) but was EXECUTING options contracts. That mismatch is why bid-ask
# dominated the results: options cost 1-2% to round trip versus ~0.003% on
# shares.
#
# Unusual Whales option flow remains the SIGNAL. Execution is now equities.
INSTRUMENT_CONFIG = {
    "instrument": "equity",          # "equity" | "option"

    # Dollar notional per entry; share count derived from the live price.
    "position_dollars": 500.0,
    "max_dollars_per_symbol": 1500.0,

    # ---------------------------------------------------------------------
    # FRACTIONAL SHARES.
    #
    # Sizing used int(target_dollars // price), so any stock priced above the
    # dollar target rounded to ZERO shares and was silently skipped. On
    # 2026-09-09 that dropped MU at 90% and 93% confidence ($1,025) and SNDK
    # at 76% ($1,770) — the strategy was structurally unable to trade any
    # large-cap above ~$750 no matter how strong the signal.
    #
    # Buying 1 whole share instead would break risk sizing the other way:
    # one SNDK share is $1,770, or 7% of a $25k account, against a $500
    # target. Fractional keeps the dollar risk constant, which is the whole
    # point of dollar-based sizing.
    #
    # Equities only — options cannot be fractional. min_position_dollars
    # stops dust orders whose spread would swamp the position.
    # ---------------------------------------------------------------------
    "allow_fractional_shares": True,
    "min_position_dollars": 50.0,
    "fractional_precision": 4,

    # Long-only. Bearish flow on a symbol we HOLD is an exit signal; bearish
    # flow on a symbol we do not hold is skipped rather than shorted, since
    # shorting needs margin and is restricted on retail Robinhood accounts.
    "allow_short": False,
}

# ===========================================================================
# OPTION-FLOW SIGNAL QUALITY FILTER
# ===========================================================================
# Added Sep 8 to stop the bot BUYING deep-ITM LEAPs whose spread cost ~20x the
# edge. With execution moved to equities that cost argument no longer applies,
# but the filter is KEPT for a different and stronger reason:
#
#     the contract an institution chooses reveals their TIME HORIZON.
#
# A Dec-2028 LEAP says nothing about the next four hours. A 30-day near-the-
# money call is a short-term directional bet — the horizon this bot trades.
# So DTE/delta now screen SIGNAL RELEVANCE rather than tradeability. The
# spread/premium gates are retained as a liquidity proxy for the name.
# ===========================================================================
# Sep 8: the bot executed deep-ITM LEAPs (AAPL Dec-2028 $100C with the stock
# at $316; GOOGL Dec-2027 $480P). Round-trip bid-ask came to -$4,350 against
# +$187 of directional P&L — spread cost ~20x the edge.
#
# Cause: premium >= $100K structurally selects EXPENSIVE contracts, which
# means long-dated and deep ITM. Measured on live flow, 36 of 39 Phase-1
# survivors were >120 DTE. Phase 1's percentage spread gate cannot catch this:
# AAPL's $4.60 spread on a $226 contract is only 2.0%.
#
# Values below were calibrated against live flow: ~5 tradeable contracts per
# 200-alert fetch, round-trip cost $15-90 per 3 contracts (was $1,110-1,380).
CONTRACT_FILTER_CONFIG = {
    "enabled": True,
    "min_dte": 2,             # skip 0DTE lottery tickets
    "max_dte": 60,            # skip LEAPs — this is the binding gate
    "min_abs_delta": 0.20,    # skip far OTM
    "max_abs_delta": 0.80,    # skip deep ITM (no gamma, huge premium)
    "max_spread_abs": 0.35,   # DOLLAR cap — what percentage gates miss
    "max_spread_pct": 0.08,
    "max_premium": 40.0,      # caps capital and round-trip cost per contract
    "min_gamma": 0.0005,
    "max_cost_to_move": 0.50, # round-trip spread vs option move per 1 ATR
}

# Alerts fetched per cycle. Raised from 50: the contract filter is selective
# (~3% of Phase-1 survivors), so a larger pool is needed to find enough
# tradeable contracts each cycle.
ALERTS_PER_CYCLE = 200

# ===========================================================================
# EXECUTION SAFEGUARDS (Phase 2.5)
# ===========================================================================
EXECUTION_SAFEGUARDS_CONFIG = {
    # Max bid-ask spread (as %) before rejecting order.
    #
    # BLOCKER FIX: this was 0.05 (5%) while Phase 1 admitted spreads up to 15%.
    # Alerts between 5% and 15% (e.g. HD at 11.68%, CAR at 13.68%) passed the
    # filter, were counted as "approved", then were unconditionally rejected at
    # execution — a silent funnel loss that inflated the approval numbers.
    # Both stages now read this single value.
    "max_bid_ask_spread_pct": 0.15,  # 15% — matches Phase1AlertFilter

    # Dynamic stop sizing (ATR-based)
    # Calibrated Sep 9 to the INTRADAY holding period. Measured over ~250
    # sessions x 10 liquid names, probability a barrier k x ATR from the open
    # is touched the same session: 0.50->66.6%, 0.75->35.7%, 1.00->19.4%,
    # 1.50->5.3%, 2.50->0.3%.
    #
    # The old 1.5/2.5 was multi-day sizing on a book that flattens at 15:45,
    # so the target was reachable on 1 session in 333 and no stop or target
    # ever fired in the bot's entire history. These values make the barriers
    # actually bind while staying above intraday noise. Widen them again if
    # the strategy ever holds overnight.
    "stop_atr_multiplier": 0.75,   # ~36% same-session touch
    "target_atr_multiplier": 1.0,  # ~19% same-session touch

    # Time-based controls
    "max_hold_minutes": 240,  # 4 hours max per position
    "eod_force_close_time": time(15, 45),  # 3:45 PM EST (liquidate all)
}

# ===========================================================================
# ROBINHOOD MCP (Phase 2)
# ===========================================================================
ROBINHOOD_MCP_CONFIG = {
    # MCP server details (from environment or defaults)
    "mcp_server_url": os.getenv("RH_MCP_URL", "http://localhost:8000"),

    # OAuth credentials (loaded from environment)
    "client_id": os.getenv("RH_CLIENT_ID"),
    "refresh_token": os.getenv("RH_REFRESH_TOKEN"),

    # Request timeouts
    "request_timeout": 30,  # seconds

    # Retry settings
    "max_retries": 3,
    "retry_backoff_seconds": 1,
}

# ===========================================================================
# UNUSUAL WHALES API (Phase 2)
# ===========================================================================
UNUSUAL_WHALES_CONFIG = {
    # API endpoint
    "api_url": os.getenv("UW_API_URL", "https://api.unusualwhales.com/v1"),

    # API key (required for live)
    "api_key": os.getenv("UW_API_KEY"),

    # Polling interval (seconds)
    "poll_interval": 300,  # 5 minutes

    # Filter by minimum notional value ($ millions)
    "min_notional_usd_m": 1.0,  # $1M minimum

    # Filter by option types
    "option_types": ["CALL", "PUT"],

    # Symbols to monitor
    "symbols": ["SPX", "NDX", "RUT"],
}

# ===========================================================================
# DISCORD ALERTS (Phase 2)
# ===========================================================================
DISCORD_CONFIG = {
    # Webhook URL for alerts
    "webhook_url": os.getenv("DISCORD_WEBHOOK_URL"),

    # Enable/disable alerts
    "enabled": bool(os.getenv("DISCORD_WEBHOOK_URL")),

    # Alert types to post
    "alert_types": {
        "uw_signal": True,  # Unusual Whales flow alerts
        "phase1_filter": True,  # Phase 1 filter results
        "phase2_trade": True,  # Trade execution notices
        "phase3_exit": True,  # Position exits (profit/loss)
        "errors": True,  # Error/warning messages
    },
}

# ===========================================================================
# LOGGING
# ===========================================================================
LOGGING_CONFIG = {
    "level": "INFO",  # DEBUG, INFO, WARNING, ERROR
    "format": "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    "log_file": "uw_bot.log",
}

# ===========================================================================
# FEATURE FLAGS
# ===========================================================================
FEATURES = {
    # Phase 1: Unusual Whales alert filtering
    "phase1_enabled": True,

    # Phase 2: Execution with Robinhood MCP
    "phase2_enabled": True,

    # Phase 2.5: Hotfixes (ATR stops, NBBO validation)
    "phase25_hotfixes_enabled": True,

    # Phase 3B: Sentiment debate engine (requires Redis)
    "phase3b_sentiment_enabled": SENTIMENT_CONFIG["sentiment_enabled"],
    "phase3b_debate_enabled": DEBATE_ENGINE_CONFIG["enabled"],
}

# ===========================================================================
# DEFAULTS & CONSTANTS
# ===========================================================================
DEFAULT_POSITION_SIZE = 1  # contracts
MAX_OPEN_POSITIONS = 10
MAX_DAILY_LOSS_PCT = -5.0  # Circuit breaker: stop if down 5%
MAX_POSITION_LOSS_PCT = -2.0  # Exit position if down 2%

# ===========================================================================
# Helper functions
# ===========================================================================


def is_mock_mode() -> bool:
    """Check if running in mock mode"""
    return EXECUTION_MODE["mock_mode"]


def is_sentiment_enabled() -> bool:
    """Check if sentiment service is enabled"""
    return SENTIMENT_CONFIG["sentiment_enabled"]


def is_debate_enabled() -> bool:
    """Check if debate engine is enabled"""
    return DEBATE_ENGINE_CONFIG["enabled"]


def get_execution_mode_name() -> str:
    """Get human-readable execution mode"""
    if is_mock_mode():
        return "MOCK (Testing)"
    elif EXECUTION_MODE["paper_trading"]:
        return "PAPER (Simulated)"
    else:
        return "LIVE (Real Money)"


# ===========================================================================
# Validation
# ===========================================================================

def validate_config() -> bool:
    """Validate configuration before startup"""
    errors = []

    # Check required environment variables for live mode
    if not is_mock_mode() and not EXECUTION_MODE["log_orders_only"]:
        if not ROBINHOOD_MCP_CONFIG["client_id"]:
            errors.append("RH_CLIENT_ID not set (required for live trading)")
        if not ROBINHOOD_MCP_CONFIG["refresh_token"]:
            errors.append("RH_REFRESH_TOKEN not set (required for live trading)")

    # Check UW API key
    if not UNUSUAL_WHALES_CONFIG["api_key"] and not is_mock_mode():
        errors.append("UW_API_KEY not set (required for UW alerts)")

    # Check sentiment prerequisites
    if is_sentiment_enabled():
        if not SENTIMENT_CONFIG["redis_host"]:
            errors.append("Redis host not configured (required for sentiment)")

    # Log results
    if errors:
        print("❌ CONFIGURATION ERRORS:")
        for error in errors:
            print(f"  - {error}")
        return False
    else:
        print(f"✅ Configuration valid (Mode: {get_execution_mode_name()})")
        return True


if __name__ == "__main__":
    # Print config summary
    print("\n" + "=" * 80)
    print("UNUSUAL WHALES BOT CONFIGURATION")
    print("=" * 80)
    print(f"Execution Mode: {get_execution_mode_name()}")
    print(f"Phase 1 (Filter): {'ENABLED' if FEATURES['phase1_enabled'] else 'DISABLED'}")
    print(f"Phase 2 (MCP): {'ENABLED' if FEATURES['phase2_enabled'] else 'DISABLED'}")
    print(f"Phase 2.5 (Hotfixes): {'ENABLED' if FEATURES['phase25_hotfixes_enabled'] else 'DISABLED'}")
    print(f"Phase 3B (Debate): {'ENABLED' if FEATURES['phase3b_debate_enabled'] else 'DISABLED'}")
    print(f"Phase 3B (Sentiment): {'ENABLED' if FEATURES['phase3b_sentiment_enabled'] else 'DISABLED'}")
    print("=" * 80 + "\n")

    # Validate
    validate_config()
