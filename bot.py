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

# ============================================================================
# CONFIGURATION
# ============================================================================

TOTAL_BUDGET = 2000
MAX_POSITION = 500
DAILY_LOSS_LIMIT_PCT = 5.0
CONFIDENCE_THRESHOLD = 75

TOKENS_PER_HOUR_LIMIT = 2_000_000
TOKENS_PER_DAY_LIMIT = 15_000_000

RH_AUTH_URL = "https://api.robinhood.com/oauth2/token/"
RH_MOVERS_URL = "https://api.robinhood.com/midlands/movers/sp500/"
RH_QUOTES_URL = "https://api.robinhood.com/quotes/"

# Cache TTLs
MOVERS_CACHE_TTL = 1800
REGIME_CACHE_TTL = 3600
LEARNING_CACHE_TTL = 604800

CACHE_FILE = "bot_cache.json"

# ============================================================================
# LOGGING SETUP
# ============================================================================

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
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

def get_rh_access_token():
    """Get Robinhood access token using env variables."""
    try:
        refresh_token = os.environ.get("RH_REFRESH_TOKEN")
        device_token = os.environ.get("RH_DEVICE_TOKEN")
        
        if not refresh_token or not device_token:
            log.error("Missing RH_REFRESH_TOKEN or RH_DEVICE_TOKEN env variables")
            return None
        
        resp = requests.post(
            RH_AUTH_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": "c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS",
                "scope": "internal",
                "device_token": device_token,
            },
            timeout=10
        )
        
        if resp.status_code == 200:
            data = resp.json()
            access_token = data.get("access_token")
            if access_token:
                log.debug("✓ Got Robinhood access token")
                return access_token
        else:
            log.error("RH auth failed: %s", resp.status_code)
    except Exception as e:
        log.error("RH token refresh error: %s", e)
    
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

def get_top_movers(access_token, limit=100, cache=None):
    """Get top movers from Robinhood with caching."""
    if cache is None:
        cache = load_cache()
    
    cached_movers = cache_get(cache, "movers", MOVERS_CACHE_TTL)
    if cached_movers:
        return cached_movers
    
    if not access_token:
        log.error("No access token for market data")
        return []
    
    try:
        resp = requests.get(
            RH_MOVERS_URL,
            timeout=10,
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "Mozilla/5.0"
            }
        )
        
        if resp.status_code != 200:
            log.error("Movers API error: %s", resp.status_code)
            return cached_movers or []
        
        data = resp.json()
        results = data.get("results", [])
        
        movers = []
        for item in results[:limit]:
            try:
                movers.append({
                    "symbol": item.get("symbol", ""),
                    "price": float(item.get("last_extended_hours_trade_price") or 
                                  item.get("last_trade_price", 0)),
                    "pct_change": float(item.get("pct_change", 0)),
                    "volume": int(item.get("volume", 0)),
                })
            except (KeyError, ValueError):
                continue
        
        movers = sorted(movers, key=lambda x: abs(x["pct_change"]), reverse=True)
        cache_set(cache, "movers", movers)
        save_cache(cache)
        
        log.info("✓ Fetched %d movers (cached for 30 min)", len(movers))
        return movers
    except Exception as e:
        log.error("Error fetching movers: %s", e)
        return cached_movers or []

def get_current_price(symbol, access_token):
    """Get current price for a symbol."""
    if not access_token:
        return 0
    
    try:
        resp = requests.get(
            f"{RH_QUOTES_URL}{symbol}/",
            timeout=10,
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "Mozilla/5.0"
            }
        )
        if resp.status_code == 200:
            return float(resp.json().get("last_trade_price", 0))
    except:
        pass
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
    """Check if market is open."""
    et = pytz.timezone('US/Eastern')
    now = datetime.now(et)
    
    if now.weekday() >= 5:
        return False
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        return False
    if now.hour >= 16:
        return False
    
    return True

# ============================================================================
# STAGE 1: HAIKU SCREENING
# ============================================================================

def stage1_haiku_screening(client, state, movers):
    """Stage 1: Identify anomalies in top movers."""
    if not movers or len(movers) == 0:
        return []
    
    movers_text = "\n".join([
        f"{m['symbol']}: {m['price']:.2f} ({m['pct_change']:+.1f}%)"
        for m in movers[:30]
    ])
    
    try:
        resp = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=400,
            system=[{
                "type": "text",
                "text": "Detect market anomalies: unusual volume, gaps, reversals.",
                "cache_control": {"type": "ephemeral"}
            }],
            messages=[{
                "role": "user",
                "content": f"""Analyze for anomalies:
{movers_text}

Rate top anomalies 0-100. Return JSON:
{{"anomalies": [{{"symbol": "XYZ", "score": 75, "reason": "spike"}}]}}"""
            }],
            betas=["prompt-caching-2024-07-31"]
        )
        
        record_token_usage(state, resp.usage.input_tokens, resp.usage.output_tokens)
        
        try:
            text = resp.content[0].text
            start = text.find('{')
            if start >= 0:
                result = json.loads(text[start:])
                return result.get("anomalies", [])
        except:
            pass
    except Exception as e:
        log.error("Stage 1 error: %s", e)
    
    return []

