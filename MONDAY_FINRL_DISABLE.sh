#!/bin/bash
# IMMEDIATE FIX FOR MONDAY 9/1
# Disables broken FinRL to unblock BB+Fibonacci strategy
# Run this BEFORE deploying to Railway

echo "🔧 Disabling FinRL for Monday launch..."

# Create backup
cp bot.py bot.py.backup.$(date +%s)
echo "✅ Backup created: bot.py.backup.*"

# Add explicit disable after FinRL import block (line 54-61)
# This ensures finrl_enabled = False regardless of import success

# Use sed to add a line after the except block
sed -i.bak '61a\
# MONDAY HOTFIX: Disable broken FinRL until proper Gymnasium model is ready\
finrl_enabled = False  # Force disable to unblock BB+Fibonacci strategy' bot.py

echo "✅ FinRL disabled in bot.py"
echo ""
echo "📋 Changes made:"
echo "  - Added: finrl_enabled = False after FinRL import block"
echo "  - Result: Bot will use rules-based BB+Fibonacci strategy"
echo "  - Backup: bot.py.backup.* (in case of issues)"
echo ""
echo "🚀 Ready for Monday deployment!"
echo ""
echo "To verify the change:"
grep -n "finrl_enabled = False" bot.py
