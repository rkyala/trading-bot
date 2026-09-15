#!/usr/bin/env python3
"""
Simple Log Server - Serve bot logs via HTTP (no external dependencies)
Access at: http://localhost:8888
"""

import http.server
import socketserver
import json
from datetime import datetime
import urllib.parse

LOG_FILE = "/Users/ramayalala/trading_bot_uw/dry_run_logs/bot_20260819.log"
PORT = 8888

class LogHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        """Handle GET requests"""
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path

        if path == '/' or path == '/dashboard':
            self.send_dashboard()
        elif path == '/api/trades':
            self.send_trades_json()
        elif path == '/api/log':
            self.send_log_json()
        else:
            self.send_error(404, "Not Found")

    def send_dashboard(self):
        """Send HTML dashboard"""
        try:
            with open(LOG_FILE, 'r') as f:
                lines = f.readlines()

            # Parse trades
            trades = []
            for line in lines:
                if " | BUY | " in line:
                    trades.append({"type": "BUY", "line": line.strip()})
                elif " | SKIP | " in line:
                    trades.append({"type": "SKIP", "line": line.strip()})

            buy_count = sum(1 for t in trades if t['type'] == 'BUY')
            skip_count = sum(1 for t in trades if t['type'] == 'SKIP')

            html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>🤖 Bot Log Server</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{
            font-family: 'Courier New', monospace;
            margin: 0;
            padding: 20px;
            background: #0a0e27;
            color: #00ff00;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header {{
            background: #1a1f3a;
            padding: 20px;
            border-radius: 5px;
            margin-bottom: 20px;
            border-left: 4px solid #00ff00;
        }}
        .header h1 {{
            margin: 0 0 10px 0;
            color: #00ff00;
        }}
        .header p {{
            margin: 5px 0;
            color: #aaa;
        }}
        .metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .metric {{
            background: #1a1f3a;
            padding: 15px;
            border-radius: 5px;
            border-left: 3px solid #00ff00;
        }}
        .metric-label {{
            font-size: 0.8em;
            color: #888;
            margin-bottom: 8px;
        }}
        .metric-value {{
            font-size: 2.5em;
            font-weight: bold;
            color: #00ff00;
        }}
        .section {{
            background: #1a1f3a;
            padding: 20px;
            border-radius: 5px;
            margin-bottom: 20px;
            border-left: 3px solid #0f6;
        }}
        .section-title {{
            font-size: 1.2em;
            margin-bottom: 15px;
            color: #ffff00;
            border-bottom: 1px solid #444;
            padding-bottom: 10px;
        }}
        .trades-container {{
            max-height: 500px;
            overflow-y: auto;
        }}
        .buy-line {{
            color: #00ff00;
            margin: 4px 0;
            font-size: 0.9em;
            padding: 4px;
            border-left: 2px solid #00ff00;
            padding-left: 8px;
        }}
        .skip-line {{
            color: #666;
            margin: 4px 0;
            font-size: 0.9em;
            padding: 4px;
            padding-left: 8px;
        }}
        .log-lines {{
            max-height: 600px;
            overflow-y: auto;
            background: #0a0e27;
            padding: 10px;
            border-radius: 3px;
        }}
        .log-line {{
            margin: 2px 0;
            font-size: 0.85em;
            line-height: 1.3;
            color: #0f0;
        }}
        .footer {{
            text-align: center;
            color: #666;
            font-size: 0.85em;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #333;
        }}
        .api-links {{
            color: #0f6;
            text-decoration: none;
            margin: 0 10px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Trading Bot Log Server</h1>
            <p>Real-time log dashboard • Auto-refresh: 30 seconds</p>
            <p>Updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S CDT")}</p>
        </div>

        <div class="metrics">
            <div class="metric">
                <div class="metric-label">📊 Total Trades</div>
                <div class="metric-value">{buy_count}</div>
            </div>
            <div class="metric">
                <div class="metric-label">⏭️ Skipped</div>
                <div class="metric-value">{skip_count}</div>
            </div>
            <div class="metric">
                <div class="metric-label">📈 Log Lines</div>
                <div class="metric-value">{len(lines)}</div>
            </div>
        </div>

        <div class="section">
            <div class="section-title">📊 Recent Trades (Last 50)</div>
            <div class="trades-container">
"""
            for trade in reversed(trades[-50:]):
                css_class = "buy-line" if trade['type'] == 'BUY' else "skip-line"
                html += f'<div class="{css_class}">{trade["line"]}</div>\n'

            html += """
            </div>
        </div>

        <div class="section">
            <div class="section-title">📝 Full Log (Last 150 Lines)</div>
            <div class="log-lines">
"""
            log_lines = lines[-150:]
            for line in log_lines:
                if line.strip():
                    html += f'<div class="log-line">{line.strip()}</div>\n'

            html += f"""
            </div>
        </div>

        <div class="footer">
            Dashboard | <a class="api-links" href="/api/trades">API: Trades</a> | <a class="api-links" href="/api/log">API: Raw Log</a>
            <br>Auto-refresh enabled • Last updated: {datetime.now().strftime("%H:%M:%S")}
        </div>
    </div>
</body>
</html>
"""
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))

        except Exception as e:
            self.send_error(500, f"Error: {str(e)}")

    def send_trades_json(self):
        """Send trades as JSON"""
        try:
            with open(LOG_FILE, 'r') as f:
                lines = f.readlines()

            trades = []
            for line in lines:
                if " | BUY | " in line:
                    trades.append({"type": "BUY", "line": line.strip()})
                elif " | SKIP | " in line:
                    trades.append({"type": "SKIP", "line": line.strip()})

            buy_count = sum(1 for t in trades if t['type'] == 'BUY')

            response = {
                "trades": trades[-50:],
                "count": len(trades),
                "buy_count": buy_count,
                "timestamp": datetime.now().isoformat()
            }

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response, indent=2).encode('utf-8'))

        except Exception as e:
            self.send_error(500, f"Error: {str(e)}")

    def send_log_json(self):
        """Send raw log as JSON"""
        try:
            with open(LOG_FILE, 'r') as f:
                lines = f.readlines()

            response = {
                "total_lines": len(lines),
                "last_100_lines": lines[-100:],
                "timestamp": datetime.now().isoformat()
            }

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response, indent=2).encode('utf-8'))

        except Exception as e:
            self.send_error(500, f"Error: {str(e)}")

    def log_message(self, format, *args):
        """Suppress logging"""
        pass


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

    with socketserver.TCPServer(("127.0.0.1", PORT), LogHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n✅ Server stopped")
