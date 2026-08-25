# Trading Bot - Deployment Guide

## Quick Start: Deploy to New Machine

This guide explains how to set up the trading bot from the `feature/local-bot-production` branch on a new machine.

---

## Prerequisites

- Python 3.9+
- Git
- Robinhood account with API access
- OAuth token from Robinhood (see steps below)

---

## Step 1: Clone Repository

```bash
git clone https://github.com/rkyala/trading-bot.git
cd trading-bot
git checkout feature/local-bot-production
```

---

## Step 2: Install Dependencies

```bash
# Using pip
pip install pandas numpy yfinance requests

# Or using requirements.txt (if available)
pip install -r requirements.txt
```

---

## Step 3: Set Up Configuration Files

### A. Create `config.json`

```json
{
  "account": {
    "agentic_account_number": "YOUR_ACCOUNT_NUMBER",
    "account_size_usd": 10000,
    "position_size_pct": 0.015
  },
  "strategy": {
    "symbol_source": "dynamic",
    "dynamic_symbols": {
      "enabled": true,
      "sources": ["yfinance_trending"],
      "max_symbols": 50,
      "min_market_cap": 10000000000,
      "min_avg_volume": 1000000,
      "price_range": {
        "min": 5,
        "max": 500
      }
    },
    "entry_criteria": {
      "min_adx": 20.0,
      "stoch_oversold": 30.0,
      "fib_levels": [0.236, 0.382, 0.500, 0.618]
    },
    "exit_criteria": {
      "stoch_recovery": 50.0,
      "trailing_stop_pct": 0.015,
      "max_cycles": 6,
      "max_retry_attempts": 3
    },
    "order_execution": {
      "order_type": "limit",
      "slippage_tolerance_pct": 0.5,
      "timeout_seconds": 60
    }
  },
  "robinhood": {
    "agentic_endpoint": "https://agent.robinhood.com/mcp/trading",
    "oauth_file": "rh_oauth.json",
    "protocol_version": "2024-11-05"
  },
  "macro_signals": {
    "fred_api_key": "YOUR_FRED_API_KEY",
    "fed_rate_cache_minutes": 5,
    "13f_scan_cache_hours": 4
  }
}
```

**Fill in:**
- `agentic_account_number`: Your Robinhood account number
- `account_size_usd`: Your trading capital (default: $10,000)
- `fred_api_key`: Get from https://fred.stlouisfed.org (free)

### B. Create `rh_oauth.json`

Get your Robinhood OAuth token:

1. Go to https://agent.robinhood.com
2. Login with your Robinhood credentials
3. Get your access token (see FIND_ROBINHOOD_TOKEN.md for details)
4. Create `rh_oauth.json`:

```json
{
  "access_token": "YOUR_ROBINHOOD_ACCESS_TOKEN",
  "expires_in": 3600
}
```

### C. Create Empty State Files

```bash
# Create empty position tracking
echo '{}' > positions_tracking.json

# Create empty failed orders queue
echo '{}' > failed_orders.json

# Create empty macro signals
echo '{"signals": {}}' > macro_triggers.json
```

---

## Step 4: Verify Setup

```bash
# Test Python environment
python3 -c "import pandas, numpy, yfinance; print('✅ Dependencies OK')"

# Test bot loads config
python3 bot_production_final.py
# Should start and run one cycle successfully
```

---

## Step 5: Set Up Cron Jobs (Optional - for Automated Trading)

### A. Bot Cycles (Every 30 minutes, 9 AM - 3 PM CDT, Weekdays)

```bash
# Edit crontab
crontab -e

# Add these lines:
0,30 9-14 * * 1-5 /path/to/trading_bot/run_bot_cycle.sh >> /path/to/trading_bot/cron.log 2>&1
```

### B. 13-F Signal Scanner (Every 60 seconds during trading hours)

