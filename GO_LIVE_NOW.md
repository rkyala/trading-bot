# 🚀 GO LIVE WITH MCP - QUICK START

## Step 1: Authenticate & Get Real Tokens

```bash
cd ~/trading_bot
python3 robinhood_full_auth.py
```

You'll be prompted for:
1. **Robinhood Email/Username**
2. **Robinhood Password**  
3. **2FA Code** (leave blank if using push notification)

The script will:
- ✅ Log in via Robinhood OAuth
- ✅ Handle 2FA/SMS/Push approval
- ✅ Save `ROBINHOOD_ACCESS_TOKEN` to `.env.mcp`
- ✅ Save `ROBINHOOD_REFRESH_TOKEN` for future token refresh
- ✅ Create `.mcp_rh_tokens.json` with full credential state

**Example output:**
```
==================================================
 Robinhood OAuth Authentication & MCP Token Generator
==================================================

Enter Robinhood Username/Email: your.email@gmail.com
Enter Robinhood Password: ••••••••
Enter 2FA/MFA Code (leave blank if receiving SMS push): 

[+] Initiating authentication request...

[!] Robinhood Challenge Triggered (Type: push)
Please approve the login prompt in your Robinhood mobile app.
Press [ENTER] after approving on your phone...

✅ AUTHENTICATION SUCCESSFUL!
------------------------------------------------------------
CLIENT_ID:      c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS
ACCESS_TOKEN:   eJydUEFuwj...
REFRESH_TOKEN:  eJydUEFgTy...
EXPIRES_IN:     86400 seconds
------------------------------------------------------------

[+] Credentials saved to: /Users/ramayalala/trading_bot/.mcp_rh_tokens.json
[+] Environment file saved to: /Users/ramayalala/trading_bot/.env.mcp
```

---

## Step 2: Verify Credentials Loaded

```bash
cat .env.mcp
```

You should see:
```
ROBINHOOD_CLIENT_ID=c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS
ROBINHOOD_ACCESS_TOKEN=eJydUEFuwj...
ROBINHOOD_REFRESH_TOKEN=eJydUEFgTy...
```

---

## Step 3: Start Live Trading

```bash
python3 bot_v38_mcp_live.py
```

Expected log output:
```
====================================================================================================
v3.8 BOT - LIVE MCP EXECUTION
====================================================================================================
✅ MCP Credentials loaded: eJydUEFuwj...eJydUEFgTy

====================================================================================================
CYCLE | 2026-08-23 18:30:00 | MODE: MCP LIVE
====================================================================================================
📊 Volatility: NORMAL (VIX 18.5) → Multiplier: 1.0x
📈 SIGNAL: NVDA BUY 50 @ $123.45
[MCP] Placing order: NVDA x50 @ $123.45
✅ MCP Order executed: Order placed successfully, ID: 12345...
📋 SCANNED 14 | Found 1 BUY signals
📊 Status: 1 open | 0 exits
====================================================================================================
```

---

## Step 4: Automate with Cron (Optional)

For 30-minute cycles during market hours:

```bash
crontab -e
```

Add:
```bash
# Run every 30 minutes during market hours (9:30 AM - 4 PM ET, Monday-Friday)
*/30 9-15 * * 1-5 cd ~/trading_bot && /usr/bin/python3 bot_v38_mcp_live.py >> bot_v38_mcp.log 2>&1
```

---

## Troubleshooting

### "❌ .env.mcp not found"
→ Run `python3 robinhood_oauth_auth.py` first

### "❌ ROBINHOOD_ACCESS_TOKEN not found in .env.mcp"
→ Check that OAuth succeeded and saved properly: `cat .env.mcp`

### MCP order fails with "Could not resolve authentication method"
→ Your access_token may have expired (24 hours). Run OAuth again or use token refresh:
```bash
python3 refresh_mcp_token.py
```

### "2FA Required" during login
→ Enter the 6-digit SMS code when prompted

### "Robinhood Challenge Triggered"
→ Approve the login request on your Robinhood mobile app, then press ENTER

---

## Architecture

```
robinhood_oauth_auth.py
        ↓ (User runs this once)
   Gets real credentials
        ↓
    Saves to .env.mcp
        ↓
    bot_v38_mcp_live.py
        ↓ (Loads .env.mcp)
    Initializes RobinhoodMCPClient
        ↓ (Every 30 minutes via cron)
    Scans for signals
        ↓
    Calls place_equity_order() via MCP
        ↓
    Tracks positions & exits
```

---

## What's Different from Signal-Only Version

| Feature | `bot_v38_signals_only.py` | `bot_v38_mcp_live.py` |
|---------|---------------------------|----------------------|
| Signal generation | ✅ | ✅ |
| Local position tracking | ✅ | ✅ |
| Robinhood order execution | ❌ | ✅ |
| MCP authentication | ❌ | ✅ (from .env.mcp) |
| Real money trading | ❌ | ✅ |

---

## Next Steps After Going Live

1. **Monitor first 50 trades** - Validate signal quality
2. **Check P&L daily** - Expected 21-24% win rate
3. **Enable token auto-refresh** - Add refresh_mcp_token.py to cron if running >24 hours
4. **Scale account size** - After 2 weeks of consistent profitability

---

## Support

If orders fail to execute via MCP:
1. Check `.env.mcp` has a valid `ROBINHOOD_ACCESS_TOKEN`
2. Check `bot_v38_mcp.log` for exact error message
3. Re-run `robinhood_oauth_auth.py` if token expired
4. Verify your Robinhood account has trading enabled (not restricted)

**You're ready to go live! 🚀**
