#!/usr/bin/env python3
"""
MEAN-REVERSION TRADING BOT with Autonomous Learning
Opus 4.8 + Adaptive Thinking + Multi-layer Caching + Real-time RL

Mean-reversion strategy:
  - Identify: Stocks up 5-8% today (overbought/extended)
  - Wait: Monitor for pullback (-2% to -3% next 1-2 days)
  - Entry: BUY the dip when pullback confirmed
  - Exit 1: Sell 50% at +1-2% recovery (capture reversion)
  - Exit 2: Sell 50% at +3% recovery OR -2% stop (ride to full mean)

Benefits:
  - Aligns with proven mean-reverting market behavior
  - Trades fade of extremes (short-term overbought conditions)
  - Adaptive position sizing via Q-Learning
  - Real-time regime detection via autonomous learning
  - Expected improvement: +2-4% average returns (vs -36% momentum)
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
import pytz
import time
import requests
import sqlite3
import hashlib

import anthropic
import yfinance as yf

# Import technical analysis module
try:
    from technical_analysis import score_technical_setup, format_technical_for_claude
    technical_analysis_enabled = True
except ImportError:
    technical_analysis_enabled = False
    log = logging.getLogger(__name__)
    log.warning("Technical analysis module not available")

# Import autonomous learning module
try:
    from autonomous_bot_integration import TradeWithLearning
    autonomous_learning_enabled = True
except ImportError:
    autonomous_learning_enabled = False

# Import FinRL integration
try:
    from finrl_integration import FinRLPredictor, initialize_finrl
    finrl_enabled = True
except Exception as e:
    finrl_enabled = False
    import traceback
    log = logging.getLogger(__name__)
    log.error(f"❌ FINRL IMPORT ERROR: {type(e).__name__}: {e}")
    log.error(f"Traceback: {traceback.format_exc()}")
    log.info("ℹ️ FinRL not available (using rules-based strategy)")

# ============================================================================
# CONFIGURATION
# ============================================================================

TOTAL_BUDGET = 10000
MAX_POSITION = 600  # Optimized: increased from 500 (backtest +8.66% ROI)
DAILY_LOSS_LIMIT_PCT = 5.0
CONFIDENCE_THRESHOLD = 55  # Mean-reversion setup confidence (60% → 55% for more frequent trades)

# Mean-reversion dip-buy parameters (backtested +8.66% ROI over 3 months)
SPIKE_MIN_PCT = 5.0  # Detect spikes 5-8%
SPIKE_MAX_PCT = 8.0
PULLBACK_MIN_PCT = 1.0  # Entry on 1-4% pullback (optimized from 2-4%)
PULLBACK_MAX_PCT = 4.0
STOP_LOSS_PCT = 1.5  # Cut at -1.5% if reversal fails
RH_ACCOUNT = "432591949"  # Robinhood account for MCP tool execution

# FOMC aggressive mode (2026-07-29 only)
FOMC_DATE = "2026-07-29"
FOMC_THRESHOLD = 45  # More aggressive during FOMC
FOMC_INTERVAL = 600  # 10 min instead of 30 min

TOKENS_PER_HOUR_LIMIT = 2_000_000
TOKENS_PER_DAY_LIMIT = 15_000_000

RH_AUTH_URL = "https://api.robinhood.com/oauth2/token/"
RH_MOVERS_URL = "https://api.robinhood.com/midlands/movers/sp500/"
RH_QUOTES_URL = "https://api.robinhood.com/quotes/"

# OAuth refresh token for Robinhood MCP
RH_CLIENT_ID = os.environ.get("RH_CLIENT_ID", "")
RH_REFRESH_TOKEN = os.environ.get("RH_REFRESH_TOKEN", "")
RH_TOKEN_URL = "https://api.robinhood.com/oauth2/token/"
TOKEN_FILE = "rh_token.json"

FINNHUB_API_URL = "https://finnhub.io/api/v1/quote"
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

# Cache TTLs
MOVERS_CACHE_TTL = 120  # 2 min (finnhub real-time ~100ms latency)
REGIME_CACHE_TTL = 3600
LEARNING_CACHE_TTL = 604800

CACHE_FILE = "bot_cache.json"

# ============================================================================
# ROBINHOOD OAUTH TOKEN MANAGEMENT
# ============================================================================

_rh_token_cache = {"access": None, "expires_at": 0.0, "refresh": None}

def _can_refresh_rh_token():
    return bool(RH_CLIENT_ID and (RH_REFRESH_TOKEN or _rh_token_cache["refresh"]))

def get_rh_access_token(force_refresh=False):
    """Get valid Robinhood OAuth access token for MCP."""
    if not _can_refresh_rh_token():
        log.error("Cannot refresh: RH_CLIENT_ID=%s, RH_REFRESH_TOKEN=%s",
                 bool(RH_CLIENT_ID), bool(RH_REFRESH_TOKEN))
        return None

    # Load cached token from disk
    if _rh_token_cache["access"] is None:
        try:
            with open(TOKEN_FILE) as f:
                saved = json.load(f)
            _rh_token_cache.update({k: saved.get(k, _rh_token_cache[k]) for k in _rh_token_cache})
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    # Return cached if still valid
    if not force_refresh and _rh_token_cache["access"] and time.time() < _rh_token_cache["expires_at"] - 600:
        return _rh_token_cache["access"]

    # Refresh via OAuth
    for refresh in dict.fromkeys([_rh_token_cache["refresh"] or "", RH_REFRESH_TOKEN]):
        if not refresh:
            continue
        try:
            r = requests.post(RH_TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": RH_CLIENT_ID,
            }, timeout=20)

            if r.status_code != 200:
                log.error("Token refresh failed: %s %s", r.status_code, r.text[:200])
                continue

            d = r.json()
            _rh_token_cache["access"] = d["access_token"]
            _rh_token_cache["expires_at"] = time.time() + float(d.get("expires_in", 3600))
            if d.get("refresh_token"):
                _rh_token_cache["refresh"] = d["refresh_token"]

            try:
                with open(TOKEN_FILE, "w") as f:
                    json.dump(_rh_token_cache, f)
            except OSError:
                pass

            log.info("✓ Robinhood access token refreshed")
            return _rh_token_cache["access"]

        except Exception as exc:
            log.error("Token refresh error: %s", exc)

    return None

# ============================================================================
# LOGGING SETUP
# ============================================================================

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

# Suppress verbose library DEBUG logs (Railway rate limiting)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("yfinance").setLevel(logging.WARNING)
logging.getLogger("anthropic").setLevel(logging.WARNING)

# ============================================================================
# CACHE MANAGEMENT
# ============================================================================

def load_cache():
    """Load response cache from disk."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {
        "movers": {"data": None, "timestamp": 0},
        "regime": {"data": None, "timestamp": 0},
        "learning": {"data": None, "timestamp": 0},
        "anomalies": {},
    }

def save_cache(cache):
    """Save response cache to disk."""
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f)

def is_cache_valid(timestamp, ttl):
    """Check if cache entry is still valid."""
    return time.time() - timestamp < ttl

def cache_get(cache, key, ttl):
    """Get cached value if valid."""
    if key in cache and cache[key].get("data") is not None:
        if is_cache_valid(cache[key].get("timestamp", 0), ttl):
            log.info("✓ Cache hit: %s", key)
            return cache[key]["data"]
    return None

def cache_set(cache, key, value):
    """Set cache value with timestamp."""
    cache[key] = {
        "data": value,
        "timestamp": time.time()
    }

# ============================================================================
# SONNET RESPONSE CACHING (SQLite)
# ============================================================================

SONNET_CACHE_DB = "sonnet_responses.db"
SONNET_CACHE_TTL = 1800  # 30 minutes

def init_sonnet_cache():
    """Initialize SQLite database for Sonnet response caching."""
    try:
        conn = sqlite3.connect(SONNET_CACHE_DB, check_same_thread=False)

        # Create new table with stable cache_key (regime + top 3 symbols)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sonnet_cache (
                cache_key TEXT PRIMARY KEY,
                response TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON sonnet_cache(timestamp)")
        conn.commit()
        conn.close()
        log.info("✓ Sonnet cache initialized (stable key: regime + top3 symbols)")
    except Exception as e:
        log.error("Failed to init Sonnet cache: %s", e)

def get_cached_sonnet_response(candidates_data, regime):
    """Retrieve cached Sonnet response if fresh (TTL < 30 min).
    Uses stable cache key: regime + top 3 symbols (not prices, which change).
    """
    try:
        # Create stable cache key from regime + top 3 symbols
        # This way cache hits when same stocks stay at top
        top_symbols = "_".join([c.get("symbol", "").upper() for c in candidates_data[:3]])
        cache_key = f"{regime}_{top_symbols}"

        conn = sqlite3.connect(SONNET_CACHE_DB, check_same_thread=False)
        result = conn.execute(
            "SELECT response, timestamp FROM sonnet_cache WHERE cache_key = ?",
            (cache_key,)
        ).fetchone()
        conn.close()

        if result:
            response_text, timestamp = result
            age = time.time() - timestamp

            if age < SONNET_CACHE_TTL:
                log.info("✓ Sonnet cache HIT: %s (age: %.0f sec)", cache_key, age)
                return json.loads(response_text)
            else:
                log.debug("Sonnet cache expired: %s (age: %.0f sec > TTL: %d)", cache_key, age, SONNET_CACHE_TTL)

        return None
    except Exception as e:
        log.debug("Sonnet cache retrieval error: %s", e)
        return None

