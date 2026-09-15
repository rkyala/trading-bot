#!/bin/bash
# Wrapper script for cron - ensures full environment is loaded

# Source shell profile to get full environment
if [ -f ~/.zprofile ]; then
  source ~/.zprofile
fi
if [ -f ~/.bash_profile ]; then
  source ~/.bash_profile
fi

# Set explicit PATH to include Homebrew and Python
export PATH="/usr/local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"

# Change to bot directory
cd "/Users/ramayalala/trading_bot_uw" || exit 1

# Log execution
echo "Bot started at $(date)" >> dry_run_logs/cron.log

# Run the bot
python3 bot_dry_run.py >> dry_run_logs/cron.log 2>&1

# Log completion
echo "Bot finished at $(date)" >> dry_run_logs/cron.log
