#!/usr/bin/env python3
"""
Block Trades Real-Time Dashboard
Displays institutional block trade detections with live updates
Runs on port 8889
"""

import json
import csv
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 8889
BLOCK_CSV = Path("block_trades.csv")


class BlockTradesDashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.serve_dashboard()
        elif self.path == "/api/trades":
            self.send_json_response(self.get_trades())
        elif self.path == "/api/stats":
            self.send_json_response(self.get_stats())
        else:
            self.send_error(404)

    def serve_dashboard(self):
        """Serve the block trades dashboard HTML"""
        html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Block Trades Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            color: #e2e8f0;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        header {
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #475569;
        }
        h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            background: linear-gradient(135deg, #fbbf24, #f59e0b);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .subtitle { color: #94a3b8; font-size: 1.1em; }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: #1e293b;
            border: 2px solid #334155;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }
        .stat-label { color: #94a3b8; font-size: 0.9em; margin-bottom: 8px; }
        .stat-value { font-size: 2.5em; font-weight: bold; color: #fbbf24; }
        .stat-sub { color: #64748b; font-size: 0.85em; margin-top: 8px; }

        .table-container {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 20px;
            overflow-x: auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th {
            background: #0f172a;
            color: #fbbf24;
            padding: 12px;
            text-align: left;
            font-weight: bold;
            border-bottom: 2px solid #334155;
        }
        td {
            padding: 12px;
            border-bottom: 1px solid #334155;
        }
        tr:hover { background: #0f172a; }

        .block-badge {
            display: inline-block;
            background: #dc2626;
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: bold;
        }
        .symbol {
            font-weight: bold;
            color: #fbbf24;
            font-size: 1.1em;
        }
        .price { color: #10b981; }
        .size { color: #3b82f6; }
        .notional { color: #f97316; font-weight: bold; }

        .no-data {
            text-align: center;
            padding: 60px 20px;
            color: #64748b;
        }
        .no-data-icon { font-size: 4em; margin-bottom: 20px; }

        .refresh-info {
            text-align: center;
            color: #94a3b8;
            margin-top: 20px;
            font-size: 0.9em;
        }
        .status-badge {
            display: inline-block;
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: bold;
            margin: 10px 0;
        }
        .status-active { background: #10b981; color: white; }
        .status-waiting { background: #f59e0b; color: white; }

        .last-updated {
            color: #64748b;
            font-size: 0.85em;
            margin-top: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🚨 Block Trades Dashboard</h1>
            <p class="subtitle">Real-Time Institutional Flow Detection</p>
        </header>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Total Detected</div>
                <div class="stat-value" id="total-trades">0</div>
                <div class="stat-sub">institutional flows</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Notional Value</div>
                <div class="stat-value" id="total-value">$0</div>
                <div class="stat-sub">aggregate volume</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Unique Symbols</div>
                <div class="stat-value" id="unique-symbols">0</div>
                <div class="stat-sub">with block trades</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Detector Status</div>
                <div id="status-badge" class="status-badge status-active">🟢 ACTIVE</div>
            </div>
        </div>

        <div class="table-container">
            <div id="trades-content">
                <div class="no-data">
                    <div class="no-data-icon">⏳</div>
                    <p>Waiting for block trades...</p>
                    <p style="margin-top: 10px; color: #475569;">Block trades (10K+ shares or $200K+) will appear here</p>
                </div>
            </div>
        </div>

        <div class="refresh-info">
            📊 Updates every 2 seconds | Last updated: <span id="last-update">--:--:--</span>
            <div class="last-updated" id="detector-info">Detector: Scanning for institutional flows during market hours</div>
        </div>
    </div>

    <script>
        async function updateDashboard() {
            try {
                // Fetch trades and stats
                const [tradesResp, statsResp] = await Promise.all([
                    fetch('/api/trades').then(r => r.json()),
                    fetch('/api/stats').then(r => r.json())
                ]);

                // Update stats
                document.getElementById('total-trades').textContent = statsResp.total_trades;
                document.getElementById('total-value').textContent = '$' + statsResp.total_notional.toLocaleString('en-US', {maximumFractionDigits: 0});
                document.getElementById('unique-symbols').textContent = statsResp.unique_symbols;

                // Update detector status
                const statusBadge = document.getElementById('status-badge');
                if (statsResp.detector_running) {
                    statusBadge.textContent = '🟢 ACTIVE';
                    statusBadge.className = 'status-badge status-active';
                } else {
                    statusBadge.textContent = '⏸️ WAITING';
                    statusBadge.className = 'status-badge status-waiting';
                }

                // Update last update time
                document.getElementById('last-update').textContent = new Date().toLocaleTimeString();

                // Render trades table or no-data message
                const container = document.getElementById('trades-content');
                if (tradesResp.trades.length === 0) {
                    container.innerHTML = `
                        <div class="no-data">
                            <div class="no-data-icon">⏳</div>
                            <p>Waiting for block trades...</p>
                            <p style="margin-top: 10px; color: #475569;">Block trades (10K+ shares or $200K+) will appear here</p>
                        </div>
                    `;
                } else {
                    let html = `
                        <table>
                            <thead>
                                <tr>
                                    <th>Time</th>
                                    <th>Symbol</th>
                                    <th>Price</th>
                                    <th>Size</th>
                                    <th>Notional Value</th>
                                    <th>Type</th>
                                </tr>
                            </thead>
                            <tbody>
                    `;

                    for (const trade of tradesResp.trades.reverse()) {
                        const notional = parseFloat(trade.notional_value);
                        const size = parseInt(trade.size);
                        const isLargeSize = size >= 10000;
                        const isLargeValue = notional >= 200000;

                        html += `
                            <tr>
                                <td>${trade.timestamp}</td>
                                <td><span class="symbol">${trade.symbol}</span></td>
                                <td><span class="price">$${parseFloat(trade.price).toFixed(2)}</span></td>
                                <td><span class="size">${size.toLocaleString()}</span></td>
                                <td><span class="notional">$${notional.toLocaleString('en-US', {maximumFractionDigits: 0})}</span></td>
                                <td>
                                    ${isLargeSize ? '<span class="block-badge">Large Size</span>' : ''}
                                    ${isLargeValue ? '<span class="block-badge">Large Value</span>' : ''}
                                </td>
                            </tr>
                        `;
                    }

                    html += `
                            </tbody>
                        </table>
                    `;
                    container.innerHTML = html;
                }

            } catch (error) {
                console.error('Dashboard update failed:', error);
            }
        }

        // Initial update and set up refresh interval
        updateDashboard();
        setInterval(updateDashboard, 2000); // Refresh every 2 seconds
    </script>
</body>
</html>"""

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def get_trades(self):
        """Get all block trades from CSV"""
        trades = []
        if BLOCK_CSV.exists():
            try:
                with open(BLOCK_CSV) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        trades.append(row)
            except Exception as e:
                print(f"Error reading trades: {e}")
        return {"trades": trades}

    def get_stats(self):
        """Get block trade statistics"""
        trades = []
        if BLOCK_CSV.exists():
            try:
                with open(BLOCK_CSV) as f:
                    reader = csv.DictReader(f)
                    trades = list(reader)
            except Exception as e:
                print(f"Error reading stats: {e}")

        total_notional = sum(float(t.get("notional_value", 0)) for t in trades)
        unique_symbols = len(set(t.get("symbol", "") for t in trades))

        return {
            "total_trades": len(trades),
            "total_notional": total_notional,
            "unique_symbols": unique_symbols,
            "detector_running": True,
            "last_trade_time": trades[-1].get("timestamp") if trades else "Never"
        }

    def send_json_response(self, data):
        """Send JSON response"""
        response = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("Content-Length", len(response))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args, **kwargs):
        pass  # Suppress logs


if __name__ == "__main__":
    server = HTTPServer(('', PORT), BlockTradesDashboardHandler)
    print(f"✅ Block Trades Dashboard at http://localhost:{PORT}")
    print("   Real-Time Institutional Flow Monitoring\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✅ Stopped")
        server.shutdown()
