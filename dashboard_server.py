#!/usr/bin/env python3
"""Trading Bot Dashboard - Last & Next Cycle + Analytics + Block Trades"""

import json
import re
import csv
from datetime import datetime, timedelta
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import subprocess

LOG_FILE = Path("/Users/ramayalala/trading_bot/bot_production.log")
BLOCK_CSV = Path("/Users/ramayalala/trading_bot/block_trades.csv")
PORT = 8888


def get_next_cycle_time():
    """Calculate CORRECT next cycle time based on current CDT time"""
    now_utc = datetime.utcnow()
    cdt_offset = timedelta(hours=-5)  # CDT = UTC-5
    now_cdt = now_utc + cdt_offset
    
    # Cron schedule times (CDT)
    cron_times = [
        (9, 30), (10, 0), (10, 30), (11, 0), (11, 30), (12, 0),
        (12, 30), (13, 0), (13, 30), (14, 0), (14, 30), (15, 0),
        (15, 30), (16, 0)  # 4:00 PM CDT
    ]
    
    weekday = now_cdt.weekday()
    hour = now_cdt.hour
    minute = now_cdt.minute
    
    # Check if it's a weekday
    if weekday >= 5:  # Weekend (5=Sat, 6=Sun)
        # Find next Monday
        days_until_monday = 0 - weekday
        if days_until_monday <= 0:
            days_until_monday += 7
        next_date = now_cdt + timedelta(days=days_until_monday)
        return f"09:30 (Mon)"
    
    # It's a weekday - find next cron time
    for h, m in cron_times:
        if h > hour or (h == hour and m > minute):
            return f"{h:02d}:{m:02d}"
    
    # All cycles passed for today - next is tomorrow 9:30 AM
    return "09:30 (tomorrow)"


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
    <title>Trading Bot</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            color: #e2e8f0;
            padding: 20px;
        }
        .container { max-width: 1600px; margin: 0 auto; }
        header { text-align: center; margin-bottom: 30px; padding-bottom: 20px; border-bottom: 2px solid #475569; }
        h1 { font-size: 2.5em; margin-bottom: 15px; background: linear-gradient(135deg, #60a5fa, #3b82f6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .status-bar { display: flex; justify-content: center; gap: 20px; flex-wrap: wrap; }
        .status-item { display: flex; align-items: center; gap: 8px; padding: 10px 16px; background: #1e293b; border-radius: 8px; border: 1px solid #334155; }
        .badge { padding: 6px 12px; border-radius: 20px; font-weight: bold; }
        .badge-open { background: #10b981; color: white; }
        .badge-closed { background: #ef4444; color: white; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; }
        .card h2 { font-size: 1.2em; margin-bottom: 15px; color: #60a5fa; border-bottom: 1px solid #334155; padding-bottom: 10px; }
        .stat-row { display: flex; justify-content: space-between; padding: 10px; margin: 8px 0; background: #0f172a; border-radius: 6px; }
        .stat-label { color: #94a3b8; }
        .stat-value { font-weight: bold; color: #60a5fa; }
        .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 30px; }
        .cycle-card { background: #1e293b; border: 2px solid #334155; border-radius: 12px; padding: 20px; }
        .cycle-card.active { border-color: #10b981; }
        .cycle-card.next { border-color: #60a5fa; }
        .cycle-title { font-size: 1.3em; font-weight: bold; margin-bottom: 15px; color: #60a5fa; }
        .cycle-time { font-size: 1.2em; color: #10b981; margin-bottom: 15px; font-weight: bold; }
        .cycle-time.next { color: #60a5fa; }
        .symbol-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(70px, 1fr)); gap: 6px; margin-top: 10px; }
        .symbol-tag { padding: 6px; border-radius: 4px; font-size: 0.8em; text-align: center; font-weight: bold; }
        .analyzed { background: #10b981; color: white; }
        .skipped { background: #ef4444; color: white; }
        .signal { background: #fbbf24; color: #000; }
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
                <h2>📊 Stats</h2>
                <div id="stats-container">Loading...</div>
            </div>
            <div class="card">
                <h2>⚙️ Status</h2>
                <div id="status-container">Loading...</div>
            </div>
            <div class="card">
                <h2>📅 Schedule</h2>
                <div id="schedule-container">Loading...</div>
            </div>
        </div>

        <div class="two-col">
            <div class="cycle-card active">
                <div class="cycle-title">📊 LAST CYCLE (COMPLETED)</div>
                <div id="last-cycle-time" class="cycle-time">--:--:--</div>
                <div id="last-cycle-container">Loading...</div>
            </div>
            <div class="cycle-card next">
                <div class="cycle-title">⏭️ NEXT CYCLE (SCHEDULED)</div>
                <div id="next-cycle-time" class="cycle-time next">--:--</div>
                <div id="next-cycle-container">Loading...</div>
            </div>
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
            return (d >= 1 && d <= 5) && (h > 9 && h < 16 || (h === 9 && m >= 30));
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
                const [stats, status, cycles] = await Promise.all([
                    fetch('/api/stats').then(r => r.json()),
                    fetch('/api/status').then(r => r.json()),
                    fetch('/api/cycles').then(r => r.json())
                ]);

                document.getElementById('stats-container').innerHTML = `
                    <div class="stat-row"><span>Cycles:</span><span class="stat-value">${stats.cycles}</span></div>
                    <div class="stat-row"><span>Signals:</span><span class="stat-value">${stats.signals}</span></div>
                    <div class="stat-row"><span>Analyzed:</span><span class="stat-value">${stats.analyzed}</span></div>
                    <div class="stat-row"><span>Skipped:</span><span class="stat-value">${stats.skipped}</span></div>
                `;

                document.getElementById('status-container').innerHTML = `
                    <div class="stat-row"><span>MCP:</span><span class="stat-value">${status.mcp_running ? '✅' : '⏸️'}</span></div>
                    <div class="stat-row"><span>Bot:</span><span class="stat-value">${status.bot_running ? '✅' : '⏸️'}</span></div>
                    <div class="stat-row"><span>Log:</span><span class="stat-value">${status.log_size}</span></div>
                `;

                document.getElementById('schedule-container').innerHTML = `
                    <div class="stat-row"><span>Frequency:</span><span class="stat-value">30 min</span></div>
                    <div class="stat-row"><span>Hours:</span><span class="stat-value">9:30 - 4 PM</span></div>
                    <div class="stat-row"><span>Days:</span><span class="stat-value">Mon-Fri</span></div>
                `;

                document.getElementById('last-cycle-time').textContent = cycles.last_cycle_time || 'Never';
                let lastHtml = '';
                if (cycles.last_cycle_data) {
                    const d = cycles.last_cycle_data;
                    if (d.analyzed && d.analyzed.length > 0) {
                        lastHtml += '<div style="margin-bottom:15px;"><strong>✅ Analyzed (' + d.analyzed.length + '):</strong><div class="symbol-list">';
                        d.analyzed.slice(0, 20).forEach(s => lastHtml += '<div class="symbol-tag analyzed">' + s + '</div>');
                        if (d.analyzed.length > 20) lastHtml += '<div style="text-align:center;color:#94a3b8;">+' + (d.analyzed.length - 20) + '</div>';
                        lastHtml += '</div></div>';
                    }
                    if (d.skipped && d.skipped.length > 0) {
                        lastHtml += '<div><strong>⏭️ Skipped (' + d.skipped.length + '):</strong><div class="symbol-list">';
                        d.skipped.forEach(s => lastHtml += '<div class="symbol-tag skipped">' + s + '</div>');
                        lastHtml += '</div></div>';
                    }
                    if (d.signals && d.signals.length > 0) {
                        lastHtml += '<div style="margin-top:15px;"><strong>🎯 Signals (' + d.signals.length + '):</strong><div class="symbol-list">';
                        d.signals.forEach(s => lastHtml += '<div class="symbol-tag signal">' + s + '</div>');
                        lastHtml += '</div></div>';
                    } else {
                        lastHtml += '<div style="color:#94a3b8;padding:10px;background:#0f172a;border-radius:6px;">No signals (market not ideal)</div>';
                    }
                } else {
                    lastHtml = '<div style="color:#94a3b8;">Waiting for first cycle...</div>';
                }
                document.getElementById('last-cycle-container').innerHTML = lastHtml;

                document.getElementById('next-cycle-time').textContent = cycles.next_cycle_time || '--:--';
                let nextHtml = '<div style="color:#94a3b8;line-height:1.8;font-size:0.9em;">';
                nextHtml += '⏳ Queued for execution...<br><br>';
                nextHtml += '<strong>Process:</strong><br>';
                nextHtml += '1. Fetch 50 trending<br>';
                nextHtml += '2. Filter $10B+ cap<br>';
                nextHtml += '3. ADX + Stochastic<br>';
                nextHtml += '4. Fibonacci check<br>';
                nextHtml += '5. Log results<br>';
                nextHtml += '</div>';
                document.getElementById('next-cycle-container').innerHTML = nextHtml;

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

    def get_status(self):
        mcp = subprocess.run(["pgrep", "-f", "robinhood_mcp_local.py"], capture_output=True).returncode == 0
        bot = subprocess.run(["pgrep", "-f", "bot_production_final.py"], capture_output=True).returncode == 0
        if LOG_FILE.exists():
            size = f"{LOG_FILE.stat().st_size / 1024:.1f}KB"
        else:
            size = "0B"
        return {"mcp_running": mcp, "bot_running": bot, "log_file": "bot_production.log", "log_size": size}

    def get_cycles(self):
        last_time = ""
        analyzed, skipped, signals = [], [], []
        
        if LOG_FILE.exists():
            content = LOG_FILE.read_text()
            lines = content.split('\n')
            
            for i in range(len(lines)-1, -1, -1):
                if 'CYCLE |' in lines[i]:
                    try:
                        last_time = lines[i].split('|')[1].strip()
                    except:
                        pass
                    break
            
            for line in lines:
                m = re.search(r'✅ \[.*?\] (\w+)', line)
                if m and m.group(1) not in analyzed:
                    analyzed.append(m.group(1))
                m = re.search(r'SIGNAL: (\w+)', line)
                if m and m.group(1) not in signals:
                    signals.append(m.group(1))
            
            for line in lines:
                if 'possibly delisted' in line or 'Error analyzing' in line:
                    m = re.search(r'\$(\w+):', line)
                    if m and m.group(1) not in skipped and m.group(1) not in analyzed:
                        skipped.append(m.group(1))
        
        next_time = get_next_cycle_time()
        
        return {
            "last_cycle_time": last_time,
            "last_cycle_data": {
                "analyzed": analyzed[:50],
                "skipped": skipped[:50],
                "signals": signals[:10]
            },
            "next_cycle_time": next_time
        }

    def get_analytics(self):
        """Get analytics data"""
        if not LOG_FILE.exists():
            return {"stocks_checked": 0, "entries": 0, "exits": 0, "block_trades": 0}

        content = LOG_FILE.read_text()
        stocks = set(re.findall(r'\[(\w{1,5})\]', content))
        stocks = {s for s in stocks if s not in ["MCP", "UTC", "EST", "CDT"]}
        entries = content.count("Order placed")
        exits = content.count("Exit order executed")

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

    def get_block_trades(self):
        """Get latest block trades"""
        trades = []
        if BLOCK_CSV.exists():
            try:
                with open(BLOCK_CSV) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        trades.append(row)
                    trades = trades[-10:]
            except:
                pass
        return {"trades": trades, "total": len(trades)}

    def log_message(self, *args, **kwargs):
        pass


if __name__ == "__main__":
    server = HTTPServer(('', PORT), DashboardHandler)
    print(f"✅ Dashboard at http://localhost:{PORT}")
    print("   Bot Status + Analytics + Block Trades\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✅ Stopped")
        server.shutdown()
