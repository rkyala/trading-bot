# Charles Schwab API Integration

**Status:** 🚀 Ready for Testing  
**Date:** 2026-08-25  
**Integration Plan:** Build standalone → Test → Merge with bot

---

## Overview

This is a **standalone Charles Schwab API client** that fetches:
- ✅ Real-time quotes (bid/ask/last/volume)
- ✅ 30-minute candles (for technicals)
- ✅ Daily candles (for ADX)
- ✅ Account information

**Why separate?** We build and test independently, then integrate once verified working.

---

## Architecture

```
Trading Bot
├── bot_production_final.py (current - uses yfinance)
│
├── PHASE 1: STANDALONE TESTING (Today)
│   ├── schwab_api_client.py (new)
│   ├── test_schwab_client.py (new)
│   └── schwab_credentials.json (credentials)
│
└── PHASE 2: INTEGRATION (Next)
    └── schwab_marketdata_fetcher.py (wrapper)
    └── Integrate into MarketDataFetcher class
```

---

## Quick Start

### 1. Install Dependencies

```bash
cd /Users/ramayalala/trading_bot

# Install requests (for API calls)
pip install requests
```

**Note:** You already have these installed (used by bot).

### 2. Verify Credentials

Check that `schwab_credentials.json` exists and has your credentials:

```bash
cat schwab_credentials.json
```

Should show:
```json
{
  "client_id": "0cO8vLBhMVTm6IUUxxxP2JQuw8oaCdtMOYbZbQ59v064mlgp",
  "client_secret": "J8DGdvItqDGmAvUGL4SbX0Y8yH8B4Oxh0dNLAnfn5FjXYLMLHYRvDZOkKOem5TQw",
  "redirect_uri": "https://developer.schwab.com/oauth2-redirect.html",
  "account_number": "1482-5544",
  ...
}
```

✅ **SECURITY:** `.gitignore` prevents this from being committed to GitHub.

### 3. Run Test Suite

```bash
python3 test_schwab_client.py
```

**Expected output:**
```
════════════════════════════════════════════════════════════════════════════════
                  CHARLES SCHWAB API CLIENT - TEST SUITE
             Standalone Verification Before Bot Integration
════════════════════════════════════════════════════════════════════════════════

TEST 1: Charles Schwab OAuth2 Authentication
════════════════════════════════════════════════════════════════════════════════
🔐 Starting OAuth2 flow...
📱 Opening browser for authorization...
   If browser doesn't open, visit: https://auth.schwab.com/auth?...
⏳ Waiting for authorization callback on http://localhost:8000...
✅ OAuth authorization code received
✅ Authentication successful!
```

Then browser automatically opens for you to authorize:
1. Log in with your Schwab credentials
2. Approve the application access
3. Redirect happens automatically
4. Script continues

---

## Test Details

### TEST 1: Authentication

**What it does:**
- OAuth2 flow with PKCE (secure)
- Browser opens → you approve → code returned
- Exchanges code for access token
- Caches token to `schwab_token_cache.json` (for next runs)

**Expected result:**
```
✅ Authentication successful!
   Token expires in 1800 seconds (~30 minutes)
```

**On subsequent runs:**
```
✅ Loaded cached OAuth token (still valid)
```

---

### TEST 2: Real-Time Quotes

**What it does:**
- Fetches live bid/ask/last prices for: AAPL, MSFT, GOOGL, TSLA, AMZN
- Shows bid/ask spread
- Displays current volume

**Expected output:**
```
✅ Received 5 quotes:

  AAPL
    Bid: $150.25 (size: 1,000)
    Ask: $150.35 (size: 500)
    Last: $150.30
    Spread: $0.1000 (0.07%)
    Volume: 50,000,000
    Timestamp: 2026-08-25T10:15:30Z

  MSFT
    Bid: $420.50 (size: 2,000)
    Ask: $420.60 (size: 1,000)
    ...
```

---

### TEST 3: 30-Minute Candles

