# Get Robinhood Token Manually (5 minutes)

Since OAuth is blocking programmatic login, get the token directly from Robinhood Web:

## Step 1: Open Robinhood in Browser

Go to: https://robinhood.com (or https://web.robinhood.com)

Log in with your email/password

## Step 2: Open Browser Developer Tools

Press: `Cmd + Option + I` (Mac) or `Ctrl + Shift + I` (Windows)

Go to: **Network** tab

## Step 3: Refresh Page

Press `Cmd + R` to reload the page

Watch the Network tab for requests to `api.robinhood.com`

## Step 4: Find the Authorization Header

Look for any request to `api.robinhood.com` 

Click on it → scroll to **Request Headers**

Find the line: `Authorization: Bearer eyJ...`

Copy the entire token value (everything after "Bearer ")

Example:
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0...
```

## Step 5: Save Token

Create a file `token_manual.txt`:

```bash
cat > ~/trading_bot/token_manual.txt << 'EOF'
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0...
EOF
```

Replace the long string with YOUR token from the browser.

## Step 6: Create .env.mcp

```bash
cat > ~/trading_bot/.env.mcp << 'EOF'
ROBINHOOD_CLIENT_ID=c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS
ROBINHOOD_ACCESS_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0...
EOF
```

Paste YOUR token in place of the example.

## Step 7: Test It

```bash
python3 test_mcp_auth.py
```

Should show:
```
✅ User profile API call successful
✅ Account API call successful
✅ ALL MCP AUTHENTICATION TESTS PASSED!
```

---

## Why This Works

Robinhood Web already has a valid access token in memory. We're just copying it from the browser instead of going through the broken OAuth flow.

The token lasts 24 hours. After that, use:
```bash
python3 auto_refresh_token.py
```

But we need a refresh_token for that. If you get stuck there, we'll extract it from the browser too.
