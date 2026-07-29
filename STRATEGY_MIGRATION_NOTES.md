# Strategy Migration: Momentum → Mean-Reversion

## Changes Made to bot.py

### 1. Docstring (Line 1-16)
```diff
- "Momentum BUY strategy: Buy strong movers, exit at +2%/+5%"
+ "Mean-reversion strategy: Buy overbought pullbacks, exit at +1%/+3%"
```

### 2. Configuration (Line 44)
```diff
- CONFIDENCE_THRESHOLD = 55
+ CONFIDENCE_THRESHOLD = 60  # Mean-reversion needs higher confidence
```

### 3. Stage 2 System Prompt (Line 609-640)
**OLD**: "Analyze movers for momentum continuation probability"
**NEW**: "Analyze movers for pullback recovery (mean-reversion) probability"

Key changes:
```
OLD:
  - "Stock up +3 to +8% today = STRONG MOMENTUM, likely to continue"
  - "Entry: BUY at close (catch momentum)"
  - "Hold: 1-2 days (momentum peaks)"

NEW:
  - "Stocks that spiked up +5-8% (overbought/extended)"
  - "Entry: BUY on pullback (-2% to -3% dip)"
  - "Hold: 3-5 days (mean reversion takes time)"
```

### 4. Stage 3 Position Sizing (Line 735-756)
```diff
OLD:
- if confidence >= 90: size = 250
- elif confidence >= 80: size = 200
- else: size = 150

NEW:
+ if confidence >= 80: size = 300  # Higher conviction = bigger
+ elif confidence >= 70: size = 200
+ else: size = 100
```

### 5. Stage 3 Exit Targets (Line 754-755)
```diff
OLD:
- "sell1_price": round(price * 1.02, 2),  # +2%
- "sell2_price": round(price * 1.05, 2),  # +5%

NEW:
+ "sell1_price": round(price * 1.01, 2),  # +1%
+ "sell2_price": round(price * 1.03, 2),  # +3%
```

### 6. Imports (Line 31-35)
```diff
- from learning import daily_learning
+ from autonomous_bot_integration import TradeWithLearning
```

---

## Testing Checklist

- [ ] **Stage 2 scoring**: Run bot, check if Claude scores "overbought" candidates
  ```bash
  python bot.py --test-stage2
  ```

- [ ] **Exit targets**: Verify limits are set at +1% and +3%
  ```bash
  grep -n "sell1_price\|sell2_price" bot.py
  ```

- [ ] **Position sizing**: Check sizes match confidence brackets
  ```bash
  # High confidence (80+) should show 300-share positions
  # Medium confidence (70-79) should show 200-share positions
  ```

- [ ] **Paper trade**: Run for 3-5 trading days to verify signals
  - Are movers being flagged correctly?
  - Are pullbacks detected?
  - Do exits trigger at +1% and +3%?

---

## Autonomous Learning Integration (Optional)

If you want real-time learning to optimize the strategy:

```python
# In bot.py Stage 3, after position closes:

from autonomous_bot_integration import TradeWithLearning

learning = TradeWithLearning(bot)

# On entry:
decision = learning.execute_trade_with_learning(
    symbol=symbol,
    daily_change_pct=daily_change,
    confidence=confidence,
    available_capital=2000
)

# On exit:
learning.close_trade_and_learn(order_id, exit_price, entry_price)
# Bot learns automatically
```

This enables:
- **Q-Learning**: Optimizes position sizing
- **Multi-Armed Bandit**: Learns which strategies work
- **Regime Detection**: Adapts to market conditions

---

## Expected Behavior

### Before (Momentum)
```
NVDA up +6% today
→ Claude: "Strong momentum, BUY"
→ Bot: BUY at close
→ Next day: -2% move
→ Result: LOSS (momentum reversed)
```

### After (Mean-Reversion)
```
NVDA up +6% today (overbought)
→ Claude: "Overbought, expect pullback + recovery"
→ Bot: WAIT for pullback
→ Next day: -2% pullback
→ Bot: BUY at pullback
→ Day 3-4: +3% recovery
→ Result: +1% win (mean reversion played out)
```

---

## Monitoring

Track these metrics daily:
1. **Anomaly scores of tagged movers** - Are we finding overbought stocks?
2. **Pullback vs spike frequency** - How many actually pull back?
3. **Win rate by confidence bracket** - 80%+ confidence working?
4. **Average hold time** - Should be 3-5 days, not 1-2
5. **Exit hit rates** - Are +1% and +3% targets being hit?

Example log output:
```
Stage 2: NVDA anomaly=82, confidence=76, reason="up +7%, expect pullback to -2%, recovery to +3%"
Stage 3: BUY 200 NVDA @ $152.00, targets: +1% ($153.52) and +3% ($156.56)
Learning: Trade closed +1.8% (between targets), feedback to Q-table
```

---

## Rollback Plan

If mean-reversion strategy underperforms:
1. Revert Stage 2 prompt to momentum (git checkout bot.py)
2. Reset exit targets to +2% and +5%
3. Review: Why did mean-reversion fail?
   - Did market stop mean-reverting?
   - Were pullbacks too deep (-5%+ instead of -2%)?
   - Was hold time too short?

---

## Files Modified

- ✅ `bot.py` - Stage 2 prompt, Stage 3 exits, position sizing
- ✅ `MEAN_REVERSION_STRATEGY.md` - Full strategy guide
- ✅ `STRATEGY_MIGRATION_NOTES.md` - This file

## Files Created (not integrated yet)

- `autonomous_learning.py` - RL agents (ready to integrate)
- `autonomous_bot_integration.py` - Integration layer (ready to integrate)
- `AUTONOMOUS_LEARNING_GUIDE.md` - RL documentation
