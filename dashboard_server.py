#!/usr/bin/env python3
"""Trading Bot Dashboard Enhanced - with Analytics & Block Trades"""

import json
import re
import csv
from datetime import datetime, timedelta
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

LOG_FILE = Path("/Users/ramayalala/trading_bot/bot_production.log")
BLOCK_CSV = Path("/Users/ramayalala/trading_bot/block_trades.csv")
PORT = 8888


def get_next_cycle_time():
    """Calculate CORRECT next cycle time based on current CDT time"""
    now_utc = datetime.utcnow()
    cdt_offset = timedelta(hours=-5)
    now_cdt = now_utc + cdt_offset
    
    cron_times = [
        (9, 0), (9, 30), (10, 0), (10, 30), (11, 0), (11, 30), (12, 0),
        (12, 30), (13, 0), (13, 30), (14, 0), (14, 30), (15, 0), (15, 30)
    ]
    
    weekday = now_cdt.weekday()
    hour = now_cdt.hour
    minute = now_cdt.minute
    
    if weekday >= 5:
        return f"09:00 (Mon)"
    
    for h, m in cron_times:
        if h > hour or (h == hour and m > minute):
            return f"{h:02d}:{m:02d}"
    
    return "09:00 (tomorrow)"


class DashboardHandler(SimpleHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/":
            self.serve_dashboard()
        elif self.path == "/api/stats":
            self.send_json_response(self.get_stats())
        elif self.path == "/api/status":
            self.send_json_response(self.get_status())
        elif self.path == "/api/cycles":
            self.send_json_response(self.get_cycles())
        elif self.path == "/api/analytics":
            self.send_json_response(self.get_analytics())
        elif self.path == "/api/block_trades":
            self.send_json_response(self.get_block_trades())
        else:
            self.send_error(404)

    def serve_dashboard(self):
        html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Bot Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            color: #e2e8f0;
            padding: 20px;
        }
        .container { max-width: 1800px; margin: 0 auto; }
        header { text-align: center; margin-bottom: 30px; padding-bottom: 20px; border-bottom: 2px solid #475569; }
        h1 { font-size: 2.5em; margin-bottom: 15px; background: linear-gradient(135deg, #60a5fa, #3b82f6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .status-bar { display: flex; justify-content: center; gap: 20px; flex-wrap: wrap; }
        .status-item { display: flex; align-items: center; gap: 8px; padding: 10px 16px; background: #1e293b; border-radius: 8px; border: 1px solid #334155; }
        .badge { padding: 6px 12px; border-radius: 20px; font-weight: bold; }
        .badge-open { background: #10b981; color: white; }
        .badge-closed { background: #ef4444; color: white; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; }
        .card h2 { font-size: 1.2em; margin-bottom: 15px; color: #60a5fa; border-bottom: 1px solid #334155; padding-bottom: 10px; }
        .stat-row { display: flex; justify-content: space-between; padding: 10px; margin: 8px 0; background: #0f172a; border-radius: 6px; }
        .stat-label { color: #94a3b8; }
        .stat-value { font-weight: bold; color: #60a5fa; }
        .block-table { width: 100%; border-collapse: collapse; font-size: 0.9em; margin-top: 15px; }
        .block-table th, .block-table td { padding: 8px; text-align: left; border-bottom: 1px solid #334155; }
        .block-table th { background: #0f172a; color: #60a5fa; font-weight: bold; }
        .block-table tr:hover { background: #0f172a; }
        .footer { text-align: center; color: #94a3b8; margin-top: 30px; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🤖 Trading Bot Dashboard</h1>
            <div class="status-bar">
                <div class="status-item"><span>Market:</span><span id="market-status" class="badge">--</span></div>
                <div class="status-item"><span>Time (CDT):</span><span id="current-time" style="font-weight:bold;color:#60a5fa">--:--:--</span></div>
            </div>
        </header>

        <div class="grid">
            <div class="card">
                <h2>📊 Bot Stats</h2>
                <div id="stats-container">Loading...</div>
            </div>
            <div class="card">
                <h2>📈 Analytics</h2>
                <div id="analytics-container">Loading...</div>
            </div>
            <div class="card">
                <h2>⚙️ System Status</h2>
                <div id="status-container">Loading...</div>
            </div>
        </div>

        <div class="card">
            <h2>🚨 Block Trades (Real-time Institutional Flows)</h2>
            <div id="block-trades-container">Loading...</div>
        </div>

        <div class="footer">Auto-refreshing | Updated: <span id="last-updated">--</span></div>
    </div>

    <script>
        function formatTime() {
            const now = new Date();
            const cdt = new Date(now.toLocaleString('en-US', { timeZone: 'America/Chicago' }));
            const h = String(cdt.getHours()).padStart(2, '0');
            const m = String(cdt.getMinutes()).padStart(2, '0');
            const s = String(cdt.getSeconds()).padStart(2, '0');
            return h + ':' + m + ':' + s;
        }

        function isMarketOpen() {
            const now = new Date();
            const cdt = new Date(now.toLocaleString('en-US', { timeZone: 'America/Chicago' }));
            const h = cdt.getHours();
            const m = cdt.getMinutes();
            const d = cdt.getDay();
            return (d >= 1 && d <= 5) && (h >= 9 && h <= 15);
        }

        function updateTime() {
            document.getElementById('current-time').textContent = formatTime();
            const b = document.getElementById('market-status');
            if (isMarketOpen()) {
                b.textContent = '🟢 OPEN';
                b.className = 'badge badge-open';
            } else {
                b.textContent = '🔴 CLOSED';
                b.className = 'badge badge-closed';
            }
        }

        async function updateAll() {
            try {
                const [stats, analytics, status, blockTrades] = await Promise.all([
                    fetch('/api/stats').then(r => r.json()),
                    fetch('/api/analytics').then(r => r.json()),
                    fetch('/api/status').then(r => r.json()),
                    fetch('/api/block_trades').then(r => r.json())
                ]);

                document.getElementById('stats-container').innerHTML = `
                    <div class="stat-row"><span>Cycles:</span><span class="stat-value">${stats.cycles}</span></div>
                    <div class="stat-row"><span>Signals:</span><span class="stat-value">${stats.signals}</span></div>
                    <div class="stat-row"><span>Analyzed:</span><span class="stat-value">${stats.analyzed}</span></div>
                    <div class="stat-row"><span>Skipped:</span><span class="stat-value">${stats.skipped}</span></div>
                `;

                document.getElementById('analytics-container').innerHTML = `
                    <div class="stat-row"><span>Stocks Checked:</span><span class="stat-value">${analytics.stocks_checked}</span></div>
                    <div class="stat-row"><span>Entries Placed:</span><span class="stat-value">${analytics.entries}</span></div>
                    <div class="stat-row"><span>Exits Executed:</span><span class="stat-value">${analytics.exits}</span></div>
                    <div class="stat-row"><span>Block Trades:</span><span class="stat-value">${analytics.block_trades}</span></div>
                `;

                document.getElementById('status-container').innerHTML = `
                    <div class="stat-row"><span>Bot:</span><span class="stat-value">${status.bot_running ? '✅' : '⏸️'}</span></div>
                    <div class="stat-row"><span>Log Size:</span><span class="stat-value">${status.log_size}</span></div>
                `;

                let blockHtml = '';
                if (blockTrades.trades && blockTrades.trades.length > 0) {
                    blockHtml = '<table class="block-table"><thead><tr><th>Timestamp</th><th>Symbol</th><th>Price</th><th>Size</th><th>Value</th></tr></thead><tbody>';
                    blockTrades.trades.forEach(trade => {
                        blockHtml += `<tr><td>${trade.timestamp}</td><td><strong>${trade.symbol}</strong></td><td>$${parseFloat(trade.price).toFixed(2)}</td><td>${parseInt(trade.size).toLocaleString()}</td><td>$${parseFloat(trade.notional_value).toLocaleString('en-US', {maximumFractionDigits: 0})}</td></tr>`;
                    });
                    blockHtml += '</tbody></table>';
                } else {
                    blockHtml = '<div style="color:#94a3b8;padding:10px;">No block trades detected yet</div>';
                }
                document.getElementById('block-trades-container').innerHTML = blockHtml;

                document.getElementById('last-updated').textContent = new Date().toLocaleTimeString();

            } catch (e) { console.error(e); }
        }

        updateTime();
        updateAll();
        setInterval(updateTime, 1000);
        setInterval(updateAll, 2000);
    </script>
</body>
</html>"""

        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(html.encode())

    def send_json_response(self, data):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def get_stats(self):
        if not LOG_FILE.exists():
            return {"cycles": 0, "signals": 0, "analyzed": 0, "skipped": 0}
        content = LOG_FILE.read_text()
        return {
            "cycles": content.count("CYCLE"),
            "signals": content.count("SIGNAL:"),
            "analyzed": content.count("✅ ["),
            "skipped": content.count("possibly delisted") + content.count("Error analyzing")
        }

    def get_analytics(self):
        """Get analytics from logs"""
        if not LOG_FILE.exists():
            return {"stocks_checked": 0, "entries": 0, "exits": 0, "block_trades": 0}
        
        content = LOG_FILE.read_text()
        
        # Count stocks checked
        stocks = set(re.findall(r'\[(\w{1,5})\]', content))
        stocks = {s for s in stocks if s not in ["MCP", "UTC", "EST", "CDT"]}
        
        # Count entries
        entries = content.count("Order placed")
        
        # Count exits
        exits = content.count("Exit order executed")
        
        # Count block trades
        block_trades = 0
        if BLOCK_CSV.exists():
            try:
                with open(BLOCK_CSV) as f:
                    block_trades = sum(1 for line in f) - 1
            except:
                pass
        
        return {
            "stocks_checked": len(stocks),
            "entries": entries,
            "exits": exits,
            "block_trades": block_trades
        }

    def get_status(self):
        size = "0B"
        if LOG_FILE.exists():
            size = f"{LOG_FILE.stat().st_size / 1024:.1f}KB"
        return {
            "bot_running": subprocess.run(["pgrep", "-f", "bot_production_final.py"], capture_output=True).returncode == 0,
            "log_file": "bot_production.log",
            "log_size": size
        }

    def get_block_trades(self):
        """Get latest block trades"""
        trades = []
        if BLOCK_CSV.exists():
            try:
                with open(BLOCK_CSV) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        trades.append(row)
                    trades = trades[-10:]  # Last 10
            except:
                pass
        return {"trades": trades, "total": len(trades)}

    def log_message(self, *args, **kwargs):
        pass


if __name__ == "__main__":
    import subprocess
    server = HTTPServer(('', PORT), DashboardHandler)
    print(f"✅ Enhanced Dashboard at http://localhost:{PORT}")
    print("   Analytics + Block Trades + Bot Status\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✅ Stopped")
        server.shutdown()
