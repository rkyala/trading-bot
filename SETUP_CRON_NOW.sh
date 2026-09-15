#!/bin/bash

# Run this on your Mac Terminal to set up dry-run cron job

BOT_DIR="/Users/ramayalala/trading_bot_uw"

echo ""
echo "=================================="
echo "  SETTING UP DRY-RUN CRON JOB"
echo "=================================="
echo ""

# Add dry-run cron job
(crontab -l 2>/dev/null | grep -v "bot_dry_run"; echo "*/30 14-21 * * 1-5 cd '$BOT_DIR' && python3 bot_dry_run.py >> dry_run_logs/cron.log 2>&1") | crontab -

echo "✅ Dry-run cron job installed!"
echo ""
echo "Schedule:"
echo "  Every 30 minutes"
echo "  9:30 AM - 4:30 PM ET"
echo "  Monday - Friday"
echo ""
echo "Verification:"
crontab -l | grep "bot_dry_run"
echo ""
echo "=================================="
echo "  READY FOR TOMORROW!"
echo "=================================="
echo ""
