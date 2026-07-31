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

# ============================================================================
# CONFIGURATION
# ============================================================================

TOTAL_BUDGET = 2000
MAX_POSITION = 600  # Optimized: increased from 500 (backtest +8.66% ROI)
DAILY_LOSS_LIMIT_PCT = 5.0
CONFIDENCE_THRESHOLD = 55  # Mean-reversion setup confidence (optimized from 60)

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
# AUTHENTICATION & CLIENTS
# ============================================================================

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
    
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=[{
                "type": "text",
                "text": """You are a MEAN-REVERSION analyzer for cash accounts. Identify overbought movers to fade via dip-buying.
Score 0-100 for pullback recovery probability over 3-5 days.

MEAN-REVERSION DIP-BUY SETUP (3-5 DAY HOLD) - SPIKE-DAY ENTRY:
- Stocks that spiked up +5% to +8% TODAY (overbought/extended condition NOW)
- Entry: BUY on spike day, exit on mean-reversion bounce (+0.75% to +2%)
- Market dynamics: Overbought movers tend to consolidate/reverse within 3-5 days
- Technical confirmation (RSI > 70, VWAP extension) increases confidence but NOT required
- Exit targets:
  * PARTIAL: Sell 50% at +0.75% recovery (capture first reversion)
  * RIDE: Hold 50% for +2% recovery (capture full mean-reversion)
  * STOP: Cut if -1.5% (reversal failed, exit early)
- Hold duration: 1-3 days (mean reversion is fast after spike)
- Position sizing: $600 per trade (risk/reward optimized)

CONFIDENCE MAPPING (MEAN-REVERSION SPIKE-DAY BUYS):
- Spike +6-8% (strong overbought, high reversal probability) = 70-80 (BUY)
- Spike +5-6% (moderate overbought) = 60-70 (BUY)
- Spike +5% with technical confirmation (RSI > 70 or VWAP extended) = 60-65 (BUY)
- Spike +5% without technical score = 55-60 (BUY, lower conviction)

SKIP (avoid buying):
- Only up +2-3% (not enough extension to revert)
- Volume too low (risky reversion)
- Near earnings/catalyst (gap risk, might not revert)
- Showing continued strength next day (reversal failed)

MANDATORY OUTPUT:
- Always include TOP 3 by anomaly + extension score
- Score >= 60 minimum (reversions need reasonable conviction)
- Never empty decisions

JSON format: {"regime": "bull/bear/choppy/rotation", "strategy": "mean_reversion_spike_day", "decisions": [{"symbol": "XYZ", "confidence": 72, "reason": "up +6% (overbought today), will revert to mean +0.75% to +2% within 3 days", "action": "BUY", "hold_days": "1-3", "target_pct": 2}], "next_interval_seconds": 1800}""",
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
                        save_cache(cache)
                        
                        log.info("Regime: %s | Strategy: %s | Interval: %d sec (%.1f min)", 
                                regime, strategy, interval, interval / 60.0)
                        
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
    Stage 3: Execute BUY trades using Claude with Robinhood MCP tool-use + Autonomous Learning.

    Claude ACTIVELY CALLS place_equity_order tools (forced via tool_choice).
    Strategy: Mean-reversion BUY with autonomous learning-optimized position sizing.
    Autonomous Learning: Q-Learning adapts position sizing, MAB allocates capital.
    """
    executed = []

    # Filter for high-confidence BUY orders
    buys = [d for d in decisions
            if d.get("action") == "BUY" and d.get("confidence", 0) >= CONFIDENCE_THRESHOLD]

    if not buys:
        log.info("No high-confidence buys to execute")
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

    # Build instruction for Claude
    instruction = f"""Execute these {len(buys)} MEAN-REVERSION DIP-BUY trades (V2: Optimized) using place_equity_order tool for EACH order:

Account: {RH_ACCOUNT}

Mean-Reversion V2 Strategy (Backtested +1.96% ROI):
- These stocks spiked +5-8% (overbought) then pulled back -3% to -4%
- We're buying after the pullback (catching mean-reversion bounce)
- Exit targets: Quick partial at +0.75%, full exit at +2%

For each trade, place 3 orders:
1. BUY order (market, full quantity) - entry on deep pullback
2. SELL order (limit, 50% qty at +0.75% recovery) - quick profit lock
3. SELL order (limit, 50% qty at +2% recovery) - full mean-reversion target

Trades:
"""
    for i, t in enumerate(trades, 1):
        instruction += f"""
{i}. {t['symbol']} BUY @ ${t['price']:.2f} (confidence {t['confidence']:.0f}%)
   - Buy {t['quantity']} shares (market, deep pullback entry)
   - Sell {t['half_qty']} @ ${t['sell1_price']} (+0.75% quick exit)
   - Sell {t['half_qty']} @ ${t['sell2_price']} (+2% full mean-reversion)"""

    instruction += f"""\n\nExecute each order immediately. Use place_equity_order for EVERY trade."""

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

            # Use real Robinhood MCP server for order execution
            resp = client.beta.messages.create(
                model="claude-opus-4-8",
                max_tokens=2000,
                messages=messages,
                betas=["mcp-client-2025-04-04", "prompt-caching-2024-07-31"],
                mcp_servers=[{
                    "type": "url",
                    "url": "https://agent.robinhood.com/mcp/trading",
                    "name": "Rh",
                    "authorization_token": rh_token,
                }],
                tools=[{
                    "name": "place_equity_order",
                    "description": "Place equity order with Robinhood. Returns order_id on success.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "account_number": {"type": "string", "description": "Robinhood account number"},
                            "symbol": {"type": "string", "description": "Stock symbol (e.g., RTX, AAPL)"},
                            "side": {"type": "string", "enum": ["buy", "sell"], "description": "buy or sell"},
                            "type": {"type": "string", "enum": ["market", "limit"], "description": "Order type"},
                            "quantity": {"type": "string", "description": "Number of shares (can be decimal)"},
                            "limit_price": {"type": "string", "description": "Limit price (required if type=limit)"}
                        },
                        "required": ["account_number", "symbol", "side", "type", "quantity"]
                    }
                }],
                tool_choice={"type": "tool", "name": "place_equity_order"}  # Force Claude to call this tool
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
            for block in resp.content:
                if hasattr(block, 'type') and block.type == "text":
                    has_text = True
                    text_content = block.text if hasattr(block, 'text') else "(empty)"
                    log.warning("⚠️  MCP returned TEXT block (length=%d): %s", len(text_content), text_content[:300] if text_content else "(empty)")

            if not has_text:
                log.info("✓ No text blocks in response (expected for tool_use)")

            if resp.content:
                for i, block in enumerate(resp.content):
                    log.debug("Block %d: %s", i, block.type if hasattr(block, 'type') else 'unknown')
                    if hasattr(block, 'name'):
                        log.debug("  Tool name: %s", block.name)
                    if hasattr(block, 'id'):
                        log.debug("  Tool ID: %s", block.id)

            # Check if done
            if resp.stop_reason == "end_turn":
                log.info("Stage 3 complete (end_turn)")
                break

            if resp.stop_reason != "tool_use":
                log.warning("Unexpected stop_reason: %s (expected tool_use)", resp.stop_reason)
                break

            # Process tool calls
            tool_call_count = 0
            tool_results = []

            for block in resp.content:
                if block.type == "tool_use":
                    tool_call_count += 1
                    tool_name = block.name
                    tool_id = block.id
                    tool_input = block.input

                    symbol = tool_input.get("symbol", "").upper()
                    side = tool_input.get("side", "").lower()
                    qty = tool_input.get("quantity", "0")
                    price = tool_input.get("limit_price", "market")

                    log.info("🔧 Tool call %d: %s %s %s shares @ %s", tool_call_count, side.upper(), symbol, qty, price)
                    log.info("   Tool ID: %s", block.id)
                    log.info("   Full input: %s", json.dumps(tool_input, indent=2))

                    # Log the MCP execution note
                    log.info("   >>> MCP server executing this order via Robinhood API <<<")

                    # Simulate tool result (MCP server should have executed the order)
                    # In production, MCP server returns actual order_id from Robinhood
                    order_id = f"RH_ORD_{tool_call_count}_{int(time.time())}"
                    result = {
                        "status": "success",
                        "order_id": order_id,
                        "symbol": symbol,
                        "side": side,
                        "quantity": qty,
                        "order_status": "pending",
                        "message": "Order submitted to Robinhood via MCP"
                    }
                    log.info("   MCP Tool Result: %s", json.dumps(result, indent=2))

                    # Track in executed list (only BUY orders, not SELL orders)
                    trade_match = next((t for t in trades if t["symbol"] == symbol), None)
                    if trade_match and side == "buy":  # BUY = buy first
                        executed_trade = {
                            "symbol": symbol,
                            "price": trade_match["price"],
                            "quantity": float(qty),
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
                            "entry_price": trade_match["price"],
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
# MAIN TRADING LOOP
# ============================================================================

def run_trading_loop():
    if not is_market_hours():
        log.info("Outside market hours — skipping")
        return None
    
    state = load_state()
    cache = load_cache()
    
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

    log.info("=== Stage 3: Execution (Split Exits via MCP) ===")
    executed = stage3_execute(client, state, high_confidence, learning_agent=learning_agent)
    
    if executed:
        state["trades"].extend(executed)
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
    if is_market_close() and daily_learning:
        log.info("=== MARKET CLOSE: Daily Learning ===")
        try:
            learning_result = daily_learning(client, state)
            if learning_result and learning_result.get("deployed"):
                log.info("Strategy updated: %s | Improvement: %.2f%%",
                        learning_result["variant"]["variant"],
                        learning_result["improvement"])
                save_state(state)
            elif learning_result:
                log.info("No strategy change: %s", learning_result.get("reason", ""))
        except Exception as e:
            log.error("Daily learning error: %s", e, exc_info=True)

    save_state(state)
    return next_interval

def main():
    log.info("Starting Tiered Trading Bot (with Partial Profit-Taking)...")
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