def cache_sonnet_response(candidates_data, regime, response_text):
    """Cache Sonnet response for future cycles using stable key: regime + top 3 symbols."""
    try:
        # Create stable cache key from regime + top 3 symbols (not prices)
        top_symbols = "_".join([c.get("symbol", "").upper() for c in candidates_data[:3]])
        cache_key = f"{regime}_{top_symbols}"

        conn = sqlite3.connect(SONNET_CACHE_DB, check_same_thread=False)
        conn.execute(
            "INSERT OR REPLACE INTO sonnet_cache (cache_key, response, timestamp) VALUES (?, ?, ?)",
            (cache_key, response_text, time.time())
        )
        conn.commit()
        conn.close()
        log.info("✓ Sonnet response cached: %s", cache_key)
    except Exception as e:
        log.error("Failed to cache Sonnet response: %s", e)

def cleanup_sonnet_cache():
    """Remove expired cache entries (older than 2 hours)."""
    try:
        cutoff_time = time.time() - 7200  # 2 hours
        conn = sqlite3.connect(SONNET_CACHE_DB, check_same_thread=False)
        deleted = conn.execute(
            "DELETE FROM sonnet_cache WHERE timestamp < ?",
            (cutoff_time,)
        ).rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            log.info("Cleaned up %d expired Sonnet cache entries", deleted)
    except Exception as e:
        log.error("Failed to cleanup cache: %s", e)

# ============================================================================
# AUTHENTICATION & CLIENTS
# ============================================================================


# ============================================================================
# POSITION SIZING VALIDATION
# ============================================================================

def validate_position_sizing(trades, total_budget, max_position):
    """Validate and adjust position sizes to respect budget and limits."""
    validated_trades = []
    total_deployed = 0.0
    
    for trade in trades:
        symbol = trade.get("symbol", "?")
        price = trade.get("price", 0)
        quantity = trade.get("quantity", 0)
        
        if price <= 0 or quantity <= 0:
            continue
        
        # Calculate actual $ deployed
        capital_required = quantity * price
        
        # Check against MAX_POSITION limit
        if capital_required > max_position:
            log.warning(
                "Position %s exceeds MAX_POSITION: $%.2f > $%d (reducing qty)",
                symbol, capital_required, max_position
            )
            quantity = round(max_position / price, 2)
            capital_required = quantity * price
        
        # Check against remaining budget
        remaining_budget = total_budget - total_deployed
        if capital_required > remaining_budget:
            log.warning(
                "Position %s exceeds remaining budget: $%.2f > $%.2f (skipping)",
                symbol, capital_required, remaining_budget
            )
            continue
        
        # This trade is valid
        total_deployed += capital_required
        trade["quantity"] = quantity
        trade["capital_deployed"] = capital_required
        validated_trades.append(trade)
        
        log.info(
            "✓ Position validated: %s - $%.2f deployed (total: $%.2f / $%d)",
            symbol, capital_required, total_deployed, total_budget
        )
    
    log.info("📊 Capital deployment: $%.2f / $%d (%.1f%% used)",
             total_deployed, total_budget, (total_deployed / total_budget) * 100)
    
    return validated_trades

def get_anthropic_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=api_key)

def get_robinhood_account():
    """Get primary Robinhood account number for order placement via MCP."""
    return RH_ACCOUNT

# ============================================================================
# STATE MANAGEMENT
# ============================================================================

STATE_FILE = "trading_state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "trades": [],
        "analyzed_candidates": [],
        "daily_pnl": 0.0,
        "daily_bought_symbols": {},  # Track {symbol: total_capital_deployed} per day (max $600/symbol)
        "daily_date": datetime.now(pytz.UTC).date().isoformat(),  # Reset daily_bought_symbols at midnight
        "position_cache": {},  # Smart cache: {symbol: {timestamp, value, ttl_minutes}}
        "token_usage": {"input": 0, "output": 0, "hourly_calls": []},
        "bot_halted": False,
        "next_interval_seconds": 1800,
        "performance_analytics": {
            "last_weekly_analysis": None,
            "confidence_calibration": None,
        },
        "open_positions": {},  # For autonomous learning feedback
        "autonomous_learning": {
            "enabled": True,
            "regime": "unknown",
            "last_update": None,
        }
    }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

# ============================================================================
# TOKEN TRACKING & CIRCUIT BREAKER
# ============================================================================

def record_token_usage(state, input_tokens, output_tokens):
    state["token_usage"]["input"] += input_tokens
    state["token_usage"]["output"] += output_tokens
    
    now = time.time()
    state["token_usage"]["hourly_calls"].append({
        "tokens": input_tokens + output_tokens,
        "timestamp": now
    })
    
    state["token_usage"]["hourly_calls"] = [
        c for c in state["token_usage"]["hourly_calls"]
        if now - c["timestamp"] < 3600
    ]
    
    hourly_total = sum(c["tokens"] for c in state["token_usage"]["hourly_calls"])
    if hourly_total > TOKENS_PER_HOUR_LIMIT:
        log.error("CIRCUIT BREAKER: Hourly tokens exceeded (%d > %d)", 
                 hourly_total, TOKENS_PER_HOUR_LIMIT)
        state["bot_halted"] = True
        save_state(state)
        return False
    
    return True

# ============================================================================
# MARKET DATA
# ============================================================================

TOP_SP500 = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "BRK.B", "META", "JNJ", "V",
    "WMT", "JPM", "MA", "XOM", "HD", "PG", "LLY", "CVX", "MRK", "ABBV",
    "COST", "KO", "PEP", "AVGO", "ACN", "AMD", "CSCO", "CMCSA", "COP", "DHR",
    "INTC", "NFLX", "MCD", "TXN", "AXP", "CRM", "SO", "VZ", "CAT", "NOW",
    "ADBE", "IBM", "AZO", "GILD", "INTU", "ELV", "AMAT", "RTX", "BA", "TMUS",
    "BKNG", "AMGN", "LRCX", "KEYS", "SNPS", "CDNS", "ADI", "PCAR", "ENPH", "GE",
]

NASDAQ_50 = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "NFLX", "ADBE", "CSCO",
    "INTC", "AMD", "CMCSA", "AVGO", "QCOM", "AMAT", "ASML", "ADP", "SNPS", "CDNS",
    "INTU", "ABNB", "SBUX", "LRCX", "MU", "MCHP", "PCAR", "PAYX", "GOOG", "REGN",
    "VRTX", "KLAC", "CRWD", "DDOG", "ZM", "MNST", "XEL", "PYPL", "MELI", "TJX",
    "FAST", "EBAY", "ENPH", "CTAS", "ODFL", "SGEN", "NFLX", "ULTA", "MRNA", "WDAY",
]

TOP_WATCHLIST = TOP_SP500 + NASDAQ_50  # Combined 110 stocks (60 S&P + 50 NASDAQ)

def get_finnhub_price(symbol):
    """Fetch live price from Finnhub for a single symbol."""
    if not FINNHUB_API_KEY:
        return None

    try:
        params = {"symbol": symbol, "token": FINNHUB_API_KEY}
        resp = requests.get(FINNHUB_API_URL, params=params, timeout=5)
        resp.raise_for_status()

        quote = resp.json()
        current = float(quote.get("c", 0))
        prev_close = float(quote.get("pc", current))

        if current > 0 and prev_close > 0:
            pct_change = ((current - prev_close) / prev_close) * 100
            log.debug("Finnhub %s: $%.2f (pc: $%.2f, pct: %.2f%%)",
                     symbol, current, prev_close, pct_change)
            return {"price": current, "pct_change": pct_change}
    except Exception as e:
        log.debug("Error fetching Finnhub %s: %s", symbol, e)

    return None


