# Dashboard Enhancement - Block Trade Integration

## Current Status
The existing `dashboard_server.py` runs on `http://localhost:8888` and displays:
- Bot stats (cycles, signals, analyzed, skipped)
- System status (MCP, Bot, Log size)
- Schedule info
- Last cycle data
- Next cycle info

## Enhancement Needed
Add Block Trade Detector information:
- Block trades count
- Latest institutional flows
- Thresholds met
- Real-time stream status

## Implementation Steps

1. **Add API Endpoint** (`/api/block_trades`)
   - Read block_trades.csv
   - Return latest 10 trades with formatting
   - Include stream status from block_trade_stream.log

2. **Add UI Section**
   - Insert "🚨 Block Trades" card in dashboard
   - Display table of latest institutional flows
   - Show total detected count
   - Indicate stream active/inactive status

3. **Data Refresh**
   - Add block trades fetch to updateAll() JavaScript
   - Update every 2 seconds (like other stats)
   - Show live count as it updates

## Example Output
```
🚨 BLOCK TRADES (Real-time Stream)

Timestamp           | Symbol | Price  | Size      | Value
08/25 09:42:11     | NVDA   | $128.50| 15,000    | $1,927,500
08/25 09:35:22     | SPY    | $560.10| 10,000    | $5,601,000
08/25 09:28:14     | AAPL   | $220.45| 12,000    | $2,645,400
```

## Next Action
To add block trades to existing dashboard:
```bash
# Modify dashboard_server.py:
# 1. Add get_block_trades() method
# 2. Add /api/block_trades endpoint handler
# 3. Add block trades card to HTML
# 4. Add fetch call to JavaScript updateAll()
```

This keeps the existing dashboard working while adding institutional flow monitoring.
