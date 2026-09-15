#!/usr/bin/env python3
"""
Cron-safe bot runner - Direct Python entry point
Calls v3.8 PRODUCTION bot for Aug 26 go-live
"""
import subprocess
import os
import sys

os.chdir('/Users/ramayalala/trading_bot_uw')
result = subprocess.run([sys.executable, 'bot_final_production.py'], capture_output=False)
sys.exit(result.returncode)