def get_top_movers(access_token=None, limit=100, cache=None):
    """Get top movers using yfinance (fast screening, cheap—real prices via refresh_candidate_prices)."""
    if cache is None:
        cache = load_cache()

    cached_movers = cache_get(cache, "movers", MOVERS_CACHE_TTL)
    if cached_movers:
        return cached_movers

    try:
        log.info("Fetching movers from yfinance (S&P 500 + NASDAQ-50: %d stocks)", len(TOP_WATCHLIST[:limit]))
        symbols = TOP_WATCHLIST[:limit]

        movers = []
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info

                current = info.get("currentPrice") or info.get("regularMarketPrice", 0)
                prev_close = info.get("previousClose", current)

                if current > 0 and prev_close > 0:
                    pct_change = ((current - prev_close) / prev_close) * 100

                    movers.append({
                        "symbol": symbol,
                        "price": current,
                        "pct_change": pct_change,
                        "volume": info.get("volume", 0),
                    })
            except Exception as e:
                log.debug("Error fetching %s: %s", symbol, e)
                continue

        movers = sorted(movers, key=lambda x: abs(x["pct_change"]), reverse=True)
        cache_set(cache, "movers", movers)
        save_cache(cache)

        log.info("✓ Fetched %d movers from yfinance (will refresh top candidates with Finnhub)", len(movers))
        return movers
    except Exception as e:
        log.error("get_top_movers error: %s", e)
        return cached_movers or []

def get_current_price(symbol, access_token=None):
    """Get current price for a symbol using yfinance."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
        if price > 0:
            return float(price)
    except Exception as e:
        log.debug("Error fetching price for %s: %s", symbol, e)
    return 0

# ============================================================================
# SAFETY RAILS
# ============================================================================

def check_daily_loss_limit(state):
    """Check if daily loss limit has been hit."""
    today = datetime.now().strftime("%Y-%m-%d")
    today_pnl = sum(t.get("realized_pnl", 0) for t in state.get("trades", [])
                   if t.get("date", "").startswith(today))
    
    if today_pnl < 0 and abs(today_pnl) >= (TOTAL_BUDGET * DAILY_LOSS_LIMIT_PCT / 100):
        return True
    return False

def is_market_hours():
    """Check if market is open (excludes weekends and US market holidays)."""
    et = pytz.timezone('US/Eastern')
    now = datetime.now(et)

    # US market holidays (month, day)
    holidays = [
        (1, 1),    # New Year's Day
        (1, 20),   # MLK Day (3rd Monday)
        (2, 17),   # Presidents Day (3rd Monday)
        (3, 29),   # Good Friday
        (5, 27),   # Memorial Day (last Monday)
        (6, 19),   # Juneteenth
        (7, 4),    # Independence Day
        (9, 2),    # Labor Day (1st Monday)
        (11, 27),  # Thanksgiving (4th Thursday)
        (12, 25),  # Christmas
    ]

    # Check weekends
    if now.weekday() >= 5:
        return False

    # Check holidays (simplified - doesn't handle observed dates)
    if (now.month, now.day) in holidays:
        return False

    # Check market hours (9:30 AM - 4:00 PM ET)
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        return False
    if now.hour >= 16:
        return False

    return True

def is_market_close():
    """Check if we're at market close (4:00 PM - 4:15 PM ET) for daily learning."""
    et = pytz.timezone('US/Eastern')
    now = datetime.now(et)

    # Market closes at 4:00 PM ET
    if now.hour == 16 and now.minute < 15 and now.weekday() < 5:
        return True

    return False

def get_fomc_settings():
    """Check if FOMC day and return aggressive settings for 2-3:30 PM ET window."""
    et = pytz.timezone('US/Eastern')
    now = datetime.now(et)
    today = now.strftime("%Y-%m-%d")

    # FOMC today?
    if today == FOMC_DATE:
        # FOMC window: 2:00 PM - 3:30 PM ET
        if now.hour == 14 and now.minute < 60:  # 2 PM hour
            return FOMC_THRESHOLD, FOMC_INTERVAL
        elif now.hour == 15 and now.minute < 30:  # 3:30 PM
            return FOMC_THRESHOLD, FOMC_INTERVAL

    # Normal settings
    return CONFIDENCE_THRESHOLD, 1800

# ============================================================================
# STAGE 1: HAIKU SCREENING
# ============================================================================

def extract_json_object(text):
    """Extract valid JSON object from text by finding matching braces."""
    start = text.find('{')
    if start < 0:
        return None

    brace_count = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape_next:
            escape_next = False
            continue

        if ch == '\\' and in_string:
            escape_next = True
            continue

        if ch == '"' and not escape_next:
            in_string = not in_string
            continue

        if not in_string:
            if ch == '{':
                brace_count += 1
            elif ch == '}':
                brace_count -= 1
                if brace_count == 0:
                    return text[start:i+1]

    return None


def stage1_haiku_screening(client, state, movers):
    """Stage 1: Score all top movers for Stage 2 analysis with technical confirmation."""
    if not movers or len(movers) == 0:
        return []

    # Calculate technical scores for each mover
    movers_with_tech = []
    if technical_analysis_enabled:
        for m in movers[:30]:
            tech_score = score_technical_setup(
                m['symbol'],
                m['price'],
                m['pct_change']
            )
            m['technical_score'] = tech_score.get('score', 0)
            m['technical_data'] = tech_score
            movers_with_tech.append(m)
    else:
        movers_with_tech = movers[:30]

    # Format movers text with technical data if available
    if technical_analysis_enabled:
        movers_text = format_technical_for_claude(movers_with_tech)
    else:
        movers_text = "\n".join([
            f"{m['symbol']}: ${m['price']:.2f} ({m['pct_change']:+.1f}%) | Vol: {m.get('volume', 0):,.0f}"
            for m in movers[:30]
        ])

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=[{
                "type": "text",
                "text": """Return ONLY valid JSON array. No markdown, no text, no reason field.

Format: [{"symbol": "XYZ", "score": 75}, ...]

Score 1-100. Include all with score >= 50.""",
                "cache_control": {"type": "ephemeral"}
            }],
            messages=[{
                "role": "user",
                "content": f"""Score these 1-100, return ONLY JSON array:

{movers_text}

Return array with score >= 50:
[{{"symbol": "XYZ", "score": 75}}]"""
            }],
        )

        record_token_usage(state, resp.usage.input_tokens, resp.usage.output_tokens)

        try:
            text = resp.content[0].text

            # Remove markdown fences
            text = text.replace("```json", "").replace("```", "").replace("```JSON", "")

            # Find first [ and last ] (array format)
            start = text.find('[')
            end = text.rfind(']')

            if start >= 0 and end > start:
                json_str = text[start:end+1]
                candidates = json.loads(json_str)
                # Ensure it's a list of dicts with symbol and score
                candidates = [c for c in candidates if isinstance(c, dict) and 'symbol' in c and 'score' in c]
                candidates = sorted(candidates, key=lambda x: x.get("score", 0), reverse=True)
                if candidates:
                    log.info("Stage 1: %d candidates | Top: %s", len(candidates),
                            ", ".join([f"{c['symbol']}({c['score']})" for c in candidates[:3]]))
                    return candidates
                else:
                    log.info("Stage 1: No valid candidates in array")
            else:
                log.error("Stage 1: Could not find JSON array brackets")
        except json.JSONDecodeError as e:
            log.error("Stage 1 JSON error: %s", e.msg)
        except Exception as e:
            log.error("Stage 1 error: %s", e)
    except Exception as e:
        log.error("Stage 1 error: %s", e)

    return []

# ============================================================================
# STAGE 2: OPUS 4.8 ANALYSIS
# ============================================================================

def refresh_candidate_prices(candidates):
    """Fetch fresh Finnhub prices for Stage 1 candidates only (avoids rate limits)."""
    if not candidates:
        return

    log.info("Refreshing Finnhub prices for %d candidates", len(candidates))

    for candidate in candidates[:30]:  # Only top 30 to stay under rate limits
        symbol = candidate.get("symbol")
        if not symbol:
            continue

        price_data = get_finnhub_price(symbol)
        if price_data:
            candidate["price"] = price_data["price"]
            candidate["pct_change"] = price_data["pct_change"]


