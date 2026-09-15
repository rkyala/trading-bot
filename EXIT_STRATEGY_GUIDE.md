# Exit Strategy Guide (Live Deployment)

## Overview

**Module:** `exit_strategy.py`
**Purpose:** Manage live position entries/exits with profit targets, stops, and risk management
**Status:** Ready for Monday 8/26 deployment

---

## Exit Rules (Mean-Reversion Optimized)

| Condition | Trigger | Action |
|-----------|---------|--------|
| **Profit Target** | Price +1.5% | Sell (lock profit) |
| **Stop Loss** | Price -1.5% | Sell (cut loss) |
| **Time Exit** | Held 4+ hours | Sell (close EOD) |
| **Trailing Stop** | Hit after +0.5% gain | Sell (protect profit) |

---

## Integration with Live Bot (Stage 3 MCP)

### Current Flow (Dry-Run)
```
Signal → Open hypothetical → Close at +1.5% → Record profit
```

### New Flow (Live - Monday)
```
Signal → MCP place_equity_order()
        ↓
        Track position in Robinhood
        ↓
        Check exit conditions every cycle
        ↓
        MCP cancel/sell if exit triggered
        ↓
        Record P&L
```

---

## Code Integration

### 1. Initialize Exit Manager (in bot startup)
```python
from exit_strategy import MeanReversionExit

exit_mgr = MeanReversionExit()
```

### 2. On Trade Entry (after MCP place_equity_order)
```python
exit_mgr.open_position(
    symbol="AAPL",
    entry_price=150.00,
    position_size=600
)
```

### 3. Every Cycle (check exits)
```python
for symbol in exit_mgr.positions:
    current_price = get_current_price(symbol)
    exit_reason, details = exit_mgr.check_exit(symbol, current_price)
    
    if exit_reason:
        # Execute MCP sell order
        mcp.place_equity_order(
            symbol=symbol,
            quantity=qty,
            side="sell",
            order_type="market"
        )
        
        # Record exit
        exit_mgr.close_position(symbol, current_price, exit_reason)
```

### 4. End of Day (print summary)
```python
exit_mgr.print_summary()
exit_mgr.save_trades_log("closed_trades.json")
```

---

## Position Management Features

### Open Positions Tracking
- Entry price, time, size
- Current P&L calculation
- Multiple exit conditions checked

### Closed Trades Logging
- Symbol, entry/exit prices
- Holding time, P&L in $ and %
- Exit reason (profit target, stop, time, etc.)
- JSON export for analysis

### Daily Summary
- Win/loss count
- Win rate %
- Total P&L
- Average P&L per trade

---

## Risk Management Built-In

| Risk Factor | Protection |
|------------|------------|
| Runaway loss | Stop loss at -1.5% |
| Lost profits | Trailing stop at +0.5% |
| Overnight risk | Time exit at 4 hours |
| Over-leverage | Position size fixed ($600) |
| Duplicate positions | Check open positions before entry |

---

## Deployment Checklist (Monday 8/26)

- [ ] Integrate `exit_strategy.py` into Stage 3 bot
- [ ] Link MCP `place_equity_order()` to exit logic
- [ ] Test exit on simulator first
- [ ] Set position size to $600
- [ ] Enable P&L logging
- [ ] Monitor first 5 trades manually
- [ ] Verify Robinhood positions update correctly
- [ ] Check exit reasons match expected behavior

---

## Expected Results (Week 1 Live)

**With exit strategy:**
- Entry at mean-reversion signal (high confidence)
- Exit at +1.5% profit OR -1.5% stop OR 4-hour timeout
- Expected: 15-25 trades/week
- Expected: 55-65% win rate
- Expected: +$200-400 weekly profit

---

## Files

- **exit_strategy.py** - Exit manager + position tracking
- **EXIT_STRATEGY_GUIDE.md** - This file
- **closed_trades.json** - Daily trade log (auto-generated)

---

## Next Steps

1. ✅ Exit strategy module created
2. ⏳ Test exit logic in simulator (tomorrow)
3. ⏳ Integrate with Stage 3 bot (Fri Aug 23)
4. ⏳ Live deployment (Mon Aug 26)

---

## Support

For exit logic changes:
- Edit profit target: Line 67 (change 1.5 → X%)
- Edit stop loss: Line 70 (change -1.5 → X%)
- Edit time exit: Line 73 (change 4 → X hours)
- Edit trailing stop: Line 77 (change 0.5 → X%)

Ready for live trading! 🚀
