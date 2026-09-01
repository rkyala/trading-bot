#!/opt/homebrew/bin/python3.10
"""
Cron-safe alert wrapper - avoids shell path escaping issues
"""
import sys
import os
import subprocess

# Change to alerts directory
alerts_dir = "/Users/ramayalala/Documents/Documents - Rama's MacBook Pro/day_trading_alerts"
os.chdir(alerts_dir)

# Run alert script
result = subprocess.run([
    sys.executable,
    "alerts_consolidated.py"
], capture_output=False)

sys.exit(result.returncode)