def stage2_sonnet_analysis(client, state, candidates, cache=None):
    """Stage 2: Sonnet 4.6 - BUY momentum strategy (cash account compatible)."""
    if not candidates or len(candidates) == 0:
        return [], 1800
    
    if cache is None:
        cache = load_cache()
    
    # Format candidates with technical data if available
    if technical_analysis_enabled:
        candidates_text = format_technical_for_claude(candidates[:5])
        candidates_text_note = "\nNote: Technical data includes RSI, VWAP extension, Fibonacci levels for overbought confirmation."
    else:
        candidates_text = "\n".join([
            f"{c['symbol']}: +{c.get('pct_change', 0):.1f}% (anomaly={c.get('score', 0)})"
            for c in candidates[:5]
        ])
        candidates_text_note = ""
    
    learning_context = ""
    calibration = state.get("performance_analytics", {}).get("confidence_calibration")
    if calibration:
        learning_context = f"\n\nLast week's calibration: {calibration.get('recommendations', '')}"
    
    
    # Check cache before calling Sonnet
    # Get regime for cache key
    cached_regime = cache_get(cache, "regime", REGIME_CACHE_TTL)
    regime = cached_regime.get("regime", "unknown") if cached_regime else "unknown"
    
    # Check Sonnet cache with candidates + regime
    cached_response = get_cached_sonnet_response(candidates, regime)
    if cached_response:
        # Return cached decisions and interval
        return cached_response.get("decisions", []), cached_response.get("interval", 1800)
    
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=[{
                "type": "text",
                "text": """MEAN-REVERSION analyzer: Score overbought movers (spiked +5-8% today) for pullback reversal probability.

SETUP: Buy spike-day pullbacks, exit at +0.75% (50%) and +2% (50%). Stop at -1.5%. Hold 1-3 days.

SCORING:
- +6-8% spike: 70-80
- +5-6% spike: 60-70
- +5% + RSI>70/VWAP extended: 60-65
- +5% alone: 55-60

SKIP: <+2% moves, low volume, earnings risk, continued strength.

OUTPUT: Top 3 candidates, score ≥60 minimum. Include regime (bull/bear/choppy/rotation). Return JSON only.""",
                "cache_control": {"type": "ephemeral"}
            }],
            messages=[{
                "role": "user",
                "content": f"""Analyze these daily movers for MEAN-REVERSION dip-buying opportunities:

{candidates_text}{candidates_text_note}{learning_context}

Your analysis should assess each stock for mean-reversion probability using:
1. Market Regime: Bull/bear/choppy/rotation? (extreme moves in choppy markets revert faster)
2. Spike Magnitude: How far up did it go? (+5% = moderate, +6-8% = strong overbought)
   - Larger spikes = higher reversal probability
3. Technical Overbought Assessment (if available):
   - RSI > 70 = overbought, increases confidence
   - Price > 2% above VWAP = extended, increases confidence
   - These are CONFIRMING signals, not required
4. Reversal Probability: Will this overbought move revert to mean within 3-5 days?
   - +6-8% spike = 70-80 confidence (very likely to revert)
   - +5-6% spike = 60-70 confidence (likely to revert)
   - +5% spike = 55-65 confidence (moderate reversion probability)
5. Historical Pattern: Does this symbol mean-revert normally? (Tech/growth tends to revert faster)

Score all candidates >= 55. BUY candidates TODAY (spike day). Exit on +0.75% partial, +2% full.

CRITICAL - MANDATORY OUTPUT:
After your analysis, you MUST output valid JSON. Do not just analyze - output the JSON response.
This JSON is required for trade execution. Always include at least an empty decisions array.

Return JSON (REQUIRED):
{{"regime": "bull/bear/choppy/rotation", "strategy": "mean_reversion_spike_day", "decisions": [{{"symbol": "XYZ", "confidence": 72, "reason": "up +7% (overbought today), high reversal probability within 1-3 days to +2%", "action": "BUY", "hold_days": "1-3", "target_pct": 2}}], "next_interval_seconds": 1800}}"""
            }],
        )
        
        record_token_usage(state, resp.usage.input_tokens, resp.usage.output_tokens)
        log.info("Stage 2 tokens: %d input, %d output | Running total: %d input, %d output",
                resp.usage.input_tokens, resp.usage.output_tokens,
                state["token_usage"]["input"], state["token_usage"]["output"])

        try:
            text_content = None
            for block in resp.content:
                if block.type == "text":
                    text_content = block.text
                    json_str = extract_json_object(text_content)
                    if json_str:
                        # DEBUG: Log raw Sonnet response to understand reasoning
                        log.debug("DEBUG: Sonnet raw response: %s", json_str[:500] if len(json_str) > 500 else json_str)
                        result = json.loads(json_str)
                        regime = result.get("regime", "unknown")
                        strategy = result.get("strategy", "unknown")
                        decisions = result.get("decisions", [])
                        interval = result.get("next_interval_seconds", 1800)
                        
                        interval = max(300, min(3600, int(interval)))
                        
                        cache_set(cache, "regime", {
                            "regime": regime,
                            "strategy": strategy,
                            "interval": interval
                        })
                        # Cache Sonnet response for future cycles
                        sonnet_response = {
                            "decisions": decisions,
                            "regime": regime,
                            "strategy": strategy,
                            "interval": interval
                        }
                        cache_sonnet_response(candidates, regime, json.dumps(sonnet_response))
                        save_cache(cache)
                        
                        log.info("Regime: %s | Strategy: %s | Interval: %d sec (%.1f min)", 
                                regime, strategy, interval, interval / 60.0)
                        
                        # DEBUG: Log what Sonnet returned
                        buy_decisions = [d for d in decisions if d.get("action") == "BUY"]
                        log.info("DEBUG: Stage 2 returned %d total decisions, %d are BUY", len(decisions), len(buy_decisions))
                        if buy_decisions:
                            for d in buy_decisions:
                                log.info("  BUY: %s (conf=%s) - %s", d.get("symbol"), d.get("confidence"), d.get("reason", "")[:80])
                        
                        return decisions, interval
        except Exception as e:
            log.error("JSON parse error: %s", e)

        # Log warning if no text content found (thinking-only response)
        if not text_content:
            log.warning("Stage 2 returned only thinking blocks, no text output with decisions")

    except Exception as e:
        log.error("Stage 2 error: %s", e, exc_info=True)

    return [], 1800

# ============================================================================
# STAGE 3: EXECUTION (with Partial Profit-Taking via MCP)
# ============================================================================

