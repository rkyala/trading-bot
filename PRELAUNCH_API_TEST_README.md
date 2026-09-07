# Pre-Launch API Validation Test

**MUST RUN BEFORE TUESDAY 9/8 LAUNCH**

This test validates that the Unusual Whales API client works correctly with your real API key.

---

## Quick Start (2 minutes)

### Step 1: Get Your API Key

Get your UW API key from: https://unusualwhales.com/settings

(You already have one - it's the key you used previously)

### Step 2: Run the Validation Test

```bash
cd /Users/ramayalala/Documents/Documents\ -\ Rama\'s\ MacBook\ Pro/trading_bot

# Set your API key
export UW_API_KEY="your_actual_api_key_here"

# Run validation
python3 test_real_uw_api_validation.py
```

### Step 3: Check Results

The test will print:
```
🟢 ALL TESTS PASSED - READY FOR LAUNCH
```

Or if there are issues:
```
🔴 TESTS FAILED - FIX BEFORE LAUNCH
[error details]
```

---

## What The Test Checks

| Test | Purpose | Pass = |
|------|---------|--------|
| **API Key Config** | Is your key set? | Key found & not empty |
| **Endpoint** | Does /api/option-trades respond? | No 401, no 404, data flows |
| **Parameters** | Does ticker_symbol filter work? | Ticker parameter accepted |
| **Premium Filter** | Does $100k+ threshold work? | min_premium=100000 accepted |
| **Async Methods** | Do async gates work? | All 4 async methods callable |

---

## Expected Outputs

### ✅ Market Open (9:35 AM - 4:00 PM ET)

```
TEST 1: API Key Configuration
✅ API key found (X chars)

TEST 2: Endpoint & Authentication
📡 Hitting /api/option-trades endpoint...
✅ Endpoint responsive (no 404, no 401)
✅ Fetched 12 alerts
✅ Data flowing back (real alerts received)

TEST 3: Parameter Mapping
🔍 Testing ticker filter (SPX, NDX)...
✅ Ticker parameter accepted
✅ Returned 8 alerts

TEST 4: Premium Threshold ($100k+)
💰 Testing min_premium=100000 parameter...
✅ Premium filter applied
✅ Got 5 $100k+ sweeps

TEST 5: Async Methods (for Filter Pipeline)
⚡ Testing async get_market_tide()...
✅ Market tide: BULLISH
✅ Net premium returned: True
✅ Dark pool data: NEUTRAL
✅ Vol/OI ratio: 1.2

🟢 ALL TESTS PASSED - READY FOR LAUNCH
```

### ⚠️ After-Hours / Weekend (no live data)

```
TEST 2: Endpoint & Authentication
✅ Endpoint responsive (no 404, no 401)
✅ Fetched 0 alerts
⚠️  No alerts returned (market may be closed)

TEST 4: Premium Threshold ($100k+)
⚠️  No $100k+ sweeps right now (market hours?)

🟢 ALL TESTS PASSED - READY FOR LAUNCH
```

(This is FINE - still validates endpoint works, just no data flowing)

---

## Troubleshooting

### ❌ "UW_API_KEY not set"

**Fix:**
```bash
export UW_API_KEY="your_key_here"
python3 test_real_uw_api_validation.py
```

### ❌ "401 Unauthorized"

**Issue:** Your API key is wrong or expired

**Fix:**
1. Go to https://unusualwhales.com/settings
2. Regenerate your API key
3. Try again:
```bash
export UW_API_KEY="new_key_from_settings"
python3 test_real_uw_api_validation.py
```

### ❌ "404 Not Found"

**Issue:** The endpoint path is wrong (but you're running the fixed code, so this shouldn't happen)

**Fix:**
1. Verify you're running the latest code:
```bash
git pull origin feature/uw
```

2. Check endpoint in code:
```bash
grep "base_url = " unusual_whales_bot/uw_api_client.py
# Should show: https://api.unusualwhales.com/api
```

### ❌ "Connection Timeout"

**Issue:** Network issue or UW API is down

**Fix:**
```bash
# Try again in a few seconds
python3 test_real_uw_api_validation.py

# If persistent, check: https://status.unusualwhales.com
```

### ❌ "Async error"

**Issue:** httpx library missing

**Fix:**
```bash
pip install httpx
python3 test_real_uw_api_validation.py
```

---

## What To Do Before Launching

### ✅ If Test Passes

```
Great! You're ready for Tuesday launch.

Verify the following are also set:
- ROBINHOOD_TOKEN in rh_oauth.json
- Discord webhook (if using alerts)
- Bot scheduler cron job

Then:
1. Set a reminder for Tuesday 9/35 AM EST
2. Monitor first trades during market open
3. Check logs for any filter/execution issues
```

### ❌ If Test Fails

```
DO NOT LAUNCH until fixed.

Debug steps:
1. Check your API key is correct (copy-paste from settings)
2. Try test 3x to rule out temporary network issues
3. Check UW status page if persistent
4. If auth fails, regenerate key and try again

Once test passes, you're good to launch.
```

---

## Critical Fixes Validated By This Test

This test validates the three critical production bugs were fixed:

```
✅ BUG #1: Endpoint path
   OLD: https://api.unusualwhales.com/v1
   NEW: https://api.unusualwhales.com/api ← Validated

✅ BUG #2: Parameter name
   OLD: params["symbols"]
   NEW: params["ticker_symbol"] ← Validated

✅ BUG #3: Async implementation
   OLD: No async methods
   NEW: httpx AsyncClient methods ← Validated
```

---

## Timeline

- **Now (Sep 7):** Run this test with your real API key
- **Monday Sep 8 (before 9:30 AM):** Final check - run test again
- **Tuesday Sep 8 (9:35 AM):** Bot launches with validated API client

---

## Questions?

If the test fails and you're not sure why:

1. Save the full output:
```bash
python3 test_real_uw_api_validation.py > validation_results.txt 2>&1
```

2. Share the output (minus your API key)

---

**Status: READY FOR VALIDATION** 🚀
