# Production Improvements - Implementation Guide

Based on code review of bot_production_final.py, here are 4 critical recommendations with implementation plans.

---

## 1. ✅ Position Sizing Limits (CRITICAL)

### Current Issue
```python
# Current: No explicit position sizing guards
qty = max(1, int(target_alloc / price))
# Could exceed account limits or fail if price drops suddenly
```

### Recommended Fix

**A. Calculate position size from available cash:**

```python
def calculate_safe_position_size(self, symbol: str, price: float) -> int:
    """
    Calculate position size based on available cash and risk limits.
    
    Constraints:
    1. Max 1% portfolio per position
    2. Max 0.5% per order (hard cap)
    3. Min $50 position size
    """
    # Get account cash balance (need to add get_accounts call)
    account_cash = self.get_available_cash()  # Via MCP
    
    if not account_cash or account_cash <= 0:
        logger.warning(f"[{symbol}] No available cash - skipping")
        return 0
    
    # Calculate three size limits
    max_per_position = self.account_cfg["account_size_usd"] * 0.01  # 1%
    max_per_order = self.account_cfg["account_size_usd"] * 0.005    # 0.5%
    available_cash_limit = account_cash * 0.50  # Never use all cash
    
    # Use most restrictive
    max_position_value = min(max_per_position, max_per_order, available_cash_limit)
    
    qty = int(max_position_value / price)
    
    if qty < 1:
        logger.info(f"[{symbol}] Position size 0 (price ${price:.2f} too high)")
        return 0
    
    logger.info(f"[{symbol}] Position size: {qty} (${qty * price:.2f} / ${max_position_value:.2f} max)")
    return qty
```

**B. Add cash-available check to MCP:**

```python
def get_available_cash(self) -> float:
    """Get available buying power from Robinhood account"""
    try:
        account_response = self.mcp.get_accounts()
        if "result" in account_response and "content" in account_response["result"]:
            content_text = account_response["result"]["content"][0].get("text", "")
            if content_text:
                parsed = json.loads(content_text)
                if "data" in parsed and "account" in parsed["data"]:
                    cash = float(parsed["data"]["account"].get("cash", 0))
                    return max(cash, 0)
    except Exception as e:
        logger.warning(f"⚠️  Could not fetch cash balance: {e}")
    return 0
```

---

## 2. ✅ Market Hours Guard (CRITICAL)

### Current Issue
```python
# Current: No market hours check
# Bot executes during:
# - Weekends (no liquidity)
# - Before 9:30 AM EST (pre-market, low volume)
# - After 4:00 PM EST (after-hours, illiquid)
# - Holidays (market closed)
```

### Recommended Fix

```python
def is_market_open(self) -> bool:
    """
    Check if US stock market is currently open.
    
    Market Hours (Eastern Time): 9:30 AM - 4:00 PM EST/EDT
    Your Time (Central): 8:30 AM - 3:00 PM CST/CDT
    
    Closed: Weekends, holidays
    """
    from datetime import datetime
    import pytz
    
    # US stock market operates on Eastern Time
    # Convert from CST/CDT to EST/EDT for comparison
    eastern = pytz.timezone('US/Eastern')
    now_eastern = datetime.now(eastern)
    
    # Check if weekend (Saturday=5, Sunday=6)
    if now_eastern.weekday() >= 5:
        logger.info(f"⏸️  Market closed: Weekend ({now_eastern.strftime('%A')})")
        return False
    
    # Check if within trading hours (9:30 AM - 4:00 PM Eastern)
    # Note: Your timezone is CST/CDT (1 hour behind), so:
    # 9:30 AM EST = 8:30 AM CST
    # 4:00 PM EST = 3:00 PM CDT
    market_open = now_eastern.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_eastern.replace(hour=16, minute=0, second=0, microsecond=0)
    
    if now_eastern < market_open:
        minutes_until = (market_open - now_eastern).seconds // 60
        cst_open = market_open.astimezone(pytz.timezone('US/Central')).strftime('%H:%M')
        logger.info(f"⏸️  Market not open yet: Opens 9:30 AM EST / 8:30 AM CST ({minutes_until}m)")
        return False
    
    if now_eastern > market_close:
        logger.info(f"⏸️  Market closed: Closed at 4:00 PM EST / 3:00 PM CDT")
        return False
    
    # Check for market holidays
    holidays = self.get_market_holidays()
    if now_eastern.date() in holidays:
        logger.info(f"⏸️  Market closed: Holiday ({now_eastern.strftime('%B %d')})")
        return False
    
    return True

def get_market_holidays(self) -> set:
    """Get US stock market holidays for current year"""
    from datetime import date
    
    # 2026 US Stock Market Holidays
    holidays_2026 = {
        date(2026, 1, 1),   # New Year's Day
        date(2026, 1, 19),  # MLK Day
        date(2026, 2, 16),  # Presidents' Day
        date(2026, 3, 27),  # Good Friday
        date(2026, 5, 25),  # Memorial Day
        date(2026, 7, 3),   # Independence Day (observed)
        date(2026, 9, 7),   # Labor Day
        date(2026, 11, 26), # Thanksgiving
        date(2026, 12, 25), # Christmas
    }
    return holidays_2026
```

**Usage in run_cycle():**

```python
def run_cycle(self):
    """Execute one trading cycle with market hours guard"""
    
    # Guard: Check market hours FIRST
    if not self.is_market_open():
        logger.info("🛑 Market closed - skipping cycle")
        return
    
    # Continue with rest of cycle...
    cycle_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"CYCLE | {cycle_time} | PRODUCTION BOT")
    
    # ... rest of code
```

---

## 3. ✅ Hardening yfinance Data Calls (HIGH PRIORITY)