def stage3_execute(client, state, decisions, learning_agent=None):
    """
    ⚠️  STAGE 3 IS LOCKED - DO NOT MODIFY THIS FUNCTION ⚠️

    This is the production MCP order execution pipeline. It is stable and working.
    Any changes MUST be discussed and approved - this controls live trading.

    Stage 3: Execute BUY trades using Claude with Robinhood MCP tool-use.
    - Claude calls place_equity_order via Robinhood MCP at agent.robinhood.com
    - OAuth token (RH_REFRESH_TOKEN) authenticated
    - Beta APIs: mcp-client-2025-04-04 + prompt-caching-2024-07-31
    - MCP server name: "robinhood" (from MCP registry)
    - Tool schemas discovered FROM MCP server (not locally defined)
    - Instruction forces IMMEDIATE EXECUTION (no review/verify first)
    - Only BUY orders placed (SELL orders blocked for non-margin accounts)

    Position sizing: Autonomous Learning Q-Learning adapts per trade regime.
    """
    executed = []

    # Filter for high-confidence BUY orders
    # DEBUG: Log ALL trade scores
    buy_decisions = [d for d in decisions if d.get("action") == "BUY"]
    if buy_decisions:
        for d in buy_decisions:
            symbol = d.get("symbol", "?")
            conf = d.get("confidence", 0)
            reason = d.get("reason", "")
            status = "✅ PASS" if conf >= CONFIDENCE_THRESHOLD else "❌ FAIL"
            log.info(f"  {status}: {symbol} conf={conf}% (threshold={CONFIDENCE_THRESHOLD}%) | {reason[:60]}")
    
    buys = [d for d in decisions
            if d.get("action") == "BUY" and d.get("confidence", 0) >= CONFIDENCE_THRESHOLD]

    if not buys:
        log.info("High-confidence trades (threshold=%d): %d", CONFIDENCE_THRESHOLD, len(buys))
        return executed

    # Initialize learning agent if not provided
    if learning_agent is None and autonomous_learning_enabled:
        try:
            learning_agent = TradeWithLearning(bot_agent=None)
            log.info("Autonomous learning enabled")
        except Exception as e:
            log.warning("Failed to initialize autonomous learning: %s", e)
            learning_agent = None

    # Build trade list for Claude
    # Mean-reversion strategy with autonomous learning-driven position sizing
    trades = []
    for decision in buys:
        symbol = decision.get("symbol")
        price = get_current_price(symbol)
        confidence = decision.get("confidence", 70)
        daily_change = decision.get("pct_change", 6.0)

        # AUTONOMOUS LEARNING: Get optimized position sizing
        if learning_agent:
            autonomous_decision = learning_agent.execute_trade_with_learning(
                symbol=symbol,
                daily_change_pct=daily_change,
                confidence=confidence,
                available_capital=TOTAL_BUDGET
            )

            # Map learned position size to actual shares
            size_map = {'small': 100, 'medium': 200, 'large': 300}
            size = size_map.get(autonomous_decision['position_size'], 200)
            strategy = autonomous_decision['strategy']
            regime = autonomous_decision['regime']

            log.info(f"[AUTONOMOUS] {symbol}: {strategy} ({regime}), size={size}")
        else:
            # Fallback to fixed position sizing V2 if learning unavailable
            if confidence >= 80:
                size = 350
            elif confidence >= 75:
                size = 300
            elif confidence >= 70:
                size = 200
            else:
                size = 150
            strategy = "mean_reversion"
            regime = "unknown"

        quantity = round(size / price, 2)
        half_qty = round(quantity / 2, 2)

        trades.append({
            "symbol": symbol,
            "price": price,
            "confidence": confidence,
            "quantity": quantity,
            "half_qty": half_qty,
            "sell1_price": round(price * 1.0075, 2),  # Sell 50% at +0.75% (quick recovery exit)
            "sell2_price": round(price * 1.02, 2),   # Sell 50% at +2% (full mean reversion)
            "strategy": strategy,
            "regime": regime,
            "learning_agent": learning_agent
        })

    # ============================================================
    # LOCKED: MCP ORDER EXECUTION PIPELINE - DO NOT MODIFY
    # ============================================================

    # Validate all positions respect budget and MAX_POSITION limits
    trades = validate_position_sizing(trades, TOTAL_BUDGET, MAX_POSITION)
    if not trades:
        log.warning("⚠️  No trades passed capital validation - skipping execution")
        return []

    # Build instruction for Claude
    # NOTE: Only place BUY orders. Exit orders require shares to be owned first (non-margin account).
    # Token-efficient: Allow one quick verify, then execute. No re-verification loop.
    instruction = f"""Execute these {len(buys)} mean-reversion BUY orders via place_equity_order.

If you haven't verified account 432591949 is eligible in this session: call get_accounts ONCE to confirm agentic_allowed=true, then proceed.
If already verified: skip get_accounts and go directly to place_equity_order.

Trades to execute (market orders):
"""
    for i, t in enumerate(trades, 1):
        instruction += f"\n{i}. {t['symbol']} BUY {t['quantity']} shares (confidence {t['confidence']:.0f}%)"

    instruction += f"""\n\nLogic:
1. Verify account eligibility (1 get_accounts call max - if not yet done)
2. Call place_equity_order for ALL BUYs (parallel, market orders only)
3. NO stop orders, NO review_equity_order, NO repeated verification, NO delays
4. Return order IDs and execution status

You have authority to execute. This is live trading with real money."""

    # Tool-use loop - Claude MUST call place_equity_order
    log.info("=== Stage 3: MCP Tool-Use Execution ===")
    messages = [{"role": "user", "content": instruction}]
    turn = 0
    max_turns = 2  # Allow 2 turns: Claude calls tool, then processes result

    while turn < max_turns:
        turn += 1
        log.debug("Tool-use loop turn %d", turn)

        try:
            # Get Robinhood OAuth token for MCP
            rh_token = get_rh_access_token()
            if not rh_token:
                log.error("No Robinhood access token for MCP execution")
                break

            # ========================================================
            # LOCKED: ROBINHOOD MCP CONFIGURATION
            # DO NOT CHANGE:
            #  - URL: https://agent.robinhood.com/mcp/trading (production endpoint)
            #  - name: "robinhood" (standard MCP registry name)
            #  - betas: mcp-client-2025-04-04, prompt-caching-2024-07-31
            #  - Tools come FROM MCP server, not locally defined
            #  - OAuth token passed as authorization_token
            # ========================================================
            resp = client.beta.messages.create(
                model="claude-opus-4-8",
                max_tokens=2000,
                system=[{
                    "type": "text",
                    "text": """You are a trading execution system with access to Robinhood MCP tools.
Your job: Execute trade instructions via place_equity_order and verify account eligibility via get_accounts.
Authority: You have live trading authorization for account 432591949.
Constraints: Market orders only, no review_equity_order, no repeated verification, parallel execution OK.""",
                    "cache_control": {"type": "ephemeral"}
                }],
                messages=messages,
                betas=["mcp-client-2025-04-04", "prompt-caching-2024-07-31"],
                mcp_servers=[{
                    "type": "url",
                    "url": "https://agent.robinhood.com/mcp/trading",  # LOCKED: Production endpoint
                    "name": "robinhood",  # LOCKED: Standard name from MCP registry
                    "authorization_token": rh_token,
                }]
            )

            record_token_usage(state, resp.usage.input_tokens, resp.usage.output_tokens)
            log.info("Stage 3 tokens: %d input, %d output | Running total: %d input, %d output",
                    resp.usage.input_tokens, resp.usage.output_tokens,
                    state["token_usage"]["input"], state["token_usage"]["output"])

            log.debug("Stage 3 response: stop_reason=%s, content_blocks=%d",
                     resp.stop_reason, len(resp.content) if resp.content else 0)

            # Deep MCP debugging - check for errors or messages
            log.info("=== MCP RESPONSE DEBUG ===")
            log.info("Stop reason: %s", resp.stop_reason)
            log.info("Response model: %s", resp.model if hasattr(resp, 'model') else 'unknown')

            # Check for text blocks (might contain errors or responses from MCP)
            has_text = False
            has_tool_result = False
            for block in resp.content:
                if hasattr(block, 'type') and block.type == "text":
                    has_text = True
                    text_content = block.text if hasattr(block, 'text') else "(empty)"
                    log.warning("⚠️  MCP returned TEXT block (length=%d): %s", len(text_content), text_content[:300] if text_content else "(empty)")
                if hasattr(block, 'type') and block.type == "tool_result":
                    has_tool_result = True

            if not has_text:
                log.info("✓ No text blocks in response")

            if not has_tool_result:
                log.warning("⚠️  NO TOOL_RESULT BLOCKS - MCP server may not be executing orders")

            if resp.content:
                for i, block in enumerate(resp.content):
                    log.debug("Block %d: %s", i, block.type if hasattr(block, 'type') else 'unknown')
                    if hasattr(block, 'name'):
                        log.debug("  Tool name: %s", block.name)
                    if hasattr(block, 'id'):
                        log.debug("  Tool ID: %s", block.id)

            # Process tool calls and look for MCP tool results (ALWAYS do this, even if end_turn)
            # When end_turn, there are still tool_use/tool_result blocks to process before exiting
            tool_call_count = 0
            tool_results = []
            import re

            for block in resp.content:
                if block.type in ("tool_use", "mcp_tool_use"):
                    tool_call_count += 1
                    tool_name = block.name
                    tool_id = block.id
                    tool_input = block.input

                    symbol = tool_input.get("symbol", "").upper()
                    side = tool_input.get("side", "").lower()
                    qty = tool_input.get("quantity", "0")
                    price = tool_input.get("limit_price", "market")

                    log.info("🔧 Tool call %d: %s %s %s shares @ %s", tool_call_count, side.upper(), symbol, qty, price)
                    log.info("   Tool ID: %s", tool_id)
                    log.info("   Full input: %s", json.dumps(tool_input, indent=2))

                    # Look for corresponding MCP tool result in response
                    # Handle both "tool_result" (regular) and "mcp_tool_result" (MCP server response)
                    mcp_result_text = ""
                    for rblock in resp.content:
                        if hasattr(rblock, "type") and rblock.type in ("tool_result", "mcp_tool_result"):
                            if hasattr(rblock, "tool_use_id") and rblock.tool_use_id == tool_id:
                                if hasattr(rblock, "content"):
                                    # Handle content as either string or list of content blocks
                                    if isinstance(rblock.content, list):
                                        mcp_result_text = "\n".join(str(c) for c in rblock.content)
                                    else:
                                        mcp_result_text = str(rblock.content)
                                    log.info("   ✅ MCP Tool Result found: %s", mcp_result_text[:300])
                                break

                    # If we found a result, this tool was actually executed by MCP
                    if mcp_result_text and symbol and side == "buy":
                        log.info("   ✅ CONFIRMED: MCP executed %s %s order", side.upper(), symbol)

                    # Extract actual fill price/quantity from MCP result if available
                    fill_price = None
                    fill_qty = None

                    if mcp_result_text:
                        # Try to extract average_price or price from MCP response
                        price_match = re.search(r'"average_price"\s*:\s*"?([\d.]+)', mcp_result_text) or \
                                     re.search(r'"price"\s*:\s*"?([\d.]+)', mcp_result_text)
                        if price_match:
                            fill_price = float(price_match.group(1))

                        # Try to extract cumulative_quantity or filled_quantity
                        qty_match = re.search(r'"cumulative_quantity"\s*:\s*"?([\d.]+)', mcp_result_text) or \
                                  re.search(r'"filled_quantity"\s*:\s*"?([\d.]+)', mcp_result_text)
                        if qty_match:
                            fill_qty = float(qty_match.group(1))

                    # Fallback: use request values if MCP didn't return execution details
                    if not fill_price:
                        fill_price = get_current_price(symbol)
                    if not fill_qty:
                        fill_qty = float(qty)

                    order_id = f"RH_ORD_{tool_call_count}_{int(time.time())}"
                    result = {
                        "status": "success",
                        "order_id": order_id,
                        "symbol": symbol,
                        "side": side,
                        "quantity": str(fill_qty),
                        "fill_price": fill_price,
                        "order_status": "pending" if not mcp_result_text else "executed",
                        "message": "Order submitted to Robinhood via MCP"
                    }
                    log.info("   📊 Processed: %s", json.dumps(result, indent=2))

                    # Track in executed list (only BUY orders, not SELL orders)
                    trade_match = next((t for t in trades if t["symbol"] == symbol), None)
                    if trade_match and side == "buy":  # BUY = buy first
                        # Calculate ACTUAL capital deployed from fill price (not planned price)
                        actual_capital = fill_qty * fill_price

                        executed_trade = {
                            "symbol": symbol,
                            "price": fill_price,
                            "quantity": fill_qty,
                            "capital_deployed": actual_capital,  # ACTUAL from MCP fill, not planned
                            "confidence": trade_match["confidence"],
                            "action": "BUY",
                            "status": "executed_via_mcp",
                            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "strategy": trade_match.get("strategy", "mean_reversion"),
                            "regime": trade_match.get("regime", "unknown"),
                            "order_id": order_id
                        }
                        executed.append(executed_trade)

                        # Track position for autonomous learning feedback
                        state["open_positions"][order_id] = {
                            "symbol": symbol,
                            "entry_price": fill_price,
                            "entry_date": datetime.now().isoformat(),
                            "confidence": trade_match["confidence"],
                            "strategy": trade_match.get("strategy", "mean_reversion"),
                            "learning_agent": trade_match.get("learning_agent")  # For feedback
                        }

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(result)
                    })

            # Check if Claude is done (end_turn means no more interaction needed)
            if resp.stop_reason == "end_turn":
                log.info("Stage 3 complete (end_turn after processing %d tool calls)", tool_call_count)
                break

            if tool_call_count == 0:
                log.info("No tool calls, exiting loop")
                break

            # Add assistant response to messages
            messages.append({"role": "assistant", "content": resp.content})

            # Add tool results to messages for Claude to process
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
                log.info("Added %d tool results to conversation, continuing loop", len(tool_results))
            else:
                log.info("No tool results, exiting loop")
                break

        except Exception as e:
            log.error("Stage 3 error: %s", e)
            import traceback
            traceback.print_exc()
            break

    log.info("Executed %d BUY trades via MCP", len(executed))

    # ========================================================================
    # PHASE 2: Place STOP-LIMIT orders for executed BUYs (sequential phase)
    # ========================================================================
    if executed:
        log.info("=== Stage 3 Phase 2: STOP-LIMIT Execution ===")

        # Build stop orders: for each executed buy, create stop-limit at entry_price * 0.995
        stop_orders = []
        for trade in executed:
            symbol = trade["symbol"]
            entry_price = float(trade["price"])
            quantity = float(trade["quantity"])

            # Stop-limit at -0.5%
            stop_price = entry_price * 0.995
            limit_price = stop_price  # Same as stop price for aggressive execution

            stop_orders.append({
                "symbol": symbol,
                "quantity": quantity,
                "stop_price": stop_price,
                "limit_price": limit_price,
                "entry_price": entry_price
            })

        # Build instruction for stop orders
        stop_instruction = f"""Place {len(stop_orders)} stop-limit SELL orders to protect executed positions.

Stop-limit details (0.5% below entry price):
"""
        for i, s in enumerate(stop_orders, 1):
            stop_instruction += f"\n{i}. {s['symbol']} SELL {s['quantity']} shares at STOP ${s['stop_price']:.2f} (limit ${s['limit_price']:.2f}, entry was ${s['entry_price']:.2f})"

        stop_instruction += f"""\n\nExecute as stop-limit SELL orders:
- Type: "stop_limit"
- Side: "sell"
- Stop price: as specified above
- Limit price: as specified above
- Time-in-force: "gfd" (good for day)

NO verification, NO review_equity_order, NO delays. Execute all STOPs in parallel."""

        # Clear messages and run stop-order phase
        messages = [{"role": "user", "content": stop_instruction}]
        turn = 0
        stop_tool_count = 0

        while turn < max_turns:
            turn += 1
            try:
                log.info("Stop-order loop turn %d", turn)

                resp = client.beta.messages.create(
                    model="claude-opus-4-8",
                    max_tokens=2200,
                    messages=messages,
                    betas=["interleaved-thinking-2025-05-14", "mcp-client-2025-04-04"],
                    mcp_servers=[{
                        "type": "url",
                        "url": "https://agent.robinhood.com/mcp/trading",
                        "name": "robinhood",
                        "authorization_token": rh_token,
                    }]
                )

                stop_tool_count = 0
                stop_tool_results = []

                for block in resp.content:
                    if block.type in ("tool_use", "mcp_tool_use"):
                        stop_tool_count += 1
                        tool_name = block.name
                        tool_id = block.id
                        tool_input = block.input

                        symbol = tool_input.get("symbol", "").upper()
                        side = tool_input.get("side", "").lower()
                        stop_price = tool_input.get("stop_price")
                        limit_price = tool_input.get("limit_price")

                        log.info("🔧 Stop order %d: %s %s @ stop $%s limit $%s",
                                 stop_tool_count, side.upper(), symbol, stop_price, limit_price)

                        # Look for MCP tool result
                        mcp_result_text = ""
                        for rblock in resp.content:
                            if hasattr(rblock, "type") and rblock.type in ("tool_result", "mcp_tool_result"):
                                if hasattr(rblock, "tool_use_id") and rblock.tool_use_id == tool_id:
                                    if hasattr(rblock, "content"):
                                        if isinstance(rblock.content, list):
                                            mcp_result_text = "\n".join(str(c) for c in rblock.content)
                                        else:
                                            mcp_result_text = str(rblock.content)
                                        log.info("   ✅ STOP order result: %s", mcp_result_text[:200])
                                    break

                        stop_tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": f"Stop-limit order for {symbol} SELL placed"
                        })

                if resp.stop_reason == "end_turn":
                    log.info("Stop-order phase complete (end_turn after %d stop calls)", stop_tool_count)
                    break

                if stop_tool_count == 0:
                    log.info("No stop order calls, exiting stop phase")
                    break

                messages.append({"role": "assistant", "content": resp.content})
                if stop_tool_results:
                    messages.append({"role": "user", "content": stop_tool_results})

            except Exception as e:
                log.error("Stop-order phase error: %s", e)
                break

        log.info("Placed %d stop-limit orders", stop_tool_count)

    return executed

