# Tuesday 9/8 Setup: Phase 2 Infrastructure Test

## Prerequisites (Install Once)

```bash
# Python dependencies
pip install redis requests torch transformers nltk

# Start Redis (in separate terminal)
# Option 1: Docker
docker run -d -p 6379:6379 redis:latest

# Option 2: Homebrew (Mac)
brew install redis
redis-server

# Option 3: Manual
# https://redis.io/docs/getting-started/installation/
```

## Tuesday Morning Checklist

```bash
# 1. Navigate to bot directory
cd trading_bot/unusual_whales_bot

# 2. Export environment variables
export UW_API_KEY="your_key_from_user"
export DISCORD_WEBHOOK_URL="your_webhook"

# 3. Verify Redis is running
redis-cli ping  # Should return "PONG"

# 4. Test infrastructure (each in separate terminal or with &)

# Terminal 1: Start sentiment service (Phase 3B optional)
# python sentiment_worker.py &

# Terminal 2: Run bot
python uw_bot.py

# Terminal 3: Run tests (to validate infrastructure)
pytest test_phase2_integration.py -v
```

## What Gets Installed

| Package | Size | Purpose |
|---------|------|---------|
| `torch` | 500MB | PyTorch (needed by FinBERT) |
| `transformers` | 100MB | HuggingFace (FinBERT model loader) |
| `redis` | 10MB | Redis Python client |
| `requests` | 1MB | HTTP library |
| `nltk` | 10MB | Natural language toolkit (fallback) |

**Total**: ~600MB one-time download

## FinBERT First-Run

On first call to `sentiment_worker.py`:
```
📥 Loading FinBERT model (may take 30s on first run)...
[Downloads ~500MB model from HuggingFace]
✅ FinBERT loaded successfully
```

After first run, model is cached locally (~1.5GB total after extraction).

## Fallback: If FinBERT Fails

If `transformers` not installed or FinBERT fails to load:
```python
# sentiment_worker.py falls back to:
logger.warning("FinBERT not available. Using VADER sentiment (lighter, faster)")

# Uses simple keyword matching instead:
positive_words = ["surge", "rally", "beat", "strong", ...]
negative_words = ["plunge", "fall", "miss", "weak", ...]
```

Fallback is **50x faster** (no ML inference), just less accurate.

## Installation Shortcut

If you want FinBERT + full setup ready by Tuesday:

```bash
# One-liner install
pip install redis requests torch transformers nltk && \
echo "✅ Dependencies ready for Tuesday"

# Pre-download FinBERT (optional, saves 30s first run)
python -c "from transformers import pipeline; \
pipeline('text-classification', model='ProsusAI/finbert')"
```

## Phase 3B (Week 2)

sentiment_worker.py only runs if:
1. Redis is running
2. `SENTIMENT_ENABLED = True` in uw_config.py
3. Phase 2 testing passed (Fri 9/11)

Until then, Phase 2 infrastructure tests work without it.

## Troubleshooting

**Redis connection fails?**
```bash
redis-cli ping  # Check if running
redis-server    # Start if not running
```

**FinBERT download slow?**
```bash
# Fallback to lightweight VADER
# Edit sentiment_worker.py line ~60:
# self.use_finbert = False  # Force fallback
```

**pytest not found?**
```bash
pip install pytest
```

---

**All set for Tuesday? 🚀**
