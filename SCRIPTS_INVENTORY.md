# Scripts Inventory - MCP Live Trading v3.8

## Authentication Scripts

### 1. `robinhood_full_auth.py` ⭐ START HERE
**Purpose:** Initial Robinhood OAuth authentication
**When to run:** Once at startup
**What it does:**
- Prompts for Robinhood email/password
- Handles 2FA (SMS or push)
- Saves ACCESS_TOKEN to `.env.mcp`
- Saves REFRESH_TOKEN to `.mcp_rh_tokens.json`
- Fetches USER_ID and ACCOUNT_NUMBER
- Stores everything needed for MCP

**Output files:**
- `.mcp_rh_tokens.json` - JSON with all credentials
- `.env.mcp` - Environment variables for bot

**Command:**
```bash
python3 robinhood_full_auth.py
```

---

### 2. `test_mcp_auth.py` ⭐ TEST BEFORE TRADING
**Purpose:** Verify OAuth tokens work with Robinhood API
**When to run:** After `robinhood_full_auth.py`, before first bot run
**What it does:**
- Loads credentials from `.mcp_rh_tokens.json`
- Tests user profile API call
- Tests account API call
- Verifies `.env.mcp` is readable
- Confirms token isn't expired

**Output:** ✅ or ❌ on each test

**Command:**
```bash
python3 test_mcp_auth.py
```

---

### 3. `auto_refresh_token.py`
**Purpose:** Refresh access token (expires every 24 hours)
**When to run:** Manually if token expires, or add to cron for >24h operations
**What it does:**
- Reads stored REFRESH_TOKEN from JSON
- Posts to Robinhood OAuth endpoint
- Gets fresh ACCESS_TOKEN
- Updates `.env.mcp` and `.mcp_rh_tokens.json`

**Command:**
```bash
python3 auto_refresh_token.py
```

**Add to cron for auto-refresh (optional):**
```bash
0 18 * * * cd ~/trading_bot && python3 auto_refresh_token.py >> bot_refresh.log 2>&1
```

---

## Bot Scripts

### 4. `bot_v38_mcp_live.py` ⭐ PRODUCTION BOT
**Purpose:** Live trading bot with MCP Robinhood execution
**When to run:** Every 30 minutes during market hours (via cron)
**What it does:**
1. Loads credentials from `.env.mcp`
2. Scans 14 symbols for mean-reversion signals
3. Generates BUY signals (ADX >20, Stoch <30, at Fibonacci)
4. **Executes orders via Robinhood MCP** ← LIVE TRADING
5. Tracks positions + calculates trailing stops
6. Exits on Stoch recovery or -1.5% stop hit
7. Logs everything to `bot_v38_mcp.log`

**Input files (read):**
- `.env.mcp` - Robinhood credentials
- `circuit_breaker_state.json` - Safety limits
- `positions.json` - Open positions

**Output files (written):**
- `positions.json` - Updated open positions
- `circuit_breaker_state.json` - P&L tracking
- `bot_v38_mcp.log` - Execution logs

**Single run:**
```bash
python3 bot_v38_mcp_live.py
```

**Automate (every 30 min during market hours):**
```bash
crontab -e
# Add: */30 9-15 * * 1-5 cd ~/trading_bot && python3 bot_v38_mcp_live.py >> bot_v38_mcp.log 2>&1
```

---

### 5. `bot_v38_signals_only.py`
**Purpose:** Signal generation WITHOUT MCP execution (local testing)
**When to run:** For signal validation/backtesting without live orders
**What it does:**
- Same signal logic as `bot_v38_mcp_live.py`
- Generates entry/exit signals
- Stores positions locally
- NO Robinhood API calls
- NO real money trading

**Useful for:**
- Testing signal quality
- Tuning parameters
- Dry-run validation

**Command:**
```bash
python3 bot_v38_signals_only.py
```

---

## Configuration & Test Files

### 6. `START_HERE.md` ⭐ QUICK GUIDE
**Purpose:** Step-by-step setup (5 minutes to live trading)
**Contents:**
- Step 1: Authenticate
- Step 2: Test authentication
- Step 3: Run test cycle
- Step 4: Enable cron
- Step 5: Monitor
- Troubleshooting section

**Read this first** if you're new to the setup.

---

### 7. `WORKING_PATH.md`
**Purpose:** Technical overview of the solution
**Contents:**
- Problem summary (MCP auth failures)
- Solution architecture
- File reference table
- Why it works

---

### 8. `GO_LIVE_NOW.md`
**Purpose:** Quick deployment guide (less detailed than START_HERE)
**Contents:**
- Run auth script
- Verify credentials
- Start bot
- Configure cron
- Troubleshoot

---

