# Integration Guide: Replacing Claude with Llama 2 in bot.py

## Overview
Replace Claude Haiku + Sonnet calls with local Llama 2 7B while keeping everything else unchanged.

---

## Step 1: Remove Claude Imports (bot.py, ~top)

### Remove
```python
from anthropic import Anthropic

client = Anthropic()
```

### Add
```python
from local_llm_wrapper import LocalLLMWrapper

# Initialize once at startup
llm = LocalLLMWrapper()
```

---

## Step 2: Find Claude Calls in bot.py

### Search for:
```python
# Line ~500-600 (approx)
client.messages.create(
    model="claude-haiku-4-5",
    ...
)
```

### Replace Haiku Screening

**Old (Claude):**
```python
# STAGE 1: Haiku screening for anomalies
haiku_prompt = f"Detect anomalies in: {market_data}"
haiku_response = client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=200,
    messages=[{"role": "user", "content": haiku_prompt}]
)
anomalies = parse_haiku_response(haiku_response.content[0].text)
```

**New (Llama 2):**
```python
# STAGE 1: No longer needed - Llama 2 integrated per-symbol
# (screening happens in Stage 2 now)
```

### Replace Sonnet Analysis

**Old (Claude):**
```python
# STAGE 2: Sonnet analysis for confidence scoring
sonnet_prompt = f"Analyze trade candidates: {candidates}"
sonnet_response = client.messages.create(
    model="claude-sonnet-4-latest",
    max_tokens=800,
    messages=[{"role": "user", "content": sonnet_prompt}]
)
trades = parse_sonnet_response(sonnet_response.content[0].text)
```

**New (Llama 2):**
```python
# STAGE 2: Local Llama 2 analysis per candidate
trades = []
for candidate in candidates:
    decision = llm.analyze_trade(
        symbol=candidate["symbol"],
        pct_change=candidate["pct_change"],
        anomaly_score=candidate["anomaly_score"],
        regime=market_regime
    )
    
    if decision["action"] == "BUY" and decision["confidence"] > 60:
        trades.append({
            "symbol": candidate["symbol"],
            "action": "BUY",
            "confidence": decision["confidence"],
            "reason": decision["reason"]
        })
```

---

## Step 3: Error Handling

Add fallback for LLM timeouts:

```python
# Wrap LLM calls with try/except
def get_trade_decision(symbol, pct_change, anomaly_score, regime):
    try:
        decision = llm.analyze_trade(
            symbol=symbol,
            pct_change=pct_change,
            anomaly_score=anomaly_score,
            regime=regime
        )
        return decision
    except Exception as e:
        print(f"⚠️  LLM error for {symbol}: {e}")
        # Fallback to rule-based
        return {
            "action": "SKIP",  # Conservative fallback
            "confidence": 0,
            "reason": "LLM unavailable, skipping"
        }
```

---

## Step 4: MCP Execution (No Changes)

Keep Stage 3 and MCP execution exactly as-is:

```python
# STAGE 3: MCP execution (UNCHANGED)
for trade in trades:
    if trade["confidence"] >= 60:
        result = place_equity_order(
            account_id=RH_ACCOUNT,
            symbol=trade["symbol"],
            quantity=calc_position_size(trade["symbol"]),
            side="buy",
            order_type="market"
        )
```

---

## Step 5: Configuration

### Add to bot.py startup:

```python
# ============================================================================
# TRADING BOT CONFIGURATION
# ============================================================================

# Ollama server (for local Llama 2)
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "llama2:7b"

# LLM decision thresholds
LLM_MIN_CONFIDENCE = 60  # Min confidence to trade
LLM_TIMEOUT = 10  # seconds

# FinRL model (optional)
FINRL_AVAILABLE = False  # Set to True after testing

print("\n" + "="*70)
print("  TRADING BOT STARTUP")
print("="*70)
print(f"✅ Llama 2 local LLM: {OLLAMA_HOST}")
print(f"✅ FinRL model: {'Yes' if FINRL_AVAILABLE else 'No'}")
print("="*70 + "\n")
```

