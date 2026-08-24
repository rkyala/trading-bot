# Official Robinhood MCP - Quick Start

## Prerequisites

- Node.js installed (`brew install node` on Mac)
- OAuth credentials in `rh_oauth.json` ✅ (already have)
- Python 3.9+ ✅ (already have)

## Run in 2 Terminals

**Terminal 1 - Start Official MCP Server:**
```bash
cd ~/trading_bot
npx -y @modelcontextprotocol/server-robinhood
```

You should see:
```
[+] Starting Robinhood MCP server...
✅ Server ready on stdio
```

**Terminal 2 - Run Trading Bot:**
```bash
cd ~/trading_bot
python3 bot_with_official_mcp.py
```

Expected output:
```
================================================================================
CYCLE | 2026-08-24 00:45:00 | OFFICIAL ROBINHOOD MCP
================================================================================
✅ Connected to Robinhood account
📈 SIGNAL: NFLX BUY 1 @ $79.62
   ✅ Order abc123def456
📋 Scanned 10 | Found 1 signals
================================================================================
```

## Enable Cron (Automatic Trading)

Once verified, automate with cron:

```bash
crontab -e

# Add this line (30-minute cycles, 9:30 AM - 3:59 PM ET, Mon-Fri):
*/30 9-15 * * 1-5 cd ~/trading_bot && npx -y @modelcontextprotocol/server-robinhood &
*/30 9-15 * * 1-5 sleep 2 && cd ~/trading_bot && python3 bot_with_official_mcp.py >> bot_official_mcp.log 2>&1
```

## Architecture

```
┌─────────────────────────────────────────┐
│     Your Mac (100% Local)               │
├─────────────────────────────────────────┤
│                                         │
│  Terminal 1:                            │
│  npx @modelcontextprotocol/...-robinhood│
│  └─ Official Robinhood MCP Server       │
│     (Node.js process listening stdio)   │
│                                         │
│  Terminal 2:                            │
│  python3 bot_with_official_mcp.py       │
│  └─ Trading Bot                         │
│     (Python sending JSON-RPC)           │
│                                         │
└──────────────┬──────────────────────────┘
               │ HTTPS (OAuth)
               ↓
        Robinhood API
```

## Workflow

1. **One-time setup:**
   - ✅ `rh_oauth.json` (already have)
   - ✅ Node.js installed
   - ✅ Bot script ready

2. **Manual testing:**
   ```bash
   # Terminal 1
   npx -y @modelcontextprotocol/server-robinhood
   
   # Terminal 2 (new terminal)
   python3 bot_with_official_mcp.py
   ```

3. **Live trading (cron):**
   - Bot runs every 30 minutes automatically
   - Logs saved to `bot_official_mcp.log`
   - Monitor with: `tail -f bot_official_mcp.log`

## Verify Working

**Check recent orders:**
```bash
grep "✅ Order" bot_official_mcp.log | head -10
```

**Check for errors:**
```bash
grep "❌" bot_official_mcp.log
```

**Monitor live:**
```bash
tail -f bot_official_mcp.log | grep -E "SIGNAL|Order|✅|❌"
```

## Next: Full Automation

After verifying 5-10 successful trades, enable full automation:

```bash
# Add to crontab (as above)
crontab -e

# Verify cron is active
crontab -l | grep trading_bot
```

## Support

- **"npx: command not found"** → Install Node.js
- **"No response from MCP server"** → Server not started in Terminal 1
- **"API auth error"** → Check `rh_oauth.json` has valid tokens
- **No signals found** → Market conditions may not meet criteria (ADX >20, Stoch <30)

---

**You're ready to go live!** 🚀

Start with Terminal 1 + Terminal 2, then enable cron after verification.
