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
    "mock_mode": True,

    # Use Robinhood paper trading (real account, simulated capital)
    "paper_trading": False,

    # Log what would happen without actually executing
    "log_orders_only": True,

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
# EXECUTION SAFEGUARDS (Phase 2.5)
# ===========================================================================
EXECUTION_SAFEGUARDS_CONFIG = {
    # Max bid-ask spread (as %) before rejecting order
    "max_bid_ask_spread_pct": 0.05,  # 5%

    # Dynamic stop sizing (ATR-based)
    "stop_atr_multiplier": 1.5,  # 1.5x ATR for stop
    "target_atr_multiplier": 2.5,  # 2.5x ATR for target

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
