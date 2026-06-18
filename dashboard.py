#!/usr/bin/env python3
"""
Generate a mobile-friendly HTML dashboard for the trading bot.
Shows: positions, daily trades, P&L, metrics, win rate.
Reads from bot_state.json and daily_metrics.json.
"""

import json
import os
from datetime import datetime
from pathlib import Path

DATA_DIR = os.environ.get("DATA_DIR", ".")

def load_json(filename):
    try:
        with open(os.path.join(DATA_DIR, filename)) as f:
            return json.load(f)
    except:
        return None

def format_currency(value):
    if value is None:
        return "$0.00"
    color = "green" if value >= 0 else "red"
    sign = "+" if value >= 0 else ""
    return f'<span style="color: {color}; font-weight: bold;">{sign}${value:,.2f}</span>'

def generate_dashboard():
    state = load_json("bot_state.json")
    metrics = load_json("daily_metrics.json")
    
    positions = state.get("positions", {}) if state else {}
    trades = state.get("trade_history", []) if state else []
    
    # Get today's trades
    today = datetime.now().strftime("%Y-%m-%d")
    today_trades = [t for t in trades[-50:] if t.get("date", "")[:10] == today]
    
    # Calculate stats
    total_pnl = sum(t.get("realized_pnl", 0) for t in today_trades)
    wins = sum(1 for t in today_trades if t.get("realized_pnl", 0) > 0)
    losses = sum(1 for t in today_trades if t.get("realized_pnl", 0) < 0)
    win_rate = (wins / len(today_trades) * 100) if today_trades else 0
    
    # Token metrics
    token_cost = metrics.get("token_cost_usd", 0) if metrics else 0
    roi = (total_pnl / token_cost * 100) if token_cost > 0 else 0
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Bot Dashboard</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            padding: 12px;
            line-height: 1.5;
        }}
        
        .container {{
            max-width: 600px;
            margin: 0 auto;
        }}
        
        .header {{
            text-align: center;
            padding: 16px 0;
            border-bottom: 2px solid #334155;
            margin-bottom: 16px;
        }}
        
        .title {{
            font-size: 24px;
            font-weight: bold;
            color: #38bdf8;
        }}
        
        .timestamp {{
            font-size: 12px;
            color: #94a3b8;
            margin-top: 4px;
        }}
        
        .card {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.3);
        }}
        
        .card-title {{
            font-size: 14px;
            font-weight: 600;
            color: #cbd5e1;
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .metric {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0;
            border-bottom: 1px solid #334155;
        }}
        
        .metric:last-child {{
            border-bottom: none;
        }}
        
        .metric-label {{
            font-size: 13px;
            color: #94a3b8;
        }}
        
        .metric-value {{
            font-size: 16px;
            font-weight: bold;
            color: #38bdf8;
        }}
        
        .stat-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-bottom: 12px;
        }}
        
        .stat-box {{
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 6px;
            padding: 12px;
            text-align: center;
        }}
        
        .stat-value {{
            font-size: 20px;
            font-weight: bold;
            color: #10b981;
        }}
        
        .stat-label {{
            font-size: 11px;
            color: #94a3b8;
            margin-top: 4px;
            text-transform: uppercase;
        }}
        
        .negative {{
            color: #ef4444 !important;
        }}
        
        .positive {{
            color: #10b981 !important;
        }}
        
        .position {{
            background: #0f172a;
            border-left: 3px solid #38bdf8;
            padding: 10px;
            margin: 8px 0;
            border-radius: 4px;
        }}
        
        .position-symbol {{
            font-weight: bold;
            font-size: 14px;
            margin-bottom: 4px;
        }}
        
        .position-info {{
            font-size: 12px;
            color: #94a3b8;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }}
        
        .trade {{
            background: #0f172a;
            border-left: 3px solid #334155;
            padding: 10px;
            margin: 8px 0;
            border-radius: 4px;
            font-size: 12px;
        }}
        
        .trade.win {{
            border-left-color: #10b981;
        }}
        
        .trade.loss {{
            border-left-color: #ef4444;
        }}
        
        .trade-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 4px;
            font-weight: bold;
        }}
        
        .trade-symbol {{
            color: #38bdf8;
        }}
        
        .trade-pnl {{
            font-weight: bold;
        }}
        
        .empty {{
            text-align: center;
            color: #64748b;
            padding: 20px;
            font-size: 13px;
        }}
        
        .refresh-note {{
            text-align: center;
            color: #64748b;
            font-size: 11px;
            margin-top: 12px;
            padding: 8px;
            background: #0f172a;
            border-radius: 4px;
        }}
        
        @media (max-width: 480px) {{
            body {{ padding: 8px; }}
            .card {{ padding: 12px; }}
            .title {{ font-size: 20px; }}
        }}
    </style>
    <meta http-equiv="refresh" content="30">
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title">📊 Trading Bot</div>
            <div class="timestamp">Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ET</div>
        </div>
        
        <!-- Daily Summary -->
        <div class="card">
            <div class="card-title">Today's Summary</div>
            <div class="stat-grid">
                <div class="stat-box">
                    <div class="stat-value {'positive' if total_pnl >= 0 else 'negative'}">
                        ${abs(total_pnl):.2f}
                    </div>
                    <div class="stat-label">Daily P&L</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value">{win_rate:.0f}%</div>
                    <div class="stat-label">Win Rate</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value">{len(today_trades)}</div>
                    <div class="stat-label">Trades</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value {'positive' if roi >= 100 else 'negative'}">{roi:+.0f}%</div>
                    <div class="stat-label">ROI</div>
                </div>
            </div>
        </div>
        
        <!-- Open Positions -->
        <div class="card">
            <div class="card-title">🔓 Open Positions ({len(positions)})</div>
            {
                ''.join([
                    f'''<div class="position">
                        <div class="position-symbol">{sym}</div>
                        <div class="position-info">
                            <div>Entry: ${p.get('entry_price', 0):.2f}</div>
                            <div>Size: ${p.get('entry_state', {}).get('size', 'N/A')}</div>
                            <div>Sector: {p.get('sector', 'N/A')}</div>
                            <div>HWM: ${p.get('high_water_mark', 0):.2f}</div>
                        </div>
                    </div>'''
                    for sym, p in list(positions.items())[:5]
                ])
                or '<div class="empty">No open positions</div>'
            }
        </div>
        
        <!-- Today's Trades -->
        <div class="card">
            <div class="card-title">📈 Today's Trades</div>
            {
                ''.join([
                    f'''<div class="trade {'win' if t.get('realized_pnl', 0) > 0 else 'loss'}">
                        <div class="trade-header">
                            <span class="trade-symbol">{t.get('symbol', 'N/A')}</span>
                            <span class="trade-pnl {'positive' if t.get('realized_pnl', 0) > 0 else 'negative'}">
                                {t.get('realized_pnl', 0):+.2f}
                            </span>
                        </div>
                        <div style="color: #94a3b8;">
                            {t.get('date', 'N/A')[-5:]} | 
                            Entry: ${t.get('entry_price', 0):.2f} → 
                            Exit: ${t.get('exit_price', 0):.2f}
                        </div>
                    </div>'''
                    for t in reversed(today_trades[-10:])
                ])
                or '<div class="empty">No trades today</div>'
            }
        </div>
        
        <!-- Token Metrics -->
        <div class="card">
            <div class="card-title">⚡ Token Usage</div>
            <div class="metric">
                <span class="metric-label">Daily Cost</span>
                <span class="metric-value">${token_cost:.4f}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Runs Today</span>
                <span class="metric-value">{metrics.get('runs', 0) if metrics else 0}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Cost per Trade</span>
                <span class="metric-value">${token_cost / len(today_trades):.4f if today_trades else 0:.4f}</span>
            </div>
        </div>
        
        <div class="refresh-note">
            🔄 Auto-refreshes every 30 seconds
        </div>
    </div>
</body>
</html>
"""
    
    return html

def save_dashboard():
    html = generate_dashboard()
    output_path = os.path.join(DATA_DIR, "dashboard.html")
    with open(output_path, 'w') as f:
        f.write(html)
    print(f"Dashboard saved to {output_path}")

if __name__ == "__main__":
    save_dashboard()