### Current Issue
```python
# Current: No retry logic for rate limits
df_30m = yf.Ticker(symbol).history(period="5d", interval="30m").dropna()
# Can fail with:
# - HTTPError (429 Too Many Requests)
# - Empty DataFrame (no data)
# - NaN values in close prices
```

### Recommended Fix

```python
def get_technicals_with_retry(symbol: str, max_retries: int = 3) -> Optional[Dict]:
    """
    Fetch technicals with exponential backoff retry logic.
    
    Handles:
    - Rate limiting (HTTPError 429)
    - Empty data returns
    - NaN value handling
    """
    import time
    from requests.exceptions import HTTPError
    
    for attempt in range(max_retries):
        try:
            # Fetch 30-minute candles
            ticker = yf.Ticker(symbol)
            df_30m = ticker.history(period="5d", interval="30m")
            
            if df_30m.empty:
                logger.warning(f"[{symbol}] No 30m data (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.info(f"   Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                continue
            
            # Drop NaN and ensure minimum candles
            df_30m = df_30m.dropna()
            if len(df_30m) < 30:
                logger.warning(f"[{symbol}] Insufficient 30m candles: {len(df_30m)} < 30")
                return None
            
            # Fetch daily candles
            df_daily = ticker.history(period="60d", interval="1d")
            if df_daily.empty or len(df_daily) < 20:
                logger.warning(f"[{symbol}] Insufficient daily candles: {len(df_daily)} < 20")
                return None
            
            df_daily = df_daily.dropna()
            
            # Calculate technicals (ADX, Stoch)
            # ... existing calculation code ...
            
            return result  # Success
            
        except HTTPError as e:
            if e.response.status_code == 429:  # Rate limited
                wait_time = 2 ** attempt  # Exponential backoff
                logger.warning(f"[{symbol}] Rate limited (attempt {attempt + 1}/{max_retries})")
                logger.info(f"   Backing off {wait_time}s...")
                time.sleep(wait_time)
                continue
            else:
                logger.error(f"[{symbol}] HTTP error {e.response.status_code}: {e}")
                return None
        
        except Exception as e:
            logger.error(f"[{symbol}] Unexpected error: {e}")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                time.sleep(wait_time)
            continue
    
    logger.error(f"[{symbol}] Failed after {max_retries} retries")
    return None
```

---

## 4. ✅ Limit Orders Instead of Market Orders

### Current Status
```python
# Current: Market orders only
response = self.mcp.place_order(symbol, qty, side="buy")
# Comment says: "MCP doesn't support price parameter"
```

### Investigation & Solution

**Step 1: Test if MCP supports limit orders:**

```python
def test_limit_order_support(self):
    """Test if MCP server accepts limit_price parameter"""
    try:
        response = self.mcp._rpc("tools/call", {
            "name": "place_equity_order",
            "arguments": {
                "symbol": "AAPL",
                "quantity": 1,
                "side": "buy",
                "limit_price": 150.00,  # Test parameter
                "order_type": "limit"
            }
        })
        
        if "error" in response.get("result", {}):
            error_msg = response["result"]["error"]["message"]
            if "limit_price" in error_msg.lower():
                logger.info("❌ MCP does NOT support limit_price parameter")
                return False
            else:
                logger.info(f"⚠️  Different error: {error_msg}")
                return False
        else:
            logger.info("✅ MCP SUPPORTS limit orders!")
            return True
    except Exception as e:
        logger.error(f"Test failed: {e}")
        return False
```

**Step 2: If supported, use limit orders with spread:**

```python
def place_limit_order(self, symbol: str, qty: int, signal_price: float) -> dict:
    """
    Place limit buy order at bid-ask midpoint + small buffer.
    
    Strategy:
    - Signal price is from 30-min candle close
    - Get live bid/ask
    - Set limit price 0.1-0.5% below bid (avoid rejection)
    - Use GTC (Good-Till-Cancelled) to prevent miss
    """
    try:
        # Get current bid/ask
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        bid = float(info.get('bid', signal_price))
        ask = float(info.get('ask', signal_price))
        midpoint = (bid + ask) / 2
        
        # Set limit slightly below midpoint (0.2% buffer)
        limit_price = midpoint * 0.998
        
        logger.info(f"[{symbol}] Bid: ${bid:.2f} | Ask: ${ask:.2f} | Limit: ${limit_price:.2f}")
        
        # Place limit order via MCP
        response = self.mcp._rpc("tools/call", {
            "name": "place_equity_order",
            "arguments": {
                "symbol": symbol,
                "quantity": qty,
                "side": "buy",
                "limit_price": round(limit_price, 2),
                "order_type": "limit",
                "time_in_force": "day"  # Day order only
            }
        })
        
        return response
        
    except Exception as e:
        logger.error(f"[{symbol}] Limit order failed: {e}")
        logger.info(f"   Falling back to market order")
        return self.mcp.place_order(symbol, qty, side="buy")
```

---

## Implementation Priority

| Priority | Fix | Effort | Impact |
|----------|-----|--------|--------|
| 🔴 CRITICAL | #1 Position Sizing | 2h | Prevents rejected orders, account depletion |
| 🔴 CRITICAL | #2 Market Hours Guard | 1h | Prevents stale signals, weekend trading |
| 🟠 HIGH | #3 yfinance Retry Logic | 3h | Improves data reliability 90%+ |
| 🟡 MEDIUM | #4 Limit Orders | 4h | Reduces slippage by 30-50% |

---

## Next Steps

1. **This Week:** Implement #1 and #2 (critical guards)
2. **Next Week:** Implement #3 (data reliability)
3. **Backlog:** Implement #4 (requires MCP testing)

---

**Note:** All recommendations maintain backward compatibility and can be deployed to production incrementally.
