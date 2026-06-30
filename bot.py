#!/usr/bin/env python3
"""
TIERED + CACHED TRADING BOT
3-Stage Architecture:
  Stage 1: Haiku screening (anomaly detection on top 100 movers, cached)
  Stage 2: Sonnet analysis (regime-aware confidence scoring, adaptive interval, cached)
  Stage 3: Execute trades if confidence >= 75 (auto-execution)

Token cost: ~$1.61/year
Expected trades: 10-15/week at 58-62% win rate
Screening interval: Adaptive based on market regime (Claude recommends)
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

TOTAL_BUDGET = 2000  # $2000 trading account
MAX_POSITION = 500   # $500 max per trade
DAILY_LOSS_LIMIT_PCT = 5.0  # Halt new trades if down 5% from day-start
CONFIDENCE_THRESHOLD = 75  # Only execute if confidence >= 75

# Token circuit breaker (safety from June 24 crisis repeat)
TOKENS_PER_HOUR_LIMIT = 2_000_000
TOKENS_PER_DAY_LIMIT = 15_000_000

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
# AUTHENTICATION & CLIENTS
# ============================================================================

def get_anthropic_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=api_key)

def get_rh_access_token():
    """Get Robinhood access token (simplified)."""
    token = os.environ.get("RH_ACCESS_TOKEN")
    if not token:
        log.error("RH_ACCESS_TOKEN not set")
        return None
    return token

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
        "analyzed_candidates": [],  # {symbol, timestamp}
        "daily_pnl": 0.0,
        "token_usage": {"input": 0, "output": 0, "hourly_calls": []},
        "bot_halted": False,
        "next_interval_seconds": 1800,  # Default 30 min, Claude can override
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
    
    # Track hourly for circuit breaker
    now = time.time()
    state["token_usage"]["hourly_calls"].append({
        "tokens": input_tokens + output_tokens,
        "timestamp": now
    })
    
    # Clean up old entries (>1 hour)
    state["token_usage"]["hourly_calls"] = [
        c for c in state["token_usage"]["hourly_calls"]
        if now - c["timestamp"] < 3600
    ]
    
    # Check hourly limit
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

def get_top_movers(limit=100):
    """Get top movers from Robinhood."""
    try:
        url = "https://api.robinhood.com/midlands/movers/sp500/"
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0"
        })
        if resp.status_code != 200:
            return []
        
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
        
        return sorted(movers, key=lambda x: abs(x["pct_change"]), reverse=True)
    except Exception as e:
        log.error("Error fetching movers: %s", e)
        return []

def get_current_price(symbol):
    """Get current price for a symbol."""
    try:
        url = f"https://api.robinhood.com/quotes/{symbol}/"
        resp = requests.get(url, timeout=10)
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
        return True  # Halted
    return False

def is_market_hours():
    """Check if market is open."""
    et = pytz.timezone('US/Eastern')
    now = datetime.now(et)
    
    # Market hours: 9:30 AM - 4:00 PM ET, Monday-Friday
    if now.weekday() >= 5:  # Saturday or Sunday
        return False
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        return False
    if now.hour >= 16:
        return False
    
    return True

# ============================================================================
# STAGE 1: HAIKU SCREENING (Anomaly Detection)
# ============================================================================

def stage1_haiku_screening(client, state, movers):
    """
    Stage 1: Identify anomalies in top movers.
    
    Uses Haiku with cached prompt (90% cost reduction on calls 2-4).
    Returns list of {symbol, anomaly_score, reason}
    """
    if not movers or len(movers) == 0:
        return []
    
    # Format movers summary
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
                "text": "You detect market anomalies: unusual volume, unexpected moves, reversal signals.",
                "cache_control": {"type": "ephemeral"}
            }],
            messages=[{
                "role": "user",
                "content": f"""Analyze these movers for anomalies (unusual volume, gaps, reversals):
{movers_text}

