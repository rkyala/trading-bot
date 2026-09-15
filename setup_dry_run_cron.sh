#!/bin/bash

# Setup dry-run cron job
# Runs bot_dry_run.py every 30 minutes during market hours

BOT_DIR="/Users/ramayalala/trading_bot_uw"
SCRIPT="bot_dry_run.py"

echo ""
echo "=================================="
echo "  DRY-RUN CRON SETUP"
echo "=================================="
echo ""

# Detect timezone
echo "Current timezone:"
date +"%Z"
echo ""

echo "Cron will run bot_dry_run.py every 30 minutes:"
echo "  Time: 9:30 AM - 4:30 PM ET (Mon-Fri)"
echo "  UTC:  14:00 - 21:30"
echo ""

# Create cron entry
CRON_JOB="*/30 14-21 * * 1-5 cd '$BOT_DIR' && python3 $SCRIPT >> dry_run_logs/cron.log 2>&1"

echo "Adding to crontab..."
echo ""

# Get current crontab
CURRENT_CRON=$(crontab -l 2>/dev/null || echo "")

# Check if already exists
if echo "$CURRENT_CRON" | grep -q "bot_dry_run.py"; then
    echo "⚠️  Cron job already exists!"
    echo ""
    echo "Current cron entry:"
    crontab -l | grep "bot_dry_run.py"
    echo ""
    read -p "Remove and recreate? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Remove old entry
        crontab -l | grep -v "bot_dry_run.py" | crontab -
        echo "Removed old entry"
    else
        echo "Keeping existing entry"
        exit 0
    fi
fi

# Add new entry
{
    crontab -l 2>/dev/null || echo ""
    echo "$CRON_JOB"
} | crontab -

echo "✅ Cron job installed!"
echo ""

# Verify
echo "Verifying installation..."
crontab -l | grep "bot_dry_run.py"

echo ""
echo "=================================="
echo "  SETUP COMPLETE"
echo "=================================="
echo ""
echo "Next steps:"
echo "1. The cron job will start at next 9:30 AM ET"
echo "2. Check logs: tail -f dry_run_logs/cron.log"
echo "3. View dashboard: python3 dry_run_dashboard.py"
echo "4. After 5 days, decide: Go live or keep testing?"
echo ""
