#!/bin/bash

# Manual test of bot_dry_run.py
# Run this on your Mac Terminal

BOT_DIR="/Users/ramayalala/trading_bot_uw"

echo ""
echo "=================================="
echo "  DRY-RUN BOT TEST"
echo "=================================="
echo ""

cd "$BOT_DIR"

echo "Running bot_dry_run.py..."
echo ""

python3 bot_dry_run.py

echo ""
echo "=================================="
echo "  TEST COMPLETE"
echo "=================================="
echo ""

echo "View results:"
echo "  python3 dry_run_dashboard.py"
echo ""