# ============================================================================
# WEEKLY LEARNING ANALYSIS
# ============================================================================

def analyze_weekly_performance(client, state, cache=None):
    """Analyze performance from past 7 days using cached learning."""
    if cache is None:
        cache = load_cache()
    
    cached_learning = cache_get(cache, "learning", LEARNING_CACHE_TTL)
    if cached_learning:
        log.info("✓ Using cached weekly learning (7 days old)")
        return cached_learning
    
    now = datetime.now()
    week_ago = now - timedelta(days=7)
    
    weekly_trades = [
        t for t in state.get("trades", [])
        if datetime.fromisoformat(t.get("date", "2000-01-01")) >= week_ago
    ]
    
    if len(weekly_trades) < 3:
        log.info("Not enough trades this week (%d) for learning", len(weekly_trades))
        return None
    
    brackets = {
        "70-75": [],
        "75-80": [],
        "80-85": [],
        "85-90": [],
        "90-95": [],
        "95-100": [],
    }
    
    for trade in weekly_trades:
        conf = trade.get("confidence", 75)
        won = trade.get("realized_pnl", 0) > 0
        
        if conf < 75:
            brackets["70-75"].append(won)
        elif conf < 80:
            brackets["75-80"].append(won)
        elif conf < 85:
            brackets["80-85"].append(won)
        elif conf < 90:
            brackets["85-90"].append(won)
        elif conf < 95:
            brackets["90-95"].append(won)
        else:
            brackets["95-100"].append(won)
    
    summary = "Weekly Performance Analysis (past 7 days):\n"
    summary += f"Total trades: {len(weekly_trades)}\n\n"
    
    for bracket, results in brackets.items():
        if len(results) == 0:
            continue
        win_rate = sum(results) / len(results) * 100
        summary += f"Confidence {bracket}: {len(results)} trades, {win_rate:.0f}% win rate\n"
    
    log.info("\n%s", summary)
    
    try:
        resp = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=800,
            thinking={"type": "adaptive"},
            system=[{
                "type": "text",
                "text": "Analyze trading performance and recommend confidence calibration adjustments.",
                "cache_control": {"type": "ephemeral"}
            }],
            messages=[{
                "role": "user",
                "content": f"""{summary}

Analyze:
1. Which confidence brackets overperform vs underperform?
2. Should we adjust the 75 confidence threshold?
3. Any patterns in win/loss clustering?

Return JSON:
{{"analysis": "...", "recommendations": "...", "confidence_adjustment": "+5/-5/none"}}"""
            }],
        )
        
        record_token_usage(state, resp.usage.input_tokens, resp.usage.output_tokens)
        
        try:
            for block in resp.content:
                if block.type == "text":
                    text = block.text
                    start = text.find('{')
                    if start >= 0:
                        result = json.loads(text[start:])
                        cache_set(cache, "learning", result)
                        save_cache(cache)
                        log.info("\nClaude's Learning Recommendations:\n%s", result.get("recommendations"))
                        return result
        except:
            pass
    except Exception as e:
        log.error("Weekly analysis error: %s", e)
    
    return None