**What it does:**
- Fetches last 5 thirty-minute candles for AAPL
- Uses 30m data to match bot's Stochastic calculations

**Expected output:**
```
✅ Received 5 candles:

  Candle 1: 2026-08-25T10:00:00Z
    OHLC: $150.10 | $150.50 | $150.05 | $150.30
    Volume: 1,000,000

  Candle 2: 2026-08-25T10:30:00Z
    OHLC: $150.30 | $150.75 | $150.25 | $150.60
    Volume: 1,100,000
    ...
```

---

### TEST 4: Daily Candles

**What it does:**
- Fetches last 10 daily candles for SPY
- Uses daily data to match bot's ADX calculations

**Expected output:**
```
✅ Received 10 daily candles:

  2026-08-25
    OHLC: $550.10 | $552.50 | $550.00 | $551.30
    Volume: 50,000,000

  2026-08-24
    OHLC: $549.50 | $551.00 | $549.00 | $550.10
    Volume: 45,000,000
    ...
```

---

### TEST 5: Account Information

**What it does:**
- Fetches your account details
- Shows account type, status, cash balance, buying power

**Expected output:**
```
✅ Account information retrieved:

  Account Number: 1482-5544
  Account Type: INDIVIDUAL
  Account Status: ACTIVE

  Balances:
    Cash: $5,000.00
    Buying Power: $20,000.00
    Equity Value: $10,000.00
```

---

## Troubleshooting

### "❌ OAuth authentication failed"

**Problem:** Authorization didn't work  
**Solution:**
1. Check if browser opened
2. If not, manually visit the URL shown in console
3. Log in with Schwab credentials
4. Approve application
5. Copy the URL from redirect (even if error page shows)

### "⚠️  No valid cached token found"

**Problem:** Token cache is empty or expired  
**Solution:**
- Normal on first run
- Script will re-authenticate
- Token cached for future runs (30 min validity)

### "❌ Quote fetch failed: HTTP 401"

**Problem:** Access token is invalid  
**Solution:**
1. Delete `schwab_token_cache.json`
2. Re-run test script
3. Re-authenticate

### "❌ Connection timeout"

**Problem:** Schwab API is slow or unreachable  
**Solution:**
1. Check internet connection
2. Try again (Schwab might be under maintenance)
3. Check market hours (API might be more responsive during trading hours)

---

## Integration Plan

### PHASE 1: Current (Testing)
- ✅ `schwab_api_client.py` - Core client implementation
- ✅ `test_schwab_client.py` - Full test suite
- ✅ `schwab_credentials.json` - Secure storage
- ✅ `SCHWAB_SETUP.md` - This documentation

### PHASE 2: Wrapper Layer (Next)

Create `schwab_marketdata_fetcher.py` that looks like yfinance but uses Schwab:

```python
class SchwabMarketDataFetcher:
    """Drop-in replacement for MarketDataFetcher using Schwab API"""

    def get_technicals(symbol, use_cache=True):
        """
        Fetch 30m candles and daily candles
        Calculate ADX, Stochastic just like yfinance version
        """
        # Get 30m candles from Schwab
        candles_30m = client.get_candles(symbol, '30min', 100)
        # Get daily candles from Schwab
        candles_daily = client.get_candles(symbol, '1d', 60)
        # Calculate technicals (same as before)
        # Return {price, adx, stoch_k, stoch_d, ...}
```

### PHASE 3: Bot Integration (Final)

Update `bot_production_final.py`:

```python
# Add to top of file
from schwab_marketdata_fetcher import SchwabMarketDataFetcher

# In MarketDataFetcher class
@staticmethod
def get_technicals(symbol, use_cache=True):
    """Use Schwab API instead of yfinance"""
    return SchwabMarketDataFetcher.get_technicals(symbol, use_cache)
```

---

## Code Structure

### `schwab_api_client.py` (Main Client)

Key classes:
- `OAuth2Handler` - Handles OAuth redirect callback
- `SchwabAPIClient` - Main API client

