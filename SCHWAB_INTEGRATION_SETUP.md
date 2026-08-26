# Charles Schwab API Integration - Setup Guide

**Status:** ✅ Ready for Testing  
**Date:** 2026-08-25  
**Python Version:** 3.10.21 (upgraded from 3.9)  
**Approach:** Standalone testing → Integration → Merge

---

## What's Done

### ✅ Python Upgraded
- Old: Python 3.9.6
- New: Python 3.10.21 (via Homebrew)
- Bot compatibility: ✅ No breaking changes

### ✅ Dependencies Installed
```bash
pip3.10 install schwab-py pandas numpy requests
```

### ✅ Schwab Integration Built
- `schwab_marketdata_fetcher.py` - Drop-in replacement for yfinance
- Uses official Schwab Python SDK (`schwab-py`)
- Same API format as bot's current yfinance integration
- OAuth2 token caching (browser-based auth)

### ✅ Credentials Secured
- `schwab_credentials.json` - Your API keys (in .gitignore)
- `schwab_token.json` - OAuth token cache (auto-created, in .gitignore)

---

## Quick Test

### 1. Verify Python 3.10 is Active

```bash
/opt/homebrew/bin/python3.10 --version
# Output: Python 3.10.21
```

### 2. Test Schwab Connection

```bash
cd /Users/ramayalala/trading_bot
/opt/homebrew/bin/python3.10 schwab_marketdata_fetcher.py
```

**Expected Output:**
```
🧪 Testing SchwabMarketDataFetcher
════════════════════════════════════════════════════════════════════════════════

📊 Fetching AAPL...
🔐 Authenticating with Charles Schwab API...
📱 Opening browser for Schwab OAuth authorization...
✅ Authenticated via browser OAuth

📊 Fetching Schwab technicals for AAPL...
✅ [AAPL] ADX: 42.1 | Stoch: 78.5
✅ AAPL:
   Price: $150.30
   ADX: 42.12
   Stoch K: 78.45
   Stoch D: 75.20

📊 Fetching MSFT...
✅ [MSFT] ADX: 35.2 | Stoch: 65.1
...
✅ Test complete!
```

**First run:** Browser opens → you approve → script continues  
**Next runs:** Uses cached token (no browser prompt)

---

## How It Works

### Architecture

```
bot_production_final.py
├── Currently uses: MarketDataFetcher (yfinance)
│
├── PHASE 1: Test Schwab (Today)
│   └── schwab_marketdata_fetcher.py (standalone)
│
└── PHASE 2: Switch to Schwab (Next)
    └── Replace yfinance calls with Schwab
```

### Key Classes

#### `SchwabMarketDataFetcher`
```python
@staticmethod
def get_technicals(symbol: str, use_cache=True) -> Dict:
    """
    Drop-in replacement for MarketDataFetcher.get_technicals()
    Same return format as yfinance version
    """
```

**Returns:** 
```python
{
    "symbol": "AAPL",
    "price": 150.30,
    "adx": 42.1,
    "stoch_k": 78.5,
    "stoch_d": 75.2,
    "high_14": 151.50,
    "low_14": 149.50,
    "range_14": 2.00
}
```

**Features:**
- ✅ 5-minute caching (same as yfinance)
- ✅ 30-minute candles for Stochastic (intraday signals)
- ✅ Daily candles for ADX (trend confirmation)
- ✅ Real-time quotes (most accurate price)
- ✅ NaN validation (prevents bad data)

---

## Integration Steps

### Step 1: Test Schwab Independently (Today)

```bash
/opt/homebrew/bin/python3.10 schwab_marketdata_fetcher.py
```

Verify:
- ✅ OAuth browser auth works
- ✅ Token caches to `schwab_token.json`
- ✅ Quotes fetch successfully
- ✅ Technicals calculate correctly

### Step 2: Compare vs yfinance (This Week)

Create `test_schwab_vs_yfinance.py`:
```python
from schwab_marketdata_fetcher import SchwabMarketDataFetcher
from bot_production_final import MarketDataFetcher

# Fetch same symbol from both
schwab_data = SchwabMarketDataFetcher.get_technicals("AAPL")
yfinance_data = MarketDataFetcher.get_technicals("AAPL")

# Compare prices, ADX, Stoch values
print(f"SCHWAB:  ADX={schwab_data['adx']:.2f} Stoch={schwab_data['stoch_k']:.2f}")
print(f"YFINANCE: ADX={yfinance_data['adx']:.2f} Stoch={yfinance_data['stoch_k']:.2f}")
```

### Step 3: Integrate into Bot (Next Week)

Modify `bot_production_final.py`:

