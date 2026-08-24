# Dynamic MCP Token Refresh - Deployment Guide

## Problem Solved
**Previous issue:** MCP orders failed with `"Could not resolve authentication method"` because:
- Access tokens expire after 24 hours
- Bot used stale token from startup
- No refresh mechanism existed
- Required manual token generation between trades

**Solution:** Automatic token refresh before each trade cycle.

---

## Token Refresh Architecture

```
BOT STARTUP
    ↓
Every 30 minutes (cron cycle)
    ↓
get_valid_mcp_access_token() called
    ↓
    ├─→ Check .mcp_rh_token.json
    ├─→ Read EXPIRES_IN field
    ├─→ If expires_in < 3600 seconds (1 hour):
    │       └─→ Call refresh_mcp_token.py
    │           └─→ POST to Robinhood OAuth2 endpoint
    │               with stored refresh_token
    │           └─→ Receive new access_token
    │           └─→ Update .mcp_rh_token.json
    │           └─→ Return fresh token
    │
    └─→ Pass token to PositionManager.place_order()
            └─→ MCP order execution proceeds
```

**Key insight:** The refresh token is **permanent** (lives ~90 days). The access token expires hourly but is **auto-refreshed**.

---

## Setup Steps

### Step 1: Bootstrap Initial Refresh Token (One-time)

You need a valid **refresh token** from a prior OAuth flow. If you already have one saved:

```bash
cd ~/trading_bot

# View what you have
cat .mcp_rh_token.json 2>/dev/null || echo "No token file yet"
```

If the file doesn't exist, you need to run the initial OAuth login once. This requires browser permission:

```bash
# (Hypothetical - user already has refresh token from prior session)
python3 oauth_browser.py
# ← Browser opens, you log in, click "Allow agentic trading"
# ← refresh_token generated and saved to .mcp_rh_token.json
```

**Assuming you already have a refresh token,** manually create the initial state:

```bash
cat > .mcp_rh_token.json << 'EOF'
{
  "ROBINHOOD_REFRESH_TOKEN": "<paste_your_refresh_token_here>",
  "ROBINHOOD_ACCESS_TOKEN": "placeholder",
  "TOKEN_TYPE": "Bearer",
  "EXPIRES_IN": 0
}
EOF
```

### Step 2: Do Initial Token Refresh

```bash
python3 refresh_mcp_token.py
```

Expected output:
```
==================================================
 Robinhood MCP Token Refresh Execution
==================================================

Sending token refresh request to Robinhood...
✅ TOKEN REFRESH SUCCESSFUL!

New Access Token: eJydUEFuwj...
Saved updated state to /Users/ramayalala/trading_bot/.mcp_rh_token.json
```

Verify the file was updated:
```bash
cat .mcp_rh_token.json
```

You should see:
- `ROBINHOOD_ACCESS_TOKEN`: New token starting with `eJyd...`
- `ROBINHOOD_REFRESH_TOKEN`: Your persistent refresh token
- `EXPIRES_IN`: Usually 86400 (24 hours)
- `TOKEN_TYPE`: "Bearer"

### Step 3: Deploy Bot with Auto Refresh

```bash
# Copy the new bot version
cp bot_v38_with_token_refresh.py bot_final_production_v38.py

# Test it manually first
python3 bot_final_production_v38.py
```

Expected log output:
```
2026-08-18 14:32:01 | INFO | ====================================================================================================
2026-08-18 14:32:01 | INFO | v3.8 BOT - AUTO TOKEN REFRESH
2026-08-18 14:32:01 | INFO | ====================================================================================================
2026-08-18 14:32:01 | INFO | 
CYCLE | 2026-08-18 14:32:01
2026-08-18 14:32:01 | INFO | Token Status: ✅ VALID
2026-08-18 14:32:01 | INFO | Volatility: NORMAL (VIX 18.5) | Mult: 1.0x
2026-08-18 14:32:01 | INFO | SCANNED 14 | Found 2 signals
2026-08-18 14:32:01 | INFO | SIGNAL: NVDA BUY 50 @ $123.45
2026-08-18 14:32:01 | INFO | [*] MCP order placement (token valid through cache)
2026-08-18 14:32:01 | INFO | Open positions: 1
```

**Key line:** `Token Status: ✅ VALID` means bot has a fresh access token.

### Step 4: Configure Cron for 30-Minute Cycles

```bash
# Edit crontab
crontab -e

# Add these lines (market hours: 9:30 AM - 4:00 PM ET)
# Every 30 minutes during market hours
*/30 9-15 * * 1-5 cd ~/trading_bot && /usr/bin/python3 bot_final_production_v38.py >> bot_v38.log 2>&1
```

### Step 5: Monitor Token Refresh in Logs

```bash
# Watch logs in real-time
tail -f bot_v38.log | grep -E "Token Status|Token near|Token refresh"

# Expected sequence over 24 hours:
# 09:30 - Token Status: ✅ VALID (expires_in: 86400)
# 10:00 - Token Status: ✅ VALID (expires_in: 85920)
# ...
# 14:30 - Token Status: ⚠️  REFRESH NEEDED (expires_in: 1200)
#         [*] Token near expiration - refreshing...
#         ✅ Token refreshed
# 15:00 - Token Status: ✅ VALID (expires_in: 86400) ← Fresh!
```

---

## Token Lifecycle

| Time | Status | Action | expires_in |
|------|--------|--------|-----------|
| T+0h | ✅ Valid | Pass to MCP | 86400 |
| T+1h | ✅ Valid | Pass to MCP | 82800 |
| T+23h | ✅ Valid | Pass to MCP | 3600 |
| T+23.95h | ⚠️ Near expiry | Auto-refresh via POST | 1200 |
| T+24h | ✅ Fresh | Pass to MCP | 86400 |

---

## What if Refresh Token Expires?

Refresh tokens last ~90 days. If it expires:

```
Error in refresh_token_now():
  ❌ Refresh Failed (HTTP 400): {"error": "invalid_grant"}
  Note: If the refresh token has expired or been revoked,
        you must run the initial login flow...
```

**Fix:** Run initial OAuth one more time to get a new refresh token pair:

```bash
python3 oauth_browser.py
# ← Browser opens, auth succeeds, new refresh_token saved
```

---

## Dry-run Testing

Before enabling cron, test the full token refresh cycle manually:

```bash
# Simulate 23+ hours passing
# Manually set expires_in to 1000 (low)
python3 << 'EOF'
import json
from pathlib import Path

state = json.loads(Path(".mcp_rh_token.json").read_text())
state["EXPIRES_IN"] = 1000  # Force refresh
Path(".mcp_rh_token.json").write_text(json.dumps(state, indent=2))
EOF

# Run bot - should auto-refresh
python3 bot_final_production_v38.py

# Check logs
tail -20 bot_v38.log | grep -i "refresh"
```

---

## Summary: What Auto Refresh Gives You

✅ **No manual token generation needed**
✅ **Tokens auto-refresh 1 hour before expiry**
✅ **24/7 trading capability for weeks**
✅ **Clean logs showing token health**
✅ **Fallback: MCP browser auth on first request** (if token file missing)

**Next step:** Deploy to Railway with this configuration for live trading.
