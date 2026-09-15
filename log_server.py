#!/usr/bin/env python3
"""
Local Log Server - Serve bot logs via HTTP (bypasses macOS sandbox)
Access at: http://localhost:8888
"""

from flask import Flask, render_template_string
from datetime import datetime
import json
import os
import threading
import time

app = Flask(__name__)

LOG_FILE = "/Users/ramayalala/trading_bot_uw/dry_run_logs/bot_20260819.log"

def read_log_file():
    """Read bot log file safely"""
    try:
        with open(LOG_FILE, 'r') as f:
            return f.read()
    except Exception as e:
        return f"Error reading log: {e}"

def parse_trades():
    """Extract trades from log"""
    trades = []
    try:
        with open(LOG_FILE, 'r') as f:
            lines = f.readlines()

        for line in lines:
            if " | BUY | " in line:
                trades.append({"type": "BUY", "line": line.strip()})
            elif " | SKIP | " in line:
                trades.append({"type": "SKIP", "line": line.strip()})

        return trades[-50:]  # Last 50 trades
    except:
        return []

@app.route('/')
def dashboard():
    """Main dashboard with real-time log data"""

    log_content = read_log_file()
    trades = parse_trades()

    # Count metrics
    buy_count = sum(1 for t in trades if t['type'] == 'BUY')
    skip_count = sum(1 for t in trades if t['type'] == 'SKIP')

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>🤖 Bot Log Server</title>
        <meta http-equiv="refresh" content="30">
        <style>
            body {
                font-family: monospace;
                margin: 20px;
                background: #0a0e27;
                color: #00ff00;
            }
            .header {
                background: #1a1f3a;
                padding: 20px;
                border-radius: 5px;
                margin-bottom: 20px;
            }
            .metrics {
                display: flex;
                gap: 20px;
                margin-bottom: 20px;
            }
            .metric {
                background: #1a1f3a;
                padding: 15px;
                border-radius: 5px;
                min-width: 150px;
            }
            .metric-label {
                font-size: 0.8em;
                color: #888;
                margin-bottom: 5px;
            }
            .metric-value {
                font-size: 2em;
                font-weight: bold;
                color: #00ff00;
            }
            .section {
                background: #1a1f3a;
                padding: 20px;
                border-radius: 5px;
                margin-bottom: 20px;
                max-height: 600px;
                overflow-y: auto;
            }
            .section-title {
                font-size: 1.2em;
                margin-bottom: 10px;
                color: #ffff00;
            }
            .buy-line {
                color: #00ff00;
                margin: 5px 0;
                font-size: 0.9em;
            }
            .skip-line {
                color: #666;
                margin: 5px 0;
                font-size: 0.9em;
            }
            .log-line {
                margin: 2px 0;
                font-size: 0.85em;
                line-height: 1.4;
            }
            .refresh-info {
                color: #888;
                font-size: 0.8em;
                margin-top: 20px;
                text-align: center;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🤖 Trading Bot Log Server</h1>
            <p>Real-time log viewer (auto-refresh every 30 sec)</p>
            <p>Updated: """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """</p>
        </div>

        <div class="metrics">
            <div class="metric">
                <div class="metric-label">Today's Trades</div>
                <div class="metric-value">""" + str(buy_count) + """</div>
            </div>
            <div class="metric">
                <div class="metric-label">Skipped</div>
                <div class="metric-value">""" + str(skip_count) + """</div>
            </div>
            <div class="metric">
                <div class="metric-label">Total Cycles</div>
                <div class="metric-value">""" + str(len(trades)) + """</div>
            </div>
        </div>

        <div class="section">
            <div class="section-title">📊 Recent Trades (Last 50)</div>
    """

    for trade in reversed(trades[-50:]):
        css_class = "buy-line" if trade['type'] == 'BUY' else "skip-line"
        html += f'<div class="{css_class}">{trade["line"]}</div>'

    html += """
        </div>

        <div class="section">
            <div class="section-title">📝 Full Log (Last 100 Lines)</div>
    """

    log_lines = log_content.split('\n')[-100:]
    for line in log_lines:
        if line.strip():
            html += f'<div class="log-line">{line}</div>'

    html += """
        </div>

        <div class="refresh-info">
            Page auto-refreshes every 30 seconds |
            <a href="/" style="color: #00ff00; text-decoration: none;">Refresh Now</a>
        </div>
    </body>
    </html>
    """

    return html

@app.route('/api/trades')
def api_trades():
    """JSON API for trades"""
    trades = parse_trades()
    return {"trades": trades, "count": len(trades), "buy_count": sum(1 for t in trades if t['type'] == 'BUY')}

@app.route('/api/log')
def api_log():
    """JSON API for raw log"""
    try:
        with open(LOG_FILE, 'r') as f:
            lines = f.readlines()
        return {
            "lines": len(lines),
            "last_50": lines[-50:],
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == '__main__':
    print("\n" + "="*80)
    print("🚀 BOT LOG SERVER STARTING")
    print("="*80)
    print(f"\n📊 Dashboard: http://localhost:8888")
    print(f"📡 API (Trades): http://localhost:8888/api/trades")
    print(f"📡 API (Log): http://localhost:8888/api/log")
    print(f"\n⏰ Auto-refresh: Every 30 seconds")
    print(f"📁 Log file: {LOG_FILE}")
    print("\nPress Ctrl+C to stop\n")
    print("="*80 + "\n")

    app.run(host='127.0.0.1', port=8888, debug=False)