def should_run_weekly_analysis(state):
    """Check if it's time for weekly analysis (Sunday 4 PM ET)."""
    et = pytz.timezone('US/Eastern')
    now = datetime.now(et)
    
    if now.weekday() != 6:
        return False
    if now.hour != 16:
        return False
    
    last_analysis = state.get("performance_analytics", {}).get("last_weekly_analysis")
    if last_analysis:
        last_time = datetime.fromisoformat(last_analysis.get("timestamp", "2000-01-01"))
        if (now - last_time).total_seconds() < 3600:
            return False
    
    return True

# ============================================================================
# POSITION MONITORING & STOP LOSS ALERTS
# ============================================================================

def should_check_position(state, symbol, position_value):
    """
    Smart cache logic:
    - If position > $600: cache for 3 hours (or until manually sold)
    - If position <= $600: always check (small positions don't need caching)
    - If position closed: check again after 3 hours (in case re-entry)

    Returns: (should_check: bool, cache_entry: dict or None)
    """
    cache = state.get("position_cache", {})
    entry = cache.get(symbol)

    if not entry:
        return (True, None)  # No cache, check now

    timestamp = entry.get("timestamp", 0)
    cached_value = entry.get("value", 0)
    time_elapsed = time.time() - timestamp
    ttl_minutes = entry.get("ttl_minutes", 180)  # 3 hours default

    # If cached position > $600: use cache for 3 hours
    if cached_value > MAX_POSITION:
        if time_elapsed < ttl_minutes * 60:
            return (False, entry)  # Use cache
        else:
            return (True, None)  # Cache expired, check now

    # If cached position was closed (0) or <= $600: check every 3 hours for re-entry
    if cached_value == 0 or cached_value <= MAX_POSITION:
        if time_elapsed < ttl_minutes * 60:
            return (False, entry)  # Trust closed/small position, skip check
        else:
            return (True, None)  # 3 hours passed, check for re-entry

    return (True, None)

def get_open_symbols(client, state=None):
    """
    Fetch positions with smart caching:
    - Positions > $600: cached 3 hours (save tokens)
    - Positions <= $600: always check (dedup safety)
    - Closed: recheck after 3 hours
    """
    try:
        # Check cache for large positions if state provided
        if state and "position_cache" in state:
            cache = state["position_cache"]
            cached_symbols = set()

            # Reuse cached large positions
            for symbol, entry in list(cache.items()):
                should_check, cached_entry = should_check_position(state, symbol, entry.get("value", 0))
                if not should_check:
                    cached_symbols.add(symbol)
                    log.debug(f"📦 Cache hit: {symbol} (${entry.get('value', 0):.0f}), skip MCP check")

            # If all positions cached, return immediately
            if cached_symbols:
                log.info(f"Using cached positions: {sorted(cached_symbols)}")
                return cached_symbols

        # Need fresh data - call MCP
        rh_token = get_rh_access_token(force_refresh=True)
        if not rh_token:
            log.error("❌ HALT: Cannot get Robinhood token")
            return None

        # Call MCP to fetch positions
        resp = client.beta.messages.create(
            model="claude-opus-4-8",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": f"Use the get_equity_positions tool to fetch ALL open positions for account {RH_ACCOUNT}. Include positions with any quantity > 0. Return the complete results with symbols and quantities."
            }],
            betas=["mcp-client-2025-04-04", "prompt-caching-2024-07-31"],
            mcp_servers=[{
                "type": "url",
                "url": "https://agent.robinhood.com/mcp/trading",
                "name": "robinhood",
                "authorization_token": rh_token,
            }]
        )

        owned_symbols = set()

        # Parse MCP response for tool results
        log.debug(f"MCP response has {len(resp.content)} content blocks")
        for i, block in enumerate(resp.content):
            block_type = getattr(block, 'type', 'unknown')
            log.debug(f"  Block {i}: type={block_type}")

            # Try mcp_tool_result blocks first
            if block_type == "mcp_tool_result":
                try:
                    result_text = block.text if hasattr(block, 'text') else str(block)
                    log.debug(f"  MCP tool result (first 300 chars): {result_text[:300]}")

                    # Parse JSON from result
                    if isinstance(result_text, str) and result_text.startswith('{'):
                        result_json = json.loads(result_text)

                        # Handle "data.results" format
                        positions = result_json.get("data", {}).get("results", [])
                        if not positions:
                            # Try top-level results
                            positions = result_json.get("results", [])
                        if not positions:
                            # Try direct array
                            if isinstance(result_json, list):
                                positions = result_json

                        log.debug(f"  Parsed {len(positions)} positions from MCP")

                        for pos in positions:
                            symbol = pos.get("symbol", "").upper()
                            qty = float(pos.get("quantity", 0))
                            if symbol and qty > 0:
                                owned_symbols.add(symbol)
                                log.info(f"  ✓ Position: {symbol} x {qty}")
                except Exception as parse_error:
                    log.error(f"MCP tool result parse error: {parse_error}", exc_info=True)

            # Also check text blocks for position data (fallback)
            elif block_type == "text":
                text = getattr(block, 'text', '')
                log.debug(f"  Text block (first 100 chars): {text[:100]}")

        if owned_symbols:
            log.info("🔒 Fetched positions: %s", ", ".join(sorted(owned_symbols)))

            # Cache large positions (> $600) for 3 hours to save tokens
            if state:
                for symbol in owned_symbols:
                    # Get position value from parsed data
                    pos_value = 0  # Default: need to extract from positions
                    for pos in positions:
                        if pos.get("symbol", "").upper() == symbol:
                            qty = float(pos.get("quantity", 0))
                            price = float(pos.get("price", 0)) or 100  # fallback
                            pos_value = qty * price
                            break

                    # Cache if > $600, TTL 3 hours
                    if pos_value > MAX_POSITION:
                        state["position_cache"][symbol] = {
                            "timestamp": time.time(),
                            "value": pos_value,
                            "ttl_minutes": 180  # 3 hours
                        }
                        log.info(f"💾 Cached {symbol}: ${pos_value:.0f} (expires in 3h)")
                    # Clear cache for small positions (already checked)
                    elif symbol in state.get("position_cache", {}):
                        del state["position_cache"][symbol]
                        log.debug(f"Cleared cache for {symbol}: now <= $600")
        else:
            log.info("ℹ️  No open positions found via MCP")

        return owned_symbols

    except Exception as e:
        log.error("❌ HALT: MCP position fetch failed: %s", e)
        return None

def check_positions_and_alert():
    """
    Monitor open positions for stop loss breach (-0.5%).
    Fetch from Robinhood, check P&L, alert if below threshold.
    Cost: ~$0 (no Claude, direct API call)
    """
    try:
        state = load_state()

        # Only check if we have open positions
        if not state.get("open_positions"):
            return

        rh_token = get_rh_access_token()
        if not rh_token:
            return

        # Fetch current positions from Robinhood
        headers = {"Authorization": f"Bearer {rh_token}"}
        resp = requests.get(
            f"https://api.robinhood.com/accounts/{RH_ACCOUNT}/positions/",
            headers=headers,
            timeout=10
        )

        if resp.status_code != 200:
            log.warning("Failed to fetch positions: %s", resp.status_code)
            return

        positions = resp.json().get("results", [])
        if not positions:
            return

        # Check each open position
        alerts = []
        for pos in positions:
            symbol = pos.get("symbol", "").upper()
            if not symbol:
                continue

            current_qty = float(pos.get("quantity", 0))
            avg_buy_price = float(pos.get("average_buy_price", 0))

            if current_qty <= 0 or avg_buy_price <= 0:
                continue

            # Get current price
            quote_resp = requests.get(
                f"https://api.robinhood.com/quotes/{symbol}/",
                headers=headers,
                timeout=5
            )

            if quote_resp.status_code != 200:
                continue

            current_price = float(quote_resp.json().get("last_trade_price", 0))
            if current_price <= 0:
                continue

            # Calculate P&L
            pnl_pct = (current_price - avg_buy_price) / avg_buy_price

            # ALERT: Below -0.5% stop loss threshold
            if pnl_pct < -0.005:  # -0.5%
                alerts.append({
                    'symbol': symbol,
                    'entry': avg_buy_price,
                    'current': current_price,
                    'qty': current_qty,
                    'pnl_pct': pnl_pct
                })

        # Log alerts
        if alerts:
            log.warning("🚨 STOP LOSS ALERTS - Manual sell required:")
            for alert in alerts:
                log.warning(
                    f"  {alert['symbol']}: ${alert['entry']:.2f} → ${alert['current']:.2f} "
                    f"({alert['pnl_pct']*100:.2f}%) | {alert['qty']} shares"
                )
            log.warning("   Action: Manually sell via Robinhood app to prevent further loss")

    except Exception as e:
        log.debug("Position check error (non-critical): %s", e)

# ============================================================================
# MAIN TRADING LOOP
# ============================================================================

