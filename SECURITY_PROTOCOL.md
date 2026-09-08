# Security Protocol - CRITICAL

**Status:** 🔒 LOCKED & ENFORCED

---

## Core Rule: NEVER Send Credentials to Discord

### ✅ DO NOT EVER:
- ❌ Send API keys in alert messages
- ❌ Include tokens in Discord embeds
- ❌ Log full responses (may contain secrets)
- ❌ Print authorization headers
- ❌ Commit .env.local to git
- ❌ Hardcode credentials in code

### ✅ ALWAYS:
- ✅ Store secrets in `.env.local` (gitignored)
- ✅ Read from environment variables only
- ✅ Use `os.getenv()` with empty default
- ✅ Sanitize any logged data
- ✅ Review code before commit

---

## Credential Storage

### Current Setup (Correct)
```python
# ✅ SAFE - Reads from environment
UW_API_KEY = os.getenv("UW_API_KEY", "")
RH_CLIENT_ID = os.getenv("RH_CLIENT_ID", "")
RH_REFRESH_TOKEN = os.getenv("RH_REFRESH_TOKEN", "")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "")
```

### File Locations

| File | Contains | Git Status | Protection |
|------|----------|-----------|-----------|
| `.env.local` | All credentials | ❌ Ignored | Primary |
| `start_uw_bot.sh` | Export paths only | ✅ Tracked | Secondary |
| `uw_bot.py` | `os.getenv()` only | ✅ Tracked | Code layer |
| `uw_*alerts.py` | `os.getenv()` only | ✅ Tracked | Code layer |

### Access Pattern
```
.env.local (source)
    ↓ (source .env.local)
Environment variables
    ↓ (os.getenv)
Python code (safe to read)
    ↓ (use directly, never print)
Discord payloads (metadata only)
```

---

## Discord Alert Content - Allowed Only:

### ✅ Safe to Send
- Stock tickers (NVDA, SPY, etc.)
- Price levels ($768.50, $772.00)
- Trading signals (BUY, SELL)
- Win/loss rates (55%, 75%)
- P&L amounts ($+127.50)
- Order counts (3 executed, 2 pending)
- Position sizes ($50, $150)
- Timestamps (2026-09-08 14:30:00)
- Status messages (SUCCESS, FAILED)

### ❌ NEVER Send to Discord
- API keys (UW, Robinhood, etc.)
- Access tokens (Bearer ...)
- Refresh tokens (OAuth tokens)
- Authentication headers
- Full HTTP responses
- Database credentials
- OAuth tokens or codes
- Webhook URLs (in messages)
- Password/PIN data

---

## Code Review Checklist

Before any commit:

```bash
# 1. Check for hardcoded secrets
grep -r "api_key\|token\|secret" . --include="*.py" | grep -v ".env\|os.getenv" 

# 2. Check for OAuth tokens
grep -r "Bearer \|refresh_token\|access_token" . --include="*.py" | grep -v "os.getenv\|import"

# 3. Verify .env.local is gitignored
grep "\.env\.local" .gitignore

# 4. Check Discord payload
grep -A 10 "payload\|embeds\|description" uw_*alerts.py | head -20
```

---

## Alert Testing (Safe Way)

### ✅ Test with dummy data:
```python
# Safe test
embed = {
    "title": "Test Alert",
    "description": "Ticker: NVDA, Price: $130.00",  # OK - public info
    "color": 0x3498db
}
```

### ❌ Never test with:
```python
# UNSAFE
embed = {
    "description": f"API Key: {UW_API_KEY}",  # NEVER!
    "webhook": DISCORD_WEBHOOK,  # NEVER!
    "token": os.getenv("RH_REFRESH_TOKEN")  # NEVER!
}
```

---

## Rotation & Revocation

If any credential is ever exposed:

1. **Immediately** rotate the credential (get new token/key)
2. **Delete** the old credential from Discord/logs/history
3. **Update** .env.local with new value
4. **Commit** .gitignore change (if new file)
5. **Audit** git history for leaks
6. **Test** bot still works

Current credentials status:
- UW API Key: ✅ Safe (stored in .env.local)
- RH OAuth: ✅ Safe (stored in .env.local)
- Discord Webhook: ✅ Safe (stored in .env.local)

---

## Monitoring

### Automated Checks (Pre-Commit)
```bash
# Prevent accidental commits
echo 'grep -r "Bearer\|api_key\|refresh_token" . --include="*.py" && exit 1 || exit 0' > .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

### Manual Audits
Run weekly:
```bash
git log --all -S "api_key\|Bearer\|refresh" --oneline
```

Expected: No results (all credentials in .env.local only)

---

## Incident Response

If credentials are ever leaked to Discord:

**Immediate (5 min):**
1. Stop the bot
2. Delete Discord message/channel
3. Revoke the credential in source system

**Short term (30 min):**
1. Generate new credential
2. Update .env.local
3. Test bot with new credential
4. Restart bot

**Long term (same day):**
1. Audit all logs for leaks
2. Review git history
3. Document incident
4. Brief on what happened

---

## Final Verification

✅ **CONFIRMED SAFE:**
- No API keys in Discord payloads
- No tokens in alert embeds
- No credentials in git commits
- All secrets in .env.local (ignored)
- Code only reads from environment

✅ **DEPLOYMENT READY:**
- Monday 9/8 alerts are secure
- New Discord webhook is protected
- .env.local prevents future leaks
- Security protocol locked in

---

**Last Updated:** Sep 7, 2026  
**Status:** 🔒 LOCKED - Critical security rule enforced
