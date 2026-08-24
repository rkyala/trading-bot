# ✅ Pre-Flight Checklist - Local MCP Bot

## Before You Go Live

### Environment & Files
- [ ] `robinhood_mcp_local.py` exists
- [ ] `bot_local_mcp.py` exists
- [ ] `rh_oauth.json` has valid tokens
- [ ] Python 3.9+ installed (`python3 --version`)
- [ ] Dependencies installed:
  ```bash
  pip install pandas numpy yfinance requests
  ```

### Credentials
- [ ] `rh_oauth.json` exists and contains:
  ```json
  {
    "access_token": "eyJ...",
    "refresh_token": "...",
    "expires_in": 825956
  }
  ```
- [ ] Access token is valid (run test to verify)

### Bot Configuration
- [ ] Account size: $10,000
- [ ] Position size: 0.5% ($50 per trade)
- [ ] Entry criteria: ADX >20, Stoch <30, Fibonacci
- [ ] Exit: Trailing stop (-1.5%) or Stoch >50
- [ ] Symbols: 10 liquid tech stocks

---

## Go-Live Steps

### Step 1: Test MCP Connection (5 minutes)
```bash
cd ~/trading_bot
python3 << 'EOF'
import json, subprocess, sys
process = subprocess.Popen([sys.executable, "robinhood_mcp_local.py"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
print("[+] MCP Server: Starting...")
req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
process.stdin.write(json.dumps(req) + "\n")
process.stdin.flush()
resp = json.loads(process.stdout.readline())
if "result" in resp:
    print(f"✅ MCP Connection: OK ({len(resp['result']['tools'])} tools)")
else:
    print(f"❌ MCP Connection: FAILED")
process.terminate()
EOF
```

Expected output: `✅ MCP Connection: OK (3 tools)`

### Step 2: Run Bot Manually (10 minutes)
```bash
# Terminal 1
cd ~/trading_bot
python3 robinhood_mcp_local.py

# Terminal 2 (new)
cd ~/trading_bot
python3 bot_local_mcp.py
```

Expected output:
```
================================================================================
CYCLE | 2026-08-24 HH:MM:SS | PURE LOCAL MCP
================================================================================
✅ Connected to local MCP server
📋 Scanned 10 | Found X signals
================================================================================
```

### Step 3: Verify Log Files (2 minutes)
```bash
# Check bot ran
ls -lh bot_local_mcp.log

# View logs
tail -20 bot_local_mcp.log
```

Expected: Log file created, shows signals and execution

### Step 4: Enable Cron (2 minutes)
```bash
crontab -e
# Add lines from DEPLOY_LOCAL_MCP.md
```

### Step 5: Verify Cron Set (1 minute)
```bash
crontab -l | grep trading_bot
```

Expected: Two lines showing every 30 min execution

---

## Go-Live Verification

After manual test runs:

- [ ] Bot completes without errors
- [ ] Log file has entries
- [ ] Signals are generated (ADX >20, Stoch <30)
- [ ] No "rejected client id" errors in trade execution
- [ ] Cron schedule is set

---

## First 24 Hours Monitoring

```bash
# Check every 1-2 hours
watch -n 300 'tail -30 bot_local_mcp.log | grep -E "CYCLE|SIGNAL|Response"'
```

Or:
```bash
# Watch live
tail -f bot_local_mcp.log
```

---

## Success Indicators (First Week)

✅ Cycle runs every 30 minutes  
✅ Signals generated on 20+ cycles  
✅ 10+ order attempts logged  
✅ No Python errors  
✅ No auth failures  

---

## Emergency Stop

If something goes wrong:

```bash
# Stop all Python bots
pkill -f "bot_local_mcp.py"
pkill -f "robinhood_mcp_local.py"

# Disable cron
crontab -r
```

---

## You're Ready ✅

Run the test command above, verify "✅ MCP Connection: OK", then start the two terminals.

**Go live in 30 seconds.** 🚀