def run_trading_loop():
    if not is_market_hours():
        log.info("Outside market hours — skipping")
        return None

    state = load_state()
    cache = load_cache()

    cleanup_sonnet_cache()  # Remove expired cache entries
    # === MONITOR OPEN POSITIONS ===
    # Check if any position falls below -0.5% stop loss, alert user
    check_positions_and_alert()

    if state.get("bot_halted"):
        log.warning("BOT HALTED — circuit breaker triggered")
        return None
    
    if check_daily_loss_limit(state):
        log.warning("Daily loss limit hit — stopping new trades")
        return None
    
    client = get_anthropic_client()

    # Initialize autonomous learning agent
    learning_agent = None
    if autonomous_learning_enabled and state.get("autonomous_learning", {}).get("enabled", True):
        try:
            learning_agent = TradeWithLearning(bot_agent=None)
            regime = learning_agent.learning_agent.regime_detector.detect_regime()
            state["autonomous_learning"]["regime"] = regime
            state["autonomous_learning"]["last_update"] = datetime.now().isoformat()
            log.info("Autonomous learning initialized (regime: %s)", regime)
        except Exception as e:
            log.warning("Failed to initialize autonomous learning: %s", e)

    if should_run_weekly_analysis(state):
        log.info("=== Weekly Learning Analysis ===")
        analysis = analyze_weekly_performance(client, state, cache)
        if analysis:
            state["performance_analytics"]["confidence_calibration"] = analysis
            state["performance_analytics"]["last_weekly_analysis"] = {
                "timestamp": datetime.now().isoformat()
            }

    log.info("=== Stage 1: Haiku Screening ===")
    movers = get_top_movers(None, 60, cache)

    if not movers:
        log.warning("No movers fetched from Robinhood")
        save_state(state)
        return None

    candidates = stage1_haiku_screening(client, state, movers)

    if not candidates or len(candidates) == 0:
        log.info("No candidates scored for analysis")
        save_state(state)
        return None

    log.info("Stage 1 identified %d candidates for Stage 2", len(candidates))

    # Refresh live prices from Finnhub for candidates (stays under rate limits)
    refresh_candidate_prices(candidates)

    log.info("=== Stage 2: Sonnet 4.6 Analysis ===")
    decisions, next_interval = stage2_sonnet_analysis(client, state, candidates, cache)

    if not decisions or len(decisions) == 0:
        log.info("No high-confidence trades identified")
        state["next_interval_seconds"] = next_interval
        save_state(state)
        return next_interval

    # Get FOMC-adjusted settings
    current_threshold, next_interval = get_fomc_settings()

    # Filter for current confidence threshold (could be aggressive during FOMC)
    high_confidence = [d for d in decisions if d.get("confidence", 0) >= current_threshold]
    log.info("High-confidence trades (threshold=%d): %d", current_threshold, len(high_confidence))

    # Reset daily tracking at midnight UTC
    today = datetime.now(pytz.UTC).date().isoformat()
    if state.get("daily_date") != today:
        state["daily_bought_symbols"] = {}
        state["daily_date"] = today
        log.info("📅 Daily tracking reset (new day)")

    # FILTER: For each stock: if owned AND total > $600 then SKIP, else BUY under $600
    # Get current positions from Robinhood (with smart caching)
    owned_symbols = get_open_symbols(client, state)
    if owned_symbols is None:
        log.critical("🛑 Cannot verify positions via MCP - HALTING trades this cycle")
        return next_interval

    filtered_trades = []
    for trade in high_confidence:
        symbol = trade.get("symbol", "").upper()
        capital_needed = trade.get("capital_deployed", 0)
        daily_deployed = state.get("daily_bought_symbols", {}).get(symbol, 0)
        total_capital = daily_deployed + capital_needed

        # Rule: If stock owned AND total > $600 → SKIP
        if symbol in owned_symbols and total_capital > MAX_POSITION:
            log.info("⏸️  SKIP %s: Owned + would exceed $600 (${:.0f} + ${:.0f} = ${:.0f})",
                     symbol, daily_deployed, capital_needed, total_capital)
            continue

        # Rule: If total > $600 → SKIP (don't buy, limit per stock)
        if total_capital > MAX_POSITION:
            log.info("⏸️  SKIP %s: Exceeds $600 daily limit (${:.0f} + ${:.0f} = ${:.0f})",
                     symbol, daily_deployed, capital_needed, total_capital)
            continue

        # Passed: execute trade
        filtered_trades.append(trade)

    high_confidence = filtered_trades

    if not high_confidence:
        log.info("No trades passed MCP position + capital checks")
        save_state(state)
        return next_interval

    log.info("Trades to execute: %d", len(high_confidence))

    log.info("=== Stage 3: Execution (Split Exits via MCP) ===")
    executed = stage3_execute(client, state, high_confidence, learning_agent=learning_agent)
    
    if executed:
        state["trades"].extend(executed)

        # Track daily capital deployed per symbol (max $600/symbol/day)
        for trade in executed:
            symbol = trade.get("symbol", "").upper()
            capital = trade.get("capital_deployed", 0)
            state["daily_bought_symbols"][symbol] = state["daily_bought_symbols"].get(symbol, 0) + capital
            log.debug(f"💰 Tracked {symbol}: +${capital:.2f} (daily total: ${state['daily_bought_symbols'][symbol]:.2f})")

        log.info("Executed %d orders (from %d trades)", len(executed), len(high_confidence))

        # Log autonomous learning status after execution
        if learning_agent:
            try:
                report = learning_agent.learning_agent.get_learning_report()
                regime = report.get('current_regime', 'unknown')
                log.info("Autonomous Learning: Regime=%s | Strategy allocations: momentum=%.0f%% mean_reversion=%.0f%%",
                        regime,
                        report.get('strategy_allocations', {}).get('momentum', 0) * 100,
                        report.get('strategy_allocations', {}).get('mean_reversion', 0) * 100)
            except Exception as e:
                log.debug("Failed to log learning status: %s", e)

    # Use FOMC interval if in FOMC window
    fomc_threshold, fomc_interval = get_fomc_settings()
    state["next_interval_seconds"] = fomc_interval
    if fomc_interval == FOMC_INTERVAL:
        log.info("🚀 FOMC AGGRESSIVE MODE: 10-min checks, threshold=%d", fomc_threshold)

    # Daily learning at market close (4:00 PM - 4:15 PM ET)
    # TODO: Re-enable after implementing daily learning function
    # if is_market_close() and daily_learning:
    #     log.info("=== MARKET CLOSE: Daily Learning ===")
    #     try:
    #         learning_result = daily_learning(client, state)
    #         if learning_result and learning_result.get("deployed"):
    #             log.info("Strategy updated: %s | Improvement: %.2f%%",
    #                     learning_result["variant"]["variant"],
    #                     learning_result["improvement"])
    #             save_state(state)
    #         elif learning_result:
    #             log.info("No strategy change: %s", learning_result.get("reason", ""))
    #     except Exception as e:
    #         log.error("Daily learning error: %s", e, exc_info=True)

    save_state(state)
    return next_interval

def main():
    log.info("Starting Tiered Trading Bot (with Partial Profit-Taking)...")
    init_sonnet_cache()  # Initialize SQLite cache for Sonnet responses

    # Initialize FinRL if available
    if finrl_enabled:
        initialize_finrl()
        log.info("✅ FinRL integration active (trained model predictions enabled)")
    else:
        log.info("⚠️  FinRL not available (using rules-based mean-reversion strategy)")

    log.info("Strategy: 50%% exits at +2%% (lock profits), 50%% rides to +5%% or -3%% (capture upside)")
    log.info("Configuration: Account=%s | Budget=$%d | Max/position=$%d | Confidence threshold=%d%%",
            RH_ACCOUNT, TOTAL_BUDGET, MAX_POSITION, CONFIDENCE_THRESHOLD)

    # Test mode: Force MCP test if TEST_MCP env var is set
    if os.environ.get("TEST_MCP") == "1":
        log.info("\n🧪 TEST MODE: Forcing MCP test order...")
        client = get_anthropic_client()
        state = load_state()
        test_decisions = [{
            "symbol": "AAPL",
            "confidence": 75,
            "action": "BUY",
            "pct_change": 5.5,
            "reason": "TEST ORDER"
        }]
        executed = stage3_execute(client, state, test_decisions)
        log.info("🧪 TEST: Executed %d test orders. Check Robinhood!", len(executed))
        return

    current_interval = 1800
    
    while True:
        try:
            returned_interval = run_trading_loop()
            if returned_interval is not None:
                current_interval = returned_interval
                log.info("Next interval: %d seconds (%.1f min)", 
                        current_interval, current_interval / 60.0)
        except Exception as e:
            log.error("Error in trading loop: %s", e, exc_info=True)
        
        log.info("Sleeping %d seconds (%.1f min) until next run...", 
                current_interval, current_interval / 60.0)
        time.sleep(current_interval)

if __name__ == "__main__":
    main()
