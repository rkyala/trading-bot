# Get Robinhood OAuth Token - Quick Start

## 3-Minute Setup

### Step 1: Run Token Generator
```bash
cd ~/trading_bot
python3 get_robinhood_token.py
```

### Step 2: Choose Method
```
How would you like to get your token?

[1] From Robinhood web app (Recommended) ← EASIEST
[2] Authenticate via API directly
[3] Paste existing token
[4] Exit

Enter choice: 1
```

### Step 3: Get Token from Robinhood Web
**If you choose [1]:**

1. Go to: https://robinhood.com/settings
2. Click: **Account** → **Connected Applications**
3. Find: **"Claude Trading Bot"** or similar
4. Copy: **Authorization Token**
5. Paste into script

**Result:**
```
✅ Token saved to ~/.robinhood_oauth
✅ Token saved to ~/trading_bot/.env
```

### Step 4: Verify It Works
```bash
# Set environment variable
export ROBINHOOD_AUTH_TOKEN="your-token-here"

# Test bot
python3 ~/trading_bot/bot_final_production_v38.py

# Check logs
tail -f ~/trading_bot/bot_v38.log | grep "MCP"

# Expected:
# MCP Status: ENABLED ✅
```

---

## Three Ways to Get Token

### 🟢 **Method 1: Robinhood Web (Easiest)**
```
1. Login to Robinhood
2. Settings → Connected Applications
3. Find Claude app
4. Copy token
5. Paste into script

⏱️  Time: 2 minutes
✅ Recommended
```

### 🟡 **Method 2: API Direct (Faster if available)**
```
1. Run script
2. Enter Robinhood username
3. Enter password
4. Script authenticates
5. Token auto-generated

⏱️  Time: 30 seconds
⚠️  Need Robinhood API access
```

### 🔵 **Method 3: Existing Token (Fastest)**
```
If you already have a token:
1. Run script
2. Select [3]
3. Paste your token
4. Done

⏱️  Time: 10 seconds
```

---

## Where Token Gets Saved

### Location 1: `~/.robinhood_oauth`
```bash
ROBINHOOD_AUTH_TOKEN=your-token-here

# Use with:
source ~/.robinhood_oauth
```

### Location 2: `~/trading_bot/.env`
```bash
ROBINHOOD_AUTH_TOKEN=your-token-here

# Bot auto-loads this file
# No extra setup needed
```

### Location 3: Environment Variable
```bash
export ROBINHOOD_AUTH_TOKEN="your-token-here"

# Add to ~/.bashrc or ~/.zshrc for persistent
```

---

## Using the Token

### Auto-loaded (Easiest)
```bash
# If saved to ~/trading_bot/.env, bot loads automatically
cd ~/trading_bot
python3 bot_final_production_v38.py

# Bot will find token in .env file
```

### Manual Setup
```bash
# Set in terminal
export ROBINHOOD_AUTH_TOKEN="your-token-here"

# Then run bot
python3 ~/trading_bot/bot_final_production_v38.py
```

### In Code
```python
import os

token = os.getenv('ROBINHOOD_AUTH_TOKEN')
if token:
    print("✅ Token loaded from environment")
else:
    print("❌ Token not found")
```

---

## Verify Token Works

Script will auto-test with Robinhood API:

```
[*] Testing token with Robinhood API...
✅ Token is VALID
   Logged in as: your_username
```

If it fails:
- Token may be expired → Get new one
- Token format wrong → Check Robinhood app
- API down → Try again later

---

## Token Info

### What is it?
OAuth 2.0 Bearer Token from Robinhood

### Where does it come from?
Robinhood API after OAuth authentication

### How long is it?
Usually 100-200 characters

### When does it expire?
Typically 24 hours (configurable)

### Can I reuse it?
Yes, until it expires

### How do I refresh it?
Run script again to get new token

---

## Troubleshooting

### "Connection refused"
- Robinhood API may be down
- Check internet connection
- Try again in a few minutes

### "Invalid credentials"
- Wrong username/password
- Account locked
- Try Method 1 (web) instead

### "No access token in response"
- 2FA enabled? Need to verify
- Account permissions issue
- Contact Robinhood support

### "Token verification uncertain"
- Token may still work
- MCP will validate when bot runs
- Check actual bot execution

---

## Full Deployment Flow

```
1. Run token script
   python3 get_robinhood_token.py
   
2. Choose method (1 = easiest)
   Get token from Robinhood web
   
3. Script saves token to .env
   ~/trading_bot/.env
   
4. Deploy bot
   cp bot_v38_balanced_with_mcp.py ~/trading_bot/bot_final_production_v38.py
   
5. Test bot
   python3 ~/trading_bot/bot_final_production_v38.py
   
   Expected:
   MCP Status: ENABLED ✅
   
6. Enable cron (if working)
   crontab -e
   */30 9-16 * * 1-5 /path/to/python3 /path/to/bot_final_production_v38.py
   
7. Monitor
   tail -f ~/trading_bot/bot_v38.log
```

---

## Quick Copy-Paste

### Get token:
```bash
cd ~/trading_bot
python3 get_robinhood_token.py
# Choose [1], get token from Robinhood web, paste
```

### Deploy bot:
```bash
cp bot_v38_balanced_with_mcp.py ~/trading_bot/bot_final_production_v38.py
python3 ~/trading_bot/bot_final_production_v38.py
```

### Check it works:
```bash
tail -f ~/trading_bot/bot_v38.log | grep "MCP"
# Should see: MCP Status: ENABLED ✅
```

### Enable cron:
```bash
crontab -e
# Add: */30 9-16 * * 1-5 /path/to/python3 /path/to/bot_final_production_v38.py
```

---

**Status: ✅ READY TO RUN SCRIPT**

Execute: `python3 get_robinhood_token.py`