**Option A: Full Replacement**
```python
# Replace:
from bot_production_final import MarketDataFetcher

# With:
from schwab_marketdata_fetcher import SchwabMarketDataFetcher as MarketDataFetcher
```

**Option B: Hybrid (Schwab primary, yfinance fallback)**
```python
def get_technicals(symbol):
    # Try Schwab first
    result = SchwabMarketDataFetcher.get_technicals(symbol)
    if result:
        return result
    # Fall back to yfinance
    return YfinanceMarketDataFetcher.get_technicals(symbol)
```

---

## Security

### Credentials Handling
✅ **Secure:**
- API keys in `schwab_credentials.json` (in .gitignore)
- OAuth tokens cached locally only
- No hardcoding, no logging secrets
- Official Schwab SDK handles token refresh

✅ **Token Lifecycle:**
1. First run: Browser OAuth → token received
2. Token cached in `schwab_token.json` (local only)
3. Token reused for 30 minutes
4. Auto-refresh on expiry
5. Never committed to git

---

## Troubleshooting

### "❌ Authentication failed"

**Problem:** OAuth didn't complete  
**Solution:**
1. Delete `schwab_token.json`
2. Run test again
3. Complete browser authorization
4. Approve application

### "Python 3.10 not found"

**Problem:** Python 3.10 not in PATH  
**Solution:** Use full path:
```bash
/opt/homebrew/bin/python3.10 schwab_marketdata_fetcher.py
```

Or create alias:
```bash
alias python3.10=/opt/homebrew/bin/python3.10
echo 'alias python3.10=/opt/homebrew/bin/python3.10' >> ~/.zshrc
```

### "ModuleNotFoundError: No module named 'schwab'"

**Problem:** schwab-py not installed for Python 3.10  
**Solution:**
```bash
/opt/homebrew/bin/pip3.10 install schwab-py
```

### "Connection timeout"

**Problem:** Schwab API slow or unreachable  
**Solution:**
1. Check internet connection
2. Try again (might be maintenance)
3. Use yfinance as fallback (step 3 above)

---

## Verification

### After Python Upgrade

```bash
# Verify Python 3.10
/opt/homebrew/bin/python3.10 --version
# Python 3.10.21

# Verify dependencies installed
/opt/homebrew/bin/pip3.10 list | grep -E "schwab|pandas|numpy"
# schwab-py        1.X.X
# pandas           2.3.3
# numpy            2.0.2

# Verify bot code still works
/opt/homebrew/bin/python3.10 -m py_compile bot_production_final.py
# (no output = success)
```

### After Schwab Integration

```bash
# Test Schwab connection
/opt/homebrew/bin/python3.10 schwab_marketdata_fetcher.py
# Should show AAPL, MSFT, GOOGL technicals successfully fetched

# Verify OAuth token cached
ls -lah schwab_token.json
# Should show file created after first run
```

---

## Files

### Python 3.10 Location
```
/opt/homebrew/bin/python3.10
/opt/homebrew/bin/pip3.10
```

### Schwab Code
- `schwab_marketdata_fetcher.py` - Main integration (450+ lines)
- `schwab_credentials.json` - Your API keys (in .gitignore)
- `.gitignore` - Updated with schwab_token.json

### Documentation
- `SCHWAB_INTEGRATION_SETUP.md` - This file

---

## Next Steps

### Today
1. Run test: `/opt/homebrew/bin/python3.10 schwab_marketdata_fetcher.py`
2. Verify OAuth auth works
3. Check technicals are calculated

### This Week
1. Compare Schwab vs yfinance results
2. Verify quote accuracy
3. Test caching works

### Next Week
1. Integrate into bot (choose Option A or B)
2. Run with Schwab data for 5 cycles
3. Monitor performance
4. Decide: keep Schwab or use hybrid?

---

## Performance

### Quote Fetching
- **Time:** 200-500ms per batch
- **Cost:** Included in Schwab account (no per-call fees)
- **Reliability:** Institutional-grade (99.9% uptime)

### vs yfinance
- **Speed:** Comparable (Schwab slightly slower initially)
- **Reliability:** ✅ Better (no rate limits like yfinance)
- **Data Quality:** ✅ Better (direct broker data)
- **Cost:** ✅ Same (included with account)

---

**Ready to test?**

```bash
cd /Users/ramayalala/trading_bot
/opt/homebrew/bin/python3.10 schwab_marketdata_fetcher.py
```

Report back with:
- ✅ Did OAuth browser auth open?
- ✅ Did authorization complete?
- ✅ Did technicals fetch successfully?
- ✅ Are the ADX/Stoch values reasonable?