```bash
# Add to crontab:
* 9-14 * * 1-5 /usr/bin/python3 /path/to/trading_bot/test_async_signal_channel.py >> /path/to/trading_bot/13f_signals.log 2>&1
```

### C. Log Rotation (Daily at 2 AM)

```bash
# Add to crontab:
0 2 * * * /usr/sbin/logrotate /path/to/trading_bot/logrotate.conf
```

---

## Step 6: Run Bot

### Manual Test (Single Cycle)

```bash
python3 bot_production_final.py
```

Expected output:
```
2026-08-25 15:52:20,982 | 🔍 Robinhood positions loaded: {'ZM', 'LRCX', 'INTC', 'KEYS', 'U'}
2026-08-25 15:52:26,078 | ⏭️  [18/50] U | Already processed this cycle - skipping
2026-08-25 15:52:36,223 | ✅ Cycle completed successfully
```

### Continuous (Via Cron)

Once cron is set up, the bot runs automatically:
- Every 30 minutes during trading hours
- Enters positions based on technical signals
- Manages exits with stop-loss and take-profit
- Logs to `bot_production.log`

---

## File Structure After Setup

```
trading-bot/
├── bot_production_final.py          ✅ Main trading bot (READY)
├── robinhood_mcp_local.py           ✅ MCP server (READY)
├── symbol_fetcher.py                ✅ Symbol detection (READY)
├── test_async_signal_channel.py     ✅ 13-F scanner (READY)
├── run_bot_cycle.sh                 ✅ Cron wrapper (READY)
├── config.json                      📝 MUST CREATE
├── rh_oauth.json                    📝 MUST CREATE
├── positions_tracking.json          ✅ Auto-created
├── failed_orders.json               ✅ Auto-created
├── macro_triggers.json              ✅ Auto-created
├── bot_production.log               ✅ Auto-created
└── README.md                        ✅ Documentation
```

---

## Critical Features Already Deployed

✅ **Four-Layer Duplicate Prevention**
- Symbol deduplication at startup (FIX #1)
- Cycle-level tracking (FIX #2, #13)
- Retry loop defensive checks (FIX #14, #16)
- Pre-order Robinhood reconciliation (FIX #12)

✅ **MCP Position Fetch (FIXED)**
- Works with account_number parameter (FIX #17)
- Parses data.positions correctly (FIX #17B)
- Prevents duplicate entries via real broker verification

✅ **Production Hardening**
- Circuit breaker (-40% drawdown halt)
- Auto-retry failed orders (up to 3 retries)
- Earnings filter (skip stocks with imminent earnings)
- True trailing stop-loss (uses highest_price)
- Time-based position exits (6-cycle max hold)

---

## Troubleshooting

### OAuth Token Expired

```bash
# Get new token from https://agent.robinhood.com
# Update rh_oauth.json with new access_token
```

### MCP Server Not Starting

```bash
# Check if port is in use
lsof -i :8000

# Restart bot
python3 bot_production_final.py
```

### Duplicate Entries Despite Fixes

1. Check `rh_oauth.json` is valid
2. Verify `config.json` has correct account_number
3. Check `bot_production.log` for MCP errors
4. Ensure positions_tracking.json is writable

### No Trades Executed

1. Check if circuit breaker is halted (portfolio down -40%)
2. Verify market hours (9 AM - 3 PM CDT, weekdays only)
3. Check ADX > 20 and Stoch < 30 conditions in `bot_production.log`
4. Ensure account has buying power

---

## Monitoring

Watch the bot in real-time:

```bash
# Follow live log
tail -f bot_production.log

# Check current positions
cat positions_tracking.json

# Check failed orders queue
cat failed_orders.json
```

---

## Support

For issues:
1. Check `bot_production.log` for errors
2. Review this deployment guide
3. Verify all config files are present and valid
4. Ensure Robinhood OAuth token is not expired

---

**Last Updated:** 2026-08-25  
**Branch:** `feature/local-bot-production`  
**Status:** ✅ Production Ready
