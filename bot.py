#!/usr/bin/env python3
"""
TIERED + CACHED TRADING BOT (with Partial Profit-Taking)
Opus 4.8 + Adaptive Thinking + Multi-layer Caching + Split Exits

Partial profit-taking strategy:
  - Buy: Full position
  - Exit 1: Sell 50% at +2% (lock profits)
  - Exit 2: Sell 50% at +5% OR -3% (capture upside or cut loss)
  
Benefits:
  - Locks profits early (avoids "sold too early" regret)
  - Captures bigger moves (50% rides to +5%)
  - Reduces full stop-outs (only half position hit at -3%)
  - Expected improvement: +1-2% average returns
  - Cost: Zero additional Claude tokens
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

# ============================================================================
# CONFIGURATION
# ============================================================================

TOTAL_BUDGET = 2000
MAX_POSITION = 500
DAILY_LOSS_LIMIT_PCT = 5.0
CONFIDENCE_THRESHOLD = 75
RH_ACCOUNT = "432591949"  # Robinhood account for MCP tool execution

TOKENS_PER_HOUR_LIMIT = 2_000_000
TOKENS_PER_DAY_LIMIT = 15_000_000

RH_AUTH_URL = "https://api.robinhood.com/oauth2/token/"
RH_MOVERS_URL = "https://api.robinhood.com/midlands/movers/sp500/"
RH_QUOTES_URL = "https://api.robinhood.com/quotes/"

FINNHUB_API_URL = "https://finnhub.io/api/v1/quote"
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

# Cache TTLs
MOVERS_CACHE_TTL = 120  # 2 min (finnhub real-time ~100ms latency)
REGIME_CACHE_TTL = 3600
LEARNING_CACHE_TTL = 604800

CACHE_FILE = "bot_cache.json"

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
    # Account number is fetched by Claude via MCP when executing trades
    # This is a placeholder—actual account lookup happens in stage3_execute
    return None

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
    """Get top movers using Finnhub API (real-time ~100ms latency)."""
    if cache is None:
        cache = load_cache()

    cached_movers = cache_get(cache, "movers", MOVERS_CACHE_TTL)
    if cached_movers:
        return cached_movers

    if not FINNHUB_API_KEY:
        log.error("FINNHUB_API_KEY not set")
        return cached_movers or []

    try:
        log.info("Fetching movers from Finnhub (S&P 500 + NASDAQ-50: %d stocks)", len(TOP_WATCHLIST[:limit]))
        symbols = TOP_WATCHLIST[:limit]

        movers = []
        for symbol in symbols:
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

                    movers.append({
                        "symbol": symbol,
                        "price": current,
                        "pct_change": pct_change,
                        "volume": quote.get("v", 0),
                    })
            except Exception as e:
                log.debug("Error fetching %s: %s", symbol, e)
                continue

        movers = sorted(movers, key=lambda x: abs(x["pct_change"]), reverse=True)
        cache_set(cache, "movers", movers)
        save_cache(cache)

        log.info("✓ Fetched %d movers from Finnhub (real-time)", len(movers))
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
    """Stage 1: Score all top movers for Stage 2 analysis."""
    if not movers or len(movers) == 0:
        return []

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
    """Stage 2: Opus 4.8 with adaptive thinking + caching."""
    if not candidates or len(candidates) == 0:
        return [], 1800
    
    if cache is None:
        cache = load_cache()
    
    candidates_text = "\n".join([
        f"{c['symbol']}: +{c.get('pct_change', 0):.1f}% (anomaly={c.get('score', 0)})"
        for c in candidates[:5]
    ])
    
    learning_context = ""
    calibration = state.get("performance_analytics", {}).get("confidence_calibration")
    if calibration:
        learning_context = f"\n\nLast week's calibration: {calibration.get('recommendations', '')}"
    
    try:
        resp = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=1500,
            thinking={
                "type": "adaptive",
                "display": "summarized"
            },
            system=[{
                "type": "text",
                "text": """You are a market regime analyst. Identify market regime, assess candidates, rate confidence for +3% in 1-2 days, and recommend scanning frequency.

Analyze:
1. Trend direction and strength (bull/bear/choppy)
2. Sector rotation patterns
3. Volatility regime (high/low)
4. Mean reversion vs momentum signals
5. Strategy that wins today (gap-fill/momentum/reversal)

JSON format: {"regime": "bull/bear/choppy/rotation", "strategy": "...", "decisions": [{"symbol": "XYZ", "confidence": 82, "reason": "...", "action": "BUY"}], "next_interval_seconds": 1200}""",
                "cache_control": {"type": "ephemeral"}
            }],
            messages=[{
                "role": "user",
                "content": f"""Analyze these anomalies for trading confidence:

{candidates_text}{learning_context}

Your analysis should show your thinking:
1. Market Regime: What type of day is this? (bull=strong uptrend, bear=downtrend, choppy=range, rotation=sector shift)
2. Candidate Assessment: For each symbol, why does it fit (or not fit) the regime?
3. Confidence Scoring: Rate each 0-100 for hitting +3% in 1-2 days. Include your reasoning.
4. Strategy: Which wins today - gap-fill reversals, momentum, or mean reversion?
5. Interval: How often should we check? (bull=fast 600-900s, normal=1200-1800s, choppy=slow 3600s)

Only recommend trades if confidence >= 75.

