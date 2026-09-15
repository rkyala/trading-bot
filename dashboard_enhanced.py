#!/usr/bin/env python3
"""
Enhanced Dashboard with Exit Strategy
Shows live trades, P&L, and exit recommendations
"""

import os
import json
import re
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import yfinance as yf

PORT = 8890

class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler for dashboard"""

    def do_GET(self):
        """Handle GET requests"""
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.send_header('Refresh', '30')  # Auto-refresh every 30s
        self.end_headers()

        html = self.generate_html()
        self.wfile.write(html.encode('utf-8'))

    def generate_html(self):
        """Generate dashboard HTML"""
        # Load trades from bot log
        trades = self.parse_bot_log()

        # Load exit suggestions
        exits = self.load_exit_suggestions()

        # Get current prices and P&L
        trades_with_pnl = self.calculate_pnl(trades)

        # Get daily stats
        daily_stats = self.calculate_stats(exits)

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Trading Bot Dashboard with Exits</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    margin: 20px;
                    background-color: #f5f5f5;
                }}
                .container {{
                    max-width: 1400px;
                    margin: 0 auto;
                }}
                .header {{
                    background-color: #2c3e50;
                    color: white;
                    padding: 20px;
                    border-radius: 5px;
                    margin-bottom: 20px;
                }}
                .stats {{
                    display: grid;
                    grid-template-columns: repeat(4, 1fr);
                    gap: 15px;
                    margin-bottom: 20px;
                }}
                .stat-card {{
                    background-color: white;
                    padding: 15px;
                    border-radius: 5px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                }}
                .stat-label {{
                    font-size: 12px;
                    color: #7f8c8d;
                    font-weight: bold;
                }}
                .stat-value {{
                    font-size: 24px;
                    font-weight: bold;
                    color: #2c3e50;
                    margin-top: 5px;
                }}
                .positive {{ color: #27ae60; }}
                .negative {{ color: #e74c3c; }}
                .table-section {{
                    background-color: white;
                    padding: 20px;
                    border-radius: 5px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                    margin-bottom: 20px;
                }}
                .section-title {{
                    font-size: 18px;
                    font-weight: bold;
                    margin-bottom: 15px;
                    color: #2c3e50;
                    border-bottom: 2px solid #3498db;
                    padding-bottom: 10px;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    font-size: 12px;
                }}
                th {{
                    background-color: #34495e;
                    color: white;
                    padding: 10px;
                    text-align: left;
                    font-weight: bold;
                }}
                td {{
                    padding: 10px;
                    border-bottom: 1px solid #ecf0f1;
                }}
                tr:hover {{
                    background-color: #f8f9fa;
                }}
                .exit-buy {{
                    background-color: #d5f4e6;
                    color: #27ae60;
                    padding: 3px 8px;
                    border-radius: 3px;
                    font-weight: bold;
                }}
                .exit-sell {{
                    background-color: #fadbd8;
                    color: #e74c3c;
                    padding: 3px 8px;
                    border-radius: 3px;
                    font-weight: bold;
                }}
                .exit-hold {{
                    background-color: #fdebd0;
                    color: #f39c12;
                    padding: 3px 8px;
                    border-radius: 3px;
                    font-weight: bold;
                }}
                .timestamp {{
                    font-size: 11px;
                    color: #95a5a6;
                }}
                .profit {{
                    font-weight: bold;
                }}
                .profit.positive {{
                    color: #27ae60;
                }}
                .profit.negative {{
                    color: #e74c3c;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🤖 Trading Bot Dashboard with Exit Strategy</h1>
                    <p class="timestamp">Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>

                <div class="stats">
                    <div class="stat-card">
                        <div class="stat-label">Total Trades</div>
                        <div class="stat-value">{daily_stats['total_trades']}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Daily Profit</div>
                        <div class="stat-value {('positive' if daily_stats['total_pnl'] >= 0 else 'negative')}">
                            ${daily_stats['total_pnl']:+.2f}
                        </div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Exit Suggestions</div>
                        <div class="stat-value">{daily_stats['exit_count']}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Win Rate</div>
                        <div class="stat-value">{daily_stats['win_rate']:.1f}%</div>
                    </div>
                </div>

                <div class="table-section">
                    <div class="section-title">📊 Open Positions ({len(trades_with_pnl)})</div>
                    <table>
                        <thead>
                            <tr>
                                <th>Symbol</th>
                                <th>Entry Price</th>
                                <th>Current Price</th>
                                <th>P&L %</th>
                                <th>P&L $</th>
                                <th>Holding Time</th>
                                <th>Exit Signal</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            {self.render_trades_table(trades_with_pnl, exits)}
                        </tbody>
                    </table>
                </div>

                <div class="table-section">
                    <div class="section-title">⚠️ Exit Recommendations ({daily_stats['exit_count']})</div>
                    <table>
                        <thead>
                            <tr>
                                <th>Symbol</th>
                                <th>Entry</th>
                                <th>Current</th>
                                <th>P&L $</th>
                                <th>Reason</th>
                                <th>Holding</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            {self.render_exits_table(exits)}
                        </tbody>
                    </table>
                </div>

                <div style="text-align: center; margin-top: 30px; color: #95a5a6; font-size: 12px;">
                    <p>Dashboard auto-refreshes every 30 seconds</p>
                    <p>Exit Monitor runs hourly to check for exits</p>
                </div>
            </div>
        </body>
        </html>
        """
        return html

    def parse_bot_log(self):
        """Parse BUY trades from bot log"""
        today = datetime.now().strftime("%Y%m%d")
        log_file = f"dry_run_logs/bot_{today}.log"
        trades = []

        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()

            for line in lines:
                if "| BUY |" in line:
                    match = re.search(r"BUY \| (\w+) @ \$([0-9.]+)", line)
                    if match:
                        symbol = match.group(1)
                        entry_price = float(match.group(2))

                        time_match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                        entry_time = time_match.group(1) if time_match else "unknown"

                        trades.append({
                            "symbol": symbol,
                            "entry_price": entry_price,
                            "entry_time": entry_time
                        })
        except:
            pass

        return trades

    def load_exit_suggestions(self):
        """Load exit suggestions from JSON"""
        try:
            exits = []
            with open("dry_run_logs/exit_suggestions.json", 'r') as f:
                for line in f:
                    if line.strip():
                        exits.append(json.loads(line))
            return exits
        except:
            return []

    def calculate_pnl(self, trades):
        """Calculate current P&L for each trade"""
        trades_pnl = []

        for trade in trades:
            symbol = trade["symbol"]
            entry_price = trade["entry_price"]

            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                current_price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
            except:
                current_price = 0

            if current_price > 0:
                pnl_percent = ((current_price - entry_price) / entry_price) * 100
                pnl_dollars = (current_price - entry_price) * (600 / entry_price)

                # Calculate holding time
                try:
                    entry_dt = datetime.strptime(trade["entry_time"], "%Y-%m-%d %H:%M:%S")
                    holding_time = (datetime.now() - entry_dt).total_seconds() / 3600
                except:
                    holding_time = 0

                # Determine exit signal
                exit_signal = "HOLD"
                if pnl_percent >= 1.5:
                    exit_signal = "✅ PROFIT TARGET"
                elif pnl_percent <= -1.5:
                    exit_signal = "⛔ STOP LOSS"
                elif holding_time >= 4:
                    exit_signal = "⏱️ TIME EXIT"
                elif pnl_percent > 0.5 and (current_price < entry_price * 1.005):
                    exit_signal = "📉 TRAILING STOP"

                trades_pnl.append({
                    "symbol": symbol,
                    "entry_price": entry_price,
                    "current_price": current_price,
                    "pnl_percent": pnl_percent,
                    "pnl_dollars": pnl_dollars,
                    "holding_time": holding_time,
                    "exit_signal": exit_signal
                })

        return trades_pnl

    def calculate_stats(self, exits):
        """Calculate daily statistics"""
        today = datetime.now().strftime("%Y%m%d")
        trades_file = f"dry_run_logs/bot_{today}.log"
        total_trades = 0
        total_pnl = 0
        wins = 0
        losses = 0

        try:
            with open(trades_file, 'r') as f:
                content = f.read()
                total_trades = len(re.findall(r"| BUY |", content))

                # Try to get profit data
                profit_matches = re.findall(r"Total profit: \+\$([0-9.]+)", content)
                if profit_matches:
                    total_pnl = sum(float(p) for p in profit_matches)

                # Count wins/losses from exits
                for exit_info in exits:
                    if exit_info.get("pnl_dollars", 0) > 0:
                        wins += 1
                    elif exit_info.get("pnl_dollars", 0) < 0:
                        losses += 1
        except:
            pass

        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

        return {
            "total_trades": total_trades,
            "total_pnl": total_pnl,
            "exit_count": len(exits),
            "win_rate": win_rate,
            "wins": wins,
            "losses": losses
        }

    def render_trades_table(self, trades, exits):
        """Render trades table rows"""
        rows = []
        for trade in trades:
            symbol = trade["symbol"]
            pnl_class = "positive" if trade["pnl_dollars"] >= 0 else "negative"

            # Check if in exit suggestions
            in_exits = any(e["symbol"] == symbol for e in exits)
            exit_class = "exit-sell" if in_exits else "exit-hold"

            rows.append(f"""
            <tr>
                <td><strong>{symbol}</strong></td>
                <td>${trade['entry_price']:.2f}</td>
                <td>${trade['current_price']:.2f}</td>
                <td class="{pnl_class}">{trade['pnl_percent']:+.2f}%</td>
                <td class="profit {pnl_class}">${trade['pnl_dollars']:+.2f}</td>
                <td>{trade['holding_time']:.1f}h</td>
                <td><span class="{exit_class}">{trade['exit_signal']}</span></td>
                <td>{'SELL' if in_exits else 'HOLD'}</td>
            </tr>
            """)

        return "".join(rows) if rows else "<tr><td colspan='8' style='text-align: center;'>No open positions</td></tr>"

    def render_exits_table(self, exits):
        """Render exit suggestions table rows"""
        rows = []
        for exit_info in exits:
            pnl_class = "positive" if exit_info.get("pnl_dollars", 0) >= 0 else "negative"

            rows.append(f"""
            <tr>
                <td><strong>{exit_info.get('symbol', 'N/A')}</strong></td>
                <td>${exit_info.get('entry_price', 0):.2f}</td>
                <td>${exit_info.get('current_price', 0):.2f}</td>
                <td class="profit {pnl_class}">${exit_info.get('pnl_dollars', 0):+.2f}</td>
                <td><strong>{exit_info.get('exit_reason', 'N/A')}</strong></td>
                <td>{exit_info.get('holding_hours', 0):.1f}h</td>
                <td><span class="exit-sell">SELL</span></td>
            </tr>
            """)

        return "".join(rows) if rows else "<tr><td colspan='7' style='text-align: center;'>No exit suggestions yet</td></tr>"

    def log_message(self, format, *args):
        """Suppress log messages"""
        pass


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), DashboardHandler)
    print(f"✅ Enhanced Dashboard running on http://localhost:{PORT}")
    print("📊 Shows: Open positions + Exit recommendations")
    print("🔄 Auto-refreshes every 30 seconds")
    print("⏹️  Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✅ Dashboard stopped")