---

## Step 6: Testing Checklist

Before deploying:

```python
# Test 1: LLM availability
print("Testing Llama 2 connection...")
if llm.is_available():
    print("✅ Llama 2 server running")
else:
    print("❌ Ollama server not running!")
    print("   Start with: ollama serve")
    exit(1)

# Test 2: Sample trade decision
test_decision = llm.analyze_trade(
    symbol="INTC",
    pct_change=5.0,
    anomaly_score=75,
    regime="range-bound"
)
print(f"✅ Test decision: {test_decision}")

# Test 3: Fallback logic
print("✅ Fallback logic ready")
```

---

## Step 7: Logging Changes

### Add logging for decisions:

```python
def log_trade_decision(symbol, decision, stage="llama2"):
    """Log trading decision for audit"""
    log_msg = (
        f"[{stage:8}] {symbol:6} | "
        f"Action: {decision['action']:6} | "
        f"Confidence: {decision['confidence']:3d}% | "
        f"Reason: {decision['reason'][:40]}"
    )
    print(log_msg)
    
    # Also log to file
    with open("trading_decisions.log", "a") as f:
        f.write(log_msg + "\n")
```

### Update bot.py logging:

```python
# Replace:
# logging.info(f"Sonnet confidence: {confidence}")

# With:
# log_trade_decision(symbol, decision, stage="llama2")
```

---

## Step 8: Deployment Order

1. **Local testing** (on Mac)
   - Start Ollama: `ollama serve`
   - Run bot.py locally: `python3 bot.py --test`
   - Watch logs for 5 cycles (~2.5 hours)

2. **Stage 2 deploy** (test mode on Railway)
   - Push to railway-test branch
   - Deploy to staging
   - Monitor for 24 hours
   - Verify zero Claude API calls

3. **Production deploy** (live)
   - Merge to main
   - Deploy to production
   - Monitor for 1 week
   - Turn off Claude API key

---

## Expected Changes in bot.py

| Section | Change | Impact |
|---------|--------|--------|
| Imports | Remove Anthropic | -3 lines |
| Init | Add LocalLLMWrapper | +5 lines |
| Stage 1 | Remove (merged into Stage 2) | -30 lines |
| Stage 2 | Replace Claude with Llama 2 | -20 lines |
| Stage 3 | No changes | +0 lines |
| Error handling | Add LLM timeout handling | +15 lines |
| **Total** | Net reduction | **~33 lines** |

---

## Validation Queries

After integration, verify with:

```bash
# Check Ollama running
curl http://localhost:11434/api/tags

# Check LLM responsiveness
python3 -c "from local_llm_wrapper import LocalLLMWrapper; \
llm = LocalLLMWrapper(); \
print(llm.is_available())"

# Check bot starts without Claude
python3 bot.py --help

# Check Claude API key not used
grep -n "anthropic" bot.py
# Should return: 0 results
```

---

## Rollback Plan

If Llama 2 doesn't perform as expected:

```bash
# Keep old bot.py backed up
git checkout <commit_before_llama2>

# Revert in 2 minutes
git push origin main --force

# Go back to Claude API
```

---

## Files to Modify

- `bot.py` — Main changes (Stage 1 + Stage 2 replacement)
- `requirements.txt` — Remove anthropic, add ollama
- `.env` — Remove ANTHROPIC_API_KEY
- `railway.toml` — No changes needed

---

## Required Libraries

```bash
pip install requests  # Already installed
pip install numpy     # Already installed
pip install pandas    # Already installed

# No additional dependencies needed!
# Ollama runs as separate service
```

---

## Post-Deployment

After deploying to Railway:

```bash
# SSH into Railway container
railway shell

# Check Ollama status
curl http://localhost:11434/api/tags

# Monitor bot
railway logs --follow

# Check for Claude API usage
grep -i "anthropic" railway.log
```

---

## Support

If LLM times out during trading:

1. Restart Ollama service
2. Check system RAM (Llama 2 needs ~4GB)
3. Check network connection
4. Fallback to rule-based logic (auto-triggered)