Key methods:
- `authenticate()` - OAuth2 flow
- `get_quotes(symbols)` - Real-time prices
- `get_candles(symbol, interval, count)` - Historical data
- `get_account_info()` - Account details

### `test_schwab_client.py` (Test Suite)

Tests:
1. `test_authentication()` - OAuth2 flow
2. `test_real_time_quotes()` - Bid/ask prices
3. `test_candle_data()` - 30m candles
4. `test_daily_candles()` - Daily candles
5. `test_account_info()` - Account details

---

## Security Notes

### Credentials Handling

✅ **What we do:**
- Store credentials in `schwab_credentials.json` (excluded from git)
- Use OAuth2 with PKCE (secure token exchange)
- Cache token locally with expiry check
- Never log sensitive data (access tokens masked)

✅ **What's NOT done:**
- No hardcoding credentials in code
- No committing to GitHub
- No storing passwords (only API tokens)

### Token Lifecycle

1. **First run:** OAuth2 flow → user approves → token received
2. **Token cached:** Stored in `schwab_token_cache.json` (local only)
3. **Token expires:** After 30 minutes
4. **On refresh:** Automatic token refresh using refresh_token
5. **On re-auth:** If refresh fails, full OAuth2 flow again

---

## Performance Expectations

### Quote Fetching
- **Time:** 200-500ms per batch
- **Limit:** 5 symbols per request recommended
- **Rate limit:** 120 requests/minute (Schwab standard)

### Candle Fetching
- **Time:** 500ms-1s per symbol
- **Historical data:** Up to 500 candles per request
- **Rate limit:** Same as quotes

### Overall
- Slower than yfinance initially (OAuth overhead)
- After caching: ~equal performance
- More reliable (Schwab is institutional-grade)

---

## Next Steps

### Today
1. Run `python3 test_schwab_client.py`
2. Verify all 5 tests pass
3. Monitor token caching (check `schwab_token_cache.json` created)
4. Note any issues

### This Week
1. Build `SchwabMarketDataFetcher` wrapper
2. Compare Schwab quotes vs yfinance (for accuracy)
3. Verify candle data matches bot's calculations
4. Create integration tests

### Next Week
1. Integrate into `bot_production_final.py`
2. Run with Schwab data for 5 cycles
3. Compare trades generated vs yfinance
4. Decide: replace yfinance completely or use as fallback?

---

## Files

### Configuration
- `schwab_credentials.json` - Your API credentials (⚠️ NOT in git)
- `schwab_token_cache.json` - Cached OAuth token (auto-created)

### Code
- `schwab_api_client.py` - Main client (400+ lines)
- `test_schwab_client.py` - Test suite (300+ lines)

### Documentation
- `SCHWAB_SETUP.md` - This file

---

## Support

### Schwab Developer Portal
- https://developer.schwab.com
- API Documentation: https://developer.schwab.com/docs
- Rate limits: https://developer.schwab.com/api-docs

### Common Issues

**"Connection refused on localhost:8000"**
- OAuth callback server might already be running
- Kill existing Python process: `pkill -f schwab_api_client`
- Try again

**"Invalid redirect_uri"**
- Check that redirect URI in `schwab_credentials.json` exactly matches Schwab developer portal
- Current: `https://developer.schwab.com/oauth2-redirect.html`

**"Access token expired"**
- Automatic refresh happens if refresh_token available
- Otherwise, re-authenticate

---

## Success Criteria

When all tests pass:

✅ Authentication completes without errors  
✅ Real-time quotes fetch successfully  
✅ 30-minute candles match trading hours  
✅ Daily candles have complete OHLCV data  
✅ Account info retrieves correctly  
✅ Token caching works (faster on 2nd run)  
✅ No sensitive data logged  

**Ready to integrate with trading bot!**

---

**Last Updated:** 2026-08-25  
**Status:** Testing Phase  
**Next:** Run test suite and report results
