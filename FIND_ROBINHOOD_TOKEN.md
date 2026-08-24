# How to Find Your Robinhood OAuth Token

## Method 1: Web Settings (Most Common)

### Path A: Direct URL
Go directly to:
```
https://robinhood.com/settings/connected-apps
```
or
```
https://robinhood.com/settings/integrations
```

---

## Method 2: From Robinhood App

### iOS App:
1. Open Robinhood app
2. Tap **Menu** (☰)
3. Tap **Settings**
4. Tap **Account**
5. Look for:
   - **Connected Apps**
   - **Integrations**
   - **Developer**
   - **API Keys**

### Android App:
1. Open Robinhood app
2. Tap **More** (⋯)
3. Tap **Settings**
4. Tap **Account Settings**
5. Look for:
   - **Connected Applications**
   - **Integrations**
   - **API Access**

---

## Method 3: Browser Developer Tools

1. **Open Robinhood.com** in browser
2. Press **F12** (Developer Tools)
3. Go to **Application** tab
4. Look in **Local Storage** for:
   - `robinhood_token`
   - `access_token`
   - `oauth_token`

---

## Method 4: Check if Token Already Exists

### On Your Mac:
```bash
# Check if token is already saved
cat ~/.robinhood_oauth
cat ~/trading_bot/.env
env | grep ROBINHOOD
```

If any of these show a token, use that!

---

## Method 5: Generate New Token via API

Run this on your Mac:
```bash
cd ~/trading_bot
source venv/bin/activate
python3 get_token.py
```

Then choose **[2] Robinhood API authentication**

Enter:
- Robinhood username
- Robinhood password
- Script will authenticate and get token automatically

---

## Method 6: Alternative - Use Robinhood CLI

```bash
pip install robinhood-cli

robinhood login
robinhood get-token
```

---

## If You Can't Find It:

### Option A: Create a New Connected App
1. Go to https://robinhood.com/settings
2. Look for **+ Add New Integration**
3. Select **Claude Trading Bot** or create custom
4. Authorize access
5. Copy generated token

### Option B: Contact Robinhood Support
1. Go to https://robinhood.com/support
2. Chat with support
3. Ask for "OAuth token for trading API"

### Option C: Use Browser's Network Inspector
1. Open https://robinhood.com/settings
2. Open Developer Tools (F12)
3. Go to **Network** tab
4. Look for API calls containing `token` or `oauth`
5. Find the bearer token in response

---

## What the Token Looks Like

It's usually one of these formats:

```
Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

or

eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

or

robinhood_access_token_1234567890abcdef...
```

**Length:** 100-300+ characters

---

## Fastest Solution: Use API Method

```bash
# Run this on your Mac
cd ~/trading_bot
source venv/bin/activate
python3 get_token.py

# Choose [2]
# Enter Robinhood username
# Enter Robinhood password
# Script generates token automatically
```

This bypasses the need to find it manually!

---

## Still Stuck?

Try running:
```bash
python3 get_token.py
```

Then select **[2] Robinhood API authentication** - let the script handle it.