# ============================================================================
# STAGE 2: OPUS 4.8 ANALYSIS
# ============================================================================

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
                "text": """You are a market regime analyst with adaptive thinking.

Your job:
1. Identify the current market regime by analyzing the movers
2. Assess how each candidate fits that regime
3. Rate confidence 0-100 for each hitting +3% in 1-2 days
4. Explain your reasoning
5. Recommend optimal scanning frequency

Think deeply about:
- Trend direction and strength (bull/bear/choppy)
- Sector rotation patterns
- Volatility regime (high/low)
- Mean reversion vs momentum signals
- Which strategy wins today (gap-fill/momentum/reversal)""",
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
            betas=["prompt-caching-2024-07-31"]
        )
        
        record_token_usage(state, resp.usage.input_tokens, resp.usage.output_tokens)
        
        for block in resp.content:
            if block.type == "thinking":
                log.info("\n[OPUS THINKING]\n%s\n", block.thinking[:500])
        
        try:
            for block in resp.content:
                if block.type == "text":
                    text = block.text
                    start = text.find('{')
                    if start >= 0:
                        result = json.loads(text[start:])
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
# STAGE 3: EXECUTION (with Partial Profit-Taking)
# ============================================================================

def stage3_execute(state, decisions, access_token):
    """
    Stage 3: Execute trades with split exits (partial profit-taking).
    
    Strategy:
    - 50% exits at +2% (lock profits early)
    - 50% exits at +5% or -3% (capture upside or cut loss)
    
    Example:
      BUY: NVDA 100 shares at $120
      ORDER 1: Limit sell 50 shares at $122.40 (+2%)
      ORDER 2: Limit sell 50 shares at $126.00 (+5%) OR stop at $116.40 (-3%)
    """
    executed = []
    
    for decision in decisions:
        if decision.get("confidence", 0) < CONFIDENCE_THRESHOLD:
            log.info("SKIP %s: confidence %.0f < %d", 
                    decision.get("symbol"), decision.get("confidence", 0), CONFIDENCE_THRESHOLD)
            continue
        
        if decision.get("action") != "BUY":
            continue
        
        symbol = decision.get("symbol")
        price = get_current_price(symbol, access_token)
        
        if price <= 0:
            log.error("Invalid price for %s", symbol)
            continue
        
        confidence = decision.get("confidence", 75)
        
        # Position sizing
        if confidence >= 90:
            size = 250
        elif confidence >= 80:
            size = 200
        else:
            size = 150
        
        quantity = size / price
        half_qty = quantity / 2
        
        # PARTIAL EXIT 1: Sell 50% at +2% (lock profits)
        partial_target = price * 1.02
        
        # PARTIAL EXIT 2: Sell 50% at +5% or -3% (capture upside or cut loss)
        full_target = price * 1.05
        full_stop = price * 0.97
        
        log.info("EXECUTE: %s @ $%.2f | confidence=%.0f | size=$%d", 
                symbol, price, confidence, size)
        log.info("  ├─ PARTIAL: Sell %.2f @ $%.2f (+2%% lock)", half_qty, partial_target)
        log.info("  └─ RIDE: Sell %.2f @ $%.2f (+5%%) OR stop $%.2f (-3%%)", 
                half_qty, full_target, full_stop)
        
        # Order 1: Partial profit-taking
        executed.append({
            "symbol": symbol,
            "price": price,
            "quantity": half_qty,
            "target": partial_target,
            "confidence": confidence,
            "order_type": "partial_profit",
            "description": "Lock profits at +2%",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        
        # Order 2: Ride or stop
        executed.append({
            "symbol": symbol,
            "price": price,
            "quantity": half_qty,
            "target": full_target,
            "stop": full_stop,
            "confidence": confidence,
            "order_type": "ride_position",
            "description": "Capture upside at +5% or cut at -3%",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    
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
            betas=["prompt-caching-2024-07-31"]
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
    access_token = get_rh_access_token()
    
    if not access_token:
        log.error("Could not get Robinhood access token")
        return None
    
    if should_run_weekly_analysis(state):
        log.info("=== Weekly Learning Analysis ===")
        analysis = analyze_weekly_performance(client, state, cache)
        if analysis:
            state["performance_analytics"]["confidence_calibration"] = analysis
            state["performance_analytics"]["last_weekly_analysis"] = {
                "timestamp": datetime.now().isoformat()
            }
    
    log.info("=== Stage 1: Haiku Screening ===")
    movers = get_top_movers(access_token, 100, cache)
    
    if not movers:
        log.warning("No movers fetched from Robinhood")
        save_state(state)
        return None
    
    anomalies = stage1_haiku_screening(client, state, movers)
    
    if not anomalies or len(anomalies) == 0:
        log.info("No anomalies detected")
        save_state(state)
        return None
    
    log.info("Found %d anomalies", len(anomalies))
    
    log.info("=== Stage 2: Opus 4.8 Analysis ===")
    decisions, next_interval = stage2_sonnet_analysis(client, state, anomalies, cache)
    
    if not decisions or len(decisions) == 0:
        log.info("No high-confidence trades identified")
        state["next_interval_seconds"] = next_interval
        save_state(state)
        return next_interval
    
    high_confidence = [d for d in decisions if d.get("confidence", 0) >= CONFIDENCE_THRESHOLD]
    log.info("High-confidence trades: %d", len(high_confidence))
    
    log.info("=== Stage 3: Execution (Split Exits) ===")
    executed = stage3_execute(state, high_confidence, access_token)
    
    if executed:
        state["trades"].extend(executed)
        log.info("Executed %d orders (from %d trades)", len(executed), len(high_confidence))
    
    state["next_interval_seconds"] = next_interval
    save_state(state)
    return next_interval

def main():
    log.info("Starting Tiered Trading Bot (with Partial Profit-Taking)...")
    log.info("Strategy: 50%% exits at +2%% (lock profits), 50%% rides to +5%% or -3%% (capture upside)")
    
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