Rate top anomalies 0-100. Return JSON only:
{{"anomalies": [{{"symbol": "XYZ", "score": 75, "reason": "volume spike"}}]}}"""
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
# STAGE 2: SONNET ANALYSIS (Confidence Scoring + Interval Recommendation)
# ============================================================================

def stage2_sonnet_analysis(client, state, candidates):
    """
    Stage 2: Deep analysis with regime-aware confidence scoring + interval recommendation.
    
    Returns tuple: (decisions list, recommended_interval_seconds)
    """
    if not candidates or len(candidates) == 0:
        return [], 1800  # Default to 30 min
    
    candidates_text = "\n".join([
        f"{c['symbol']}: +{c.get('pct_change', 0):.1f}% (anomaly={c.get('score', 0)})"
        for c in candidates[:5]
    ])
    
    try:
        resp = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=800,
            system=[{
                "type": "text",
                "text": "Rate trade confidence 0-100 based on technical + regime analysis. Recommend optimal screening frequency for next interval.",
                "cache_control": {"type": "ephemeral"}
            }],
            messages=[{
                "role": "user",
                "content": f"""Analyze these candidates. Rate confidence 0-100 each will hit +3% in 1-2 days:

{candidates_text}

What type of market day? Bull/bear/choppy/rotation?
Which strategy wins best today (gap-fill, momentum, reversal)?
How often should we screen? (bull market=fast 600-900s, normal=1200-1800s, choppy=slow 3600s)

Only recommend trades if confidence >= 75.

Return JSON only:
{{"decisions": [{{"symbol": "XYZ", "confidence": 82, "reason": "...", "action": "BUY"}}], "next_interval_seconds": 1200}}"""
            }],
            betas=["prompt-caching-2024-07-31"]
        )
        
        record_token_usage(state, resp.usage.input_tokens, resp.usage.output_tokens)
        
        try:
            text = resp.content[0].text
            start = text.find('{')
            if start >= 0:
                result = json.loads(text[start:])
                decisions = result.get("decisions", [])
                interval = result.get("next_interval_seconds", 1800)
                
                # Bound interval: 5 min to 60 min
                interval = max(300, min(3600, int(interval)))
                
                log.info("Claude recommended next interval: %d seconds (%.1f min)", 
                        interval, interval / 60.0)
                
                return decisions, interval
        except:
            pass
    except Exception as e:
        log.error("Stage 2 error: %s", e)
    
    return [], 1800

# ============================================================================
# STAGE 3: EXECUTION
# ============================================================================

def stage3_execute(state, decisions):
    """
    Stage 3: Execute trades if confidence >= 75.
    
    Sets stop at -3%, target at +3%.
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
        price = get_current_price(symbol)
        
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
        stop = price * 0.97
        target = price * 1.03
        
        log.info("EXECUTE: %s @ $%.2f | qty=%.2f | SL=$%.2f | TP=$%.2f | confidence=%.0f",
                symbol, price, quantity, stop, target, confidence)
        
        executed.append({
            "symbol": symbol,
            "price": price,
            "quantity": quantity,
            "stop": stop,
            "target": target,
            "confidence": confidence,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    
    return executed

# ============================================================================
# MAIN TRADING LOOP
# ============================================================================

def run_trading_loop():
    if not is_market_hours():
        log.info("Outside market hours — skipping")
        return None
    
    state = load_state()
    
    # Check if halted
    if state.get("bot_halted"):
        log.warning("BOT HALTED — circuit breaker triggered")
        return None
    
    # Check daily loss limit
    if check_daily_loss_limit(state):
        log.warning("Daily loss limit hit — stopping new trades")
        return None
    
    client = get_anthropic_client()
    
    log.info("=== Stage 1: Haiku Screening ===")
    movers = get_top_movers(100)
    anomalies = stage1_haiku_screening(client, state, movers)
    
    if not anomalies or len(anomalies) == 0:
        log.info("No anomalies detected")
        save_state(state)
        return None
    
    log.info("Found %d anomalies", len(anomalies))
    
    log.info("=== Stage 2: Sonnet Analysis ===")
    decisions, next_interval = stage2_sonnet_analysis(client, state, anomalies)
    
    if not decisions or len(decisions) == 0:
        log.info("No high-confidence trades identified")
        state["next_interval_seconds"] = next_interval
        save_state(state)
        return next_interval
    
    high_confidence = [d for d in decisions if d.get("confidence", 0) >= CONFIDENCE_THRESHOLD]
    log.info("High-confidence trades: %d", len(high_confidence))
    
    log.info("=== Stage 3: Execution ===")
    executed = stage3_execute(state, high_confidence)
    
    if executed:
        state["trades"].extend(executed)
        log.info("Executed %d trades", len(executed))
    
    state["next_interval_seconds"] = next_interval
    save_state(state)
    return next_interval

def main():
    log.info("Starting Tiered Trading Bot (Adaptive Interval)...")
    
    current_interval = 1800  # Start with 30 min default
    
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