### 9. `TOKEN_REFRESH_DEPLOYMENT.md`
**Purpose:** Token lifecycle management
**Contents:**
- Token refresh architecture
- Bootstrap steps
- Lifecycle table
- Cron configuration

---

### 10. `SCRIPTS_INVENTORY.md` (this file)
**Purpose:** Reference guide for all scripts
**Contents:** Name, purpose, when to run, what it does

---

## Data Files (Auto-Created)

### `.mcp_rh_tokens.json`
**Created by:** `robinhood_full_auth.py`
**Contains:**
```json
{
  "CLIENT_ID": "c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS",
  "USER_ID": "abc123def456",
  "ACCOUNT_NUMBER": "12345678",
  "ROBINHOOD_ACCESS_TOKEN": "eJydUEFuwj...",
  "ROBINHOOD_REFRESH_TOKEN": "eJydUEFgTy...",
  "EXPIRES_IN": 86400
}
```

### `.env.mcp`
**Created by:** `robinhood_full_auth.py`
**Contains:** Environment variables
```
ROBINHOOD_CLIENT_ID=c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS
ROBINHOOD_USER_ID=abc123def456
ROBINHOOD_ACCOUNT_NUMBER=12345678
ROBINHOOD_ACCESS_TOKEN=eJydUEFuwj...
ROBINHOOD_REFRESH_TOKEN=eJydUEFgTy...
```

### `positions.json`
**Created by:** `bot_v38_mcp_live.py` on first trade
**Contains:** Open positions with entry price, stop, peak price
```json
[
  {
    "symbol": "NVDA",
    "qty": 50,
    "entry_price": 123.45,
    "entry_time": "2026-08-23T18:30:00",
    "stop": 121.49,
    "peak": 123.45,
    "mult": 1.0,
    "mcp_status": "success",
    "order_id": "12345678"
  }
]
```

### `circuit_breaker_state.json`
**Created by:** `bot_v38_mcp_live.py` on first run
**Contains:** Safety metrics (P&L, losses, halt status)
```json
{
  "is_halted": false,
  "pnl": 150.25,
  "losses": 3
}
```

### `bot_v38_mcp.log`
**Created by:** `bot_v38_mcp_live.py` on each run
**Contains:** Execution logs with signals, orders, exits

---

## Recommended Workflow

### Initial Setup (5 minutes)
1. Run `robinhood_full_auth.py` → Get credentials
2. Run `test_mcp_auth.py` → Verify they work
3. Run `bot_v38_mcp_live.py` manually → Test one cycle
4. Verify order appears in Robinhood app

### Automate (1 minute)
1. Edit crontab: `crontab -e`
2. Add 30-minute cycle during market hours
3. Done!

### Monitoring (Daily)
1. Check logs: `tail -f bot_v38_mcp.log`
2. Review positions: `cat positions.json`
3. Check P&L: `cat circuit_breaker_state.json`

---

## Troubleshooting Matrix

| Error | Solution |
|-------|----------|
| "❌ .env.mcp not found" | Run `robinhood_full_auth.py` |
| "❌ Unauthorized (HTTP 401)" | Token expired, run `auto_refresh_token.py` |
| "❌ MCP order placement failed" | Check `test_mcp_auth.py` output for details |
| "⚠️ SIGNAL GENERATED but not executed" | Check `bot_v38_mcp.log` for MCP error |
| "Circuit breaker halted" | Drawdown >40% or 29 consecutive losses |

---

## Key Points

✅ **Must do first:** `robinhood_full_auth.py` - Gets real credentials
✅ **Must test next:** `test_mcp_auth.py` - Verifies they work
✅ **Production bot:** `bot_v38_mcp_live.py` - Executes trades via MCP
✅ **Auto-refresh:** `auto_refresh_token.py` - Keeps token fresh
⚠️ **Don't forget:** Add bot to cron for automation
📊 **Monitor:** Logs and position files for performance tracking

---

## What NOT To Do

❌ Don't run multiple bot instances simultaneously (can cause duplicate orders)
❌ Don't modify `bot_v38_mcp_live.py` without testing `bot_v38_signals_only.py` first
❌ Don't let tokens expire (>24h) without running refresh script
❌ Don't disable circuit breaker (it prevents catastrophic losses)
❌ Don't trade more than 0.5% of account size per position (Config.POSITION_SIZE_PCT)

---

## Next Steps

1. **Now:** Read [START_HERE.md](START_HERE.md)
2. **Then:** Run `robinhood_full_auth.py`
3. **Then:** Run `test_mcp_auth.py`
4. **Then:** Run `bot_v38_mcp_live.py` once
5. **Finally:** Add to cron and let it run

**Questions?** Check `bot_v38_mcp.log` for detailed error messages.