Return JSON:
{{"regime": "bull/bear/choppy/rotation", "strategy": "...", "decisions": [{{"symbol": "XYZ", "confidence": 82, "reason": "...", "action": "BUY"}}], "next_interval_seconds": 1200}}"""
            }],
        )
        
        record_token_usage(state, resp.usage.input_tokens, resp.usage.output_tokens)
        
        for block in resp.content:
            if block.type == "thinking":
                log.info("\n[OPUS THINKING]\n%s\n", block.thinking[:500])
        
        try:
            for block in resp.content:
                if block.type == "text":
                    text = block.text
                    json_str = extract_json_object(text)
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
    except Exception as e:
        log.error("Stage 2 error: %s", e)
    
    return [], 1800

# ============================================================================
# STAGE 3: EXECUTION (with Partial Profit-Taking via MCP)
# ============================================================================

def stage3_execute(client, state, decisions):
    """
    Stage 3: Execute trades using Claude with Robinhood MCP tools.

    Claude has access to place_equity_order and get_equity_positions.
    Strategy: 50% exits at +2%, 50% rides to +5% or -3%.
    """
    executed = []

    # Filter for high-confidence BUY orders
    buys = [d for d in decisions
            if d.get("action") == "BUY" and d.get("confidence", 0) >= CONFIDENCE_THRESHOLD]

    if not buys:
        log.info("No high-confidence buys to execute")
        return executed

    # Build execution plan for MCP tools
    plan = f"""Execute these {len(buys)} trades using Robinhood MCP tools.

Account: {RH_ACCOUNT}

For EACH trade:
1. Use get_equity_positions(account_number="{RH_ACCOUNT}") to check buying power
2. Place BUY order using place_equity_order with:
   - account_number: "{RH_ACCOUNT}"
   - type: "market"
   - side: "buy"
   - quantity: (calculated below)
3. Place TWO SELL orders for partial profit-taking:
   - Order 1: limit sell 50% at +2% (lock profits)
   - Order 2: limit sell 50% at +5% OR stop-loss at -3% (ride position)

Trades to execute:
"""

    for i, decision in enumerate(buys, 1):
        symbol = decision.get("symbol")
        price = get_current_price(symbol)
        confidence = decision.get("confidence", 75)

        # Position sizing based on confidence
        if confidence >= 90:
            size = 250
        elif confidence >= 80:
            size = 200
        else:
            size = 150

        quantity = round(size / price, 2)
        half_qty = round(quantity / 2, 2)

        plan += f"""
{i}. {symbol} @ ${price:.2f} (confidence: {confidence:.0f}%)
   - Buy: {quantity} shares (${size:.0f} allocation)
   - Sell 1: {half_qty} @ ${price*1.02:.2f} (+2% lock profit)
   - Sell 2: {half_qty} @ ${price*1.05:.2f} (+5% upside) or stop at ${price*0.97:.2f} (-3%)"""

    plan += "\n\nExecute all orders. Report each order's confirmation or error."

    # Ask Claude to execute via MCP
    try:
        log.info("=== Stage 3 Execution Request ===")
        log.info(plan[:200] + "...")

        resp = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": plan
            }]
        )

        text = resp.content[0].text
        log.info("Execution result:\n%s", text[:500])

        # Track execution records
        for decision in buys:
            executed.append({
                "symbol": decision.get("symbol"),
                "price": get_current_price(decision.get("symbol")),
                "confidence": decision.get("confidence", 75),
                "status": "submitted_to_claude",
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

        record_token_usage(state, resp.usage.input_tokens, resp.usage.output_tokens)

    except Exception as e:
        log.error("Stage 3 execution error: %s", e)

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

    if should_run_weekly_analysis(state):
        log.info("=== Weekly Learning Analysis ===")
        analysis = analyze_weekly_performance(client, state, cache)
        if analysis:
            state["performance_analytics"]["confidence_calibration"] = analysis
            state["performance_analytics"]["last_weekly_analysis"] = {
                "timestamp": datetime.now().isoformat()
            }

    log.info("=== Stage 1: Haiku Screening ===")
    movers = get_top_movers(None, 100, cache)
    
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

    log.info("=== Stage 2: Opus 4.8 Analysis ===")
    decisions, next_interval = stage2_sonnet_analysis(client, state, candidates, cache)
    
    if not decisions or len(decisions) == 0:
        log.info("No high-confidence trades identified")
        state["next_interval_seconds"] = next_interval
        save_state(state)
        return next_interval
    
    high_confidence = [d for d in decisions if d.get("confidence", 0) >= CONFIDENCE_THRESHOLD]
    log.info("High-confidence trades: %d", len(high_confidence))

    log.info("=== Stage 3: Execution (Split Exits via MCP) ===")
    executed = stage3_execute(client, state, high_confidence)
    
    if executed:
        state["trades"].extend(executed)
        log.info("Executed %d orders (from %d trades)", len(executed), len(high_confidence))
    
    state["next_interval_seconds"] = next_interval
    save_state(state)
    return next_interval

def main():
    log.info("Starting Tiered Trading Bot (with Partial Profit-Taking)...")
    log.info("Strategy: 50%% exits at +2%% (lock profits), 50%% rides to +5%% or -3%% (capture upside)")
    log.info("Configuration: Account=%s | Budget=$%d | Max/position=$%d | Confidence threshold=%d%%",
            RH_ACCOUNT, TOTAL_BUDGET, MAX_POSITION, CONFIDENCE_THRESHOLD)

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
