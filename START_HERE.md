# 🚀 START HERE - MCP Live Trading Setup

## The Complete Flow (5 minutes)

### Step 1️⃣: Authenticate (Get Real Credentials)

```bash
cd ~/trading_bot

# This script gets your Robinhood OAuth tokens
python3 robinhood_full_auth.py
```

**What happens:**
1. Prompts for Robinhood email/password
2. Handles 2FA (SMS or push notification)
3. Saves credentials to `.mcp_rh_tokens.json` and `.env.mcp`
4. Fetches your user_id and account_number

**Expected output:**
```
Enter Robinhood Username/Email: your.email@gmail.com
Enter Robinhood Password: ••••••••
Enter 2FA/MFA Code (leave blank if receiving SMS push): 

[+] Authenticating with Robinhood...
[!] App Challenge Triggered. Please approve login on your phone.
Press [ENTER] after approving on your Robinhood App...

✅ AUTHENTICATION & EXTRACTION SUCCESSFUL
-----------------------------------------
CLIENT_ID:           c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS
USER_ID:             abc123def456
ACCOUNT_NUMBER:      12345678
ACCESS_TOKEN:        eJydUEFuwj...
REFRESH_TOKEN:       eJydUEFgTy...
EXPIRES_IN:          86400 seconds
-----------------------------------------
```

---

### Step 2️⃣: Test Authentication (Verify It Works)

```bash
# This script verifies your credentials with Robinhood API
python3 test_mcp_auth.py
```

**Expected output:**
```
[1] Checking for credential files...
✅ .mcp_rh_tokens.json found
✅ .env.mcp found

[2] Loading credentials from JSON...
✅ Access Token: eJydUEFuwj...
✅ User ID: abc123def456
✅ Account Number: 12345678

[3] Testing API authentication...
✅ User profile API call successful
   Username: your_robinhood_username

[4] Testing account API...
✅ Account API call successful
   Account Type: cash
   Buying Power: $10000.00

[5] Checking .env.mcp file...
✅ .env.mcp readable
   ROBINHOOD_ACCESS_TOKEN: eJydUEFuwj...

✅ ALL MCP AUTHENTICATION TESTS PASSED!
```

**If you see ✅ on everything, you're ready to trade.**

---

### Step 3️⃣: Run One Test Cycle

```bash
# This runs ONE full bot cycle to verify MCP order execution
python3 bot_v38_mcp_live.py
```

**Expected output:**
```
====================================================================================================
v3.8 BOT - LIVE MCP EXECUTION
====================================================================================================
✅ MCP Credentials loaded: eJydUEFuwj...

====================================================================================================
CYCLE | 2026-08-23 18:30:00 | MODE: MCP LIVE
====================================================================================================
📊 Volatility: NORMAL (VIX 18.5) → Multiplier: 1.0x
📈 SIGNAL: NVDA BUY 50 @ $123.45
[MCP] Placing order: NVDA x50 @ $123.45
✅ MCP Order executed: Order placed successfully
📋 SCANNED 14 | Found 1 BUY signals
📊 Status: 1 open | 0 exits
====================================================================================================
```

**Check Robinhood app** → Should see order in "Orders" tab

---

### Step 4️⃣: Automate with Cron (Optional but Recommended)

For automatic trading every 30 minutes during market hours:

```bash
# Edit crontab
crontab -e

# Add this line:
*/30 9-15 * * 1-5 cd ~/trading_bot && /usr/bin/python3 bot_v38_mcp_live.py >> bot_v38_mcp.log 2>&1

# Verify it's set
crontab -l
```

**This runs the bot:**
- Every 30 minutes (*/30)
- Between 9:30 AM - 3:59 PM Eastern (9-15 in 24h format)
- Monday-Friday only (1-5)
- Logs to `bot_v38_mcp.log`

---

### Step 5️⃣: Monitor (During Market Hours)

```bash
# Watch logs in real-time
tail -f bot_v38_mcp.log | grep -E "SIGNAL|✅|❌"

# Check daily P&L
cat circuit_breaker_state.json | grep -E "pnl|losses"

# View open positions
cat positions.json | python3 -m json.tool
```

---

## File Reference

| File | Purpose | When to Run |
|------|---------|------------|
| `robinhood_full_auth.py` | Get OAuth tokens | **Once at start** |
| `test_mcp_auth.py` | Verify tokens work | Before first trade |
| `bot_v38_mcp_live.py` | Live bot | Every 30 min (cron) |
| `auto_refresh_token.py` | Refresh stale tokens | If running >24h, run manually or add to cron |

---

## If Something Goes Wrong

### Error: "❌ .mcp_rh_tokens.json not found"
→ You haven't run Step 1 yet
```bash
python3 robinhood_full_auth.py
```

### Error: "❌ Unauthorized (HTTP 401)"
→ Token expired (>24 hours old)
```bash
python3 auto_refresh_token.py
```

### Error: "MCP order placement failed"
→ Check that you approved MCP access in Robinhood settings
→ Run test again: `python3 test_mcp_auth.py`

### Error: "No signal found" after 5 cycles
→ This is normal! Signals require specific market conditions (ADX >20, Stoch <30, at Fibonacci)
→ Wait for higher volatility or check `bot_v38_mcp.log` for why no signals

---

## Success Checklist

After following the steps above, verify:

- ✅ `robinhood_full_auth.py` ran successfully
- ✅ `test_mcp_auth.py` passed all checks
- ✅ `bot_v38_mcp_live.py` placed at least 1 test order
- ✅ Order appears in Robinhood app
- ✅ Cron job configured (optional, for automation)
- ✅ Logs show signal generation every 30 minutes

---

## What Happens Next

🎯 **First 2 weeks (Learning phase):**
- Watch 50-100 trades
- Validate 21-24% win rate
- Monitor drawdown (<5% acceptable)
- Review closed positions for quality

📈 **After 2 weeks (Production):**
- If validation passes → Scale account size
- Enable auto-refresh for token longevity
- Set alerts (optional, via email or Slack)

🚀 **Long term:**
- Bot trades 24/5 (Mon-Fri market hours)
- Auto-refreshes tokens every 24h
- Tracks P&L in circuit_breaker_state.json
- Can be extended to options trading later

---

## Quick Command Reference

```bash
# Get credentials
python3 robinhood_full_auth.py

# Test credentials work
python3 test_mcp_auth.py

# Run one cycle
python3 bot_v38_mcp_live.py

# Refresh token (if >24h old)
python3 auto_refresh_token.py

# Watch live trades
tail -f bot_v38_mcp.log

# View positions
cat positions.json | python3 -m json.tool

# Check P&L
cat circuit_breaker_state.json

# Enable cron
crontab -e
# Add: */30 9-15 * * 1-5 cd ~/trading_bot && /usr/bin/python3 bot_v38_mcp_live.py >> bot_v38_mcp.log 2>&1

# Disable cron
crontab -r
```

---

## You're Now Ready! 🎉

Start with **Step 1** above. Everything else follows.

Questions? Check the logs:
```bash
tail -100 bot_v38_mcp.log
```
