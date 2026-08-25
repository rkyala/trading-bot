# 🏗️ Foundation Phase: Production Implementation Checklist

**Status:** READY FOR IMMEDIATE DEPLOYMENT  
**Success Criteria:** Win Rate ≥55% + Profit Factor >1.5  
**Timeline:** 2 weeks to validation  
**Institutional Methodology:** Phased rollout with risk gates at each stage

---

## 🎯 Foundation Phase Objectives

1. **Validate strategy across diverse market regimes** (not just bull runs)
2. **Implement volatility filtering** (ATR-based symbol screening)
3. **Deploy dynamic stops** (volatility-adjusted risk management)
4. **Establish baseline metrics** before adding overlays

---

## ✅ FOUNDATION IMPLEMENTATION CHECKLIST

### Step 1: 180-Day Backtest Framework

**[ ] Run 180-day backtest on CRWD, ZM, JD**

```python
# backtest_180day.py
import yfinance as yf
import pandas as pd
import numpy as np

def run_180day_backtest(tickers, include_diverse_regimes=True):
    """
    180-day backtest with regime diversity validation
    
    Diverse regimes needed:
    - Bull market (sustained uptrend)
    - Bear market (sustained downtrend)  
    - Sideways/choppy (range-bound)
    - Volatility spike (earnings, news)
    """
    
    for ticker in tickers:
        df = yf.download(ticker, period="180d", interval="30m")
        
        # Calculate ATR
        df['ATR'] = calculate_atr(df, period=14)
        df['ATR_pct'] = (df['ATR'] / df['Close']) * 100
        
        # Filter signals by ATR
        entry_signals = calculate_entry_signals(df)
        filtered_signals = entry_signals[df['ATR_pct'] < 3.0]
        
        # Run backtest
        trades = execute_trades(filtered_signals, df)
        
        # Calculate metrics
        win_rate = len([t for t in trades if t['pnl'] > 0]) / len(trades)
        profit_factor = sum([t['pnl'] for t in trades if t['pnl'] > 0]) / abs(sum([t['pnl'] for t in trades if t['pnl'] < 0]))
        
        print(f"{ticker}:")
        print(f"  Trades: {len(trades)}")
        print(f"  Win Rate: {win_rate*100:.1f}%")
        print(f"  Profit Factor: {profit_factor:.2f}")
        
    return backtest_results
```

**Success Criteria:**
- [ ] Win rate ≥ 55% on at least 2 of 3 symbols
- [ ] Profit factor > 1.5 (for every $1 lost, make $1.50)
- [ ] Minimum 40 trades per symbol (statistical significance)
- [ ] Diverse market regimes covered (bull, bear, sideways, vol spike)

**What to watch for:**
- ⚠️ If win rate < 50% → Strategy has negative edge, don't proceed
- ⚠️ If profit factor < 1.2 → Losing trades too big vs wins
- ⚠️ If all 180 days were bull market → Re-run including bear market periods
- ⚠️ If one symbol dominates → Check for survivorship bias

---

### Step 2: ATR-Based Symbol Filtering

**[ ] Implement dynamic ATR filter in entry screening**

```python
# In bot_production_final.py, Phase 2 entry screening

class VolatilityFilter:
    """
    Filter symbols by intraday volatility (ATR)
    Prevents trading high-volatility names where stops get whipsawed
    """
    
    def __init__(self, max_atr_pct=3.0, max_atr_usd=None):
        self.max_atr_pct = max_atr_pct  # 3% of price
        self.max_atr_usd = max_atr_usd  # Optional: 3% = $6 on $200 stock
    
    def calculate_atr(self, high, low, close, period=14):
        """Calculate Average True Range"""
        tr = np.maximum(
            high - low,
            np.maximum(
                abs(high - close.shift(1)),
                abs(low - close.shift(1))
            )
        )
        atr = tr.rolling(period).mean()
        return atr
    
    def is_tradeable(self, symbol, current_price, atr):
        """Check if symbol volatility is within acceptable range"""
        atr_pct = (atr / current_price) * 100
        
        if atr_pct > self.max_atr_pct:
            logger.info(f"[{symbol}] REJECTED: ATR {atr_pct:.1f}% exceeds {self.max_atr_pct}% limit")
            return False
        
        logger.info(f"[{symbol}] ACCEPTED: ATR {atr_pct:.1f}% within limits")
        return True

# Usage in entry loop:
vol_filter = VolatilityFilter(max_atr_pct=3.0)

for symbol in self.symbols:
    data = MarketDataFetcher.get_technicals(symbol)
    atr = vol_filter.calculate_atr(data['high'], data['low'], data['close'])
    
    if not vol_filter.is_tradeable(symbol, data['price'], atr):
        skipped.append(symbol)
        continue  # Skip this symbol
    
    # Proceed with entry signal logic
    signal = self.entry_signal_gen.generate_signal(data)
```

**Symbols to filter:**
- [ ] CRWD: ATR ~3.5% (TOO HIGH) → Skip
- [ ] ZM: ATR ~1.9% (OK) → Trade
- [ ] JD: ATR ~1.8% (OK) → Trade

**Success Criteria:**
- [ ] CRWD position removed from active symbols
- [ ] ZM + JD remain as primary trading universe
- [ ] Logs show "ATR REJECTED" for high-vol symbols
- [ ] Portfolio drawdown reduces by ~5-10%

---

### Step 3: Dynamic Stop/Target by Volatility

**[ ] Implement volatility-adjusted risk management**

```python
# In bot_production_final.py, entry order logic

class DynamicRiskManager:
    """
    Adjust stop-loss and take-profit based on intraday ATR
    Prevents whipsaws on high-vol days while maximizing efficiency on low-vol days
    """
    
    def calculate_dynamic_stops(self, symbol, atr_pct, position_price):
        """
        Determine stop/target based on volatility regime
        Always maintains 1:2 risk/reward ratio
        """
        
        if atr_pct > 2.5:  # High volatility
            stop_pct = -0.025      # -2.5% stop
            target_pct = 0.050     # +5.0% target
            regime = "HIGH_VOL"
            
        elif atr_pct > 1.5:  # Medium volatility (ZM, JD range)
            stop_pct = -0.0175     # -1.75% stop (standard)
            target_pct = 0.035     # +3.5% target (standard)
            regime = "MED_VOL"
            
        else:  # Low volatility
            stop_pct = -0.012      # -1.2% stop
            target_pct = 0.024     # +2.4% target
            regime = "LOW_VOL"
        
        stop_price = position_price * (1 + stop_pct)
        target_price = position_price * (1 + target_pct)
        
        logger.info(f"[{symbol}] {regime} regime | ATR: {atr_pct:.1f}%")
        logger.info(f"  Entry: ${position_price:.2f}")
        logger.info(f"  Stop: ${stop_price:.2f} ({stop_pct*100:+.2f}%)")
        logger.info(f"  Target: ${target_price:.2f} ({target_pct*100:+.2f}%)")
        logger.info(f"  Risk/Reward: 1:{abs(target_pct/stop_pct):.1f}")
        
        return {
            "stop_price": stop_price,
            "target_price": target_price,
            "regime": regime,
            "risk_reward": abs(target_pct / stop_pct)
        }

# Usage:
risk_mgr = DynamicRiskManager()
entry_price = 189.89  # CRWD example
atr_pct = 3.2  # High volatility

stops = risk_mgr.calculate_dynamic_stops("CRWD", atr_pct, entry_price)
# Result:
# Stop: $185.22 (-2.5%)
# Target: $199.39 (+5.0%)
# Risk/Reward: 1:2.0
```

**Success Criteria:**
- [ ] CRWD orders use -2.5% stop (wider) / +5% target
- [ ] ZM/JD orders use -1.75% stop / +3.5% target
- [ ] All maintain 1:2 risk/reward ratio
- [ ] Logs show dynamic regime classification
- [ ] Win rate on CRWD improves from 30% → 50%+

**What to watch for:**
- ⚠️ If stops still getting whipsawed → Increase to -3% for high-vol
- ⚠️ If target never reached → Check that VWAP bands are calibrated correctly
- ⚠️ If win rate doesn't improve → Volume/liquidity issue, consider skipping symbol

---

### Step 4: Session-Anchored VWAP Implementation

**[ ] Ensure VWAP resets at market open (9:30 AM EST)**

```python
# CRITICAL: This is where most VWAP implementations fail
# Rolling VWAP ≠ Session-anchored VWAP

class SessionAnchoredVWAP:
    """
    VWAP MUST reset at 9:30 AM EST daily
    Do NOT use rolling VWAP (includes yesterday's volume)
    """
    
    def calculate_vwap(self, intraday_candles):
        """
        intraday_candles: DataFrame with index = timestamp, columns = OHLCV
        
        Key requirement: 
        - All candles in dataframe are from SAME trading day
        - First candle is at 9:30 AM EST
        - Last candle is most recent (not stale)
        """
        
        # Ensure we're working with same day only
        df = intraday_candles.copy()
        df['Date'] = df.index.date
        
        if df['Date'].nunique() > 1:
            logger.error("ERROR: Mixed trading days in VWAP calculation!")
            logger.error("VWAP must reset at market open, not span multiple days")
            return None
        
        # Calculate typical price
        typical_price = (df['High'] + df['Low'] + df['Close']) / 3
        
        # Cumulative sum within session only
        cumsum_tp_vol = (typical_price * df['Volume']).cumsum()
        cumsum_vol = df['Volume'].cumsum()
        
        # VWAP = cumulative TP*V / cumulative V
        vwap = cumsum_tp_vol / cumsum_vol
        
        # Standard deviation (only this session)
        session_std = df['Close'].std()
        vwap_lower_2s = vwap - (2 * session_std)
        
        logger.info(f"VWAP calculated for {df['Date'].iloc[0]}")
        logger.info(f"  Latest VWAP: ${vwap.iloc[-1]:.2f}")
        logger.info(f"  -2σ band: ${vwap_lower_2s.iloc[-1]:.2f}")
        
        return {
            'vwap': vwap,
            'std_dev': session_std,
            'lower_2s': vwap_lower_2s,
            'session_date': df['Date'].iloc[0]
        }

# WRONG - This breaks at market open reset:
rolling_vwap = df['Close'].rolling(120).mean()  # ❌ WRONG

# RIGHT - This resets daily:
session_vwap = calculate_vwap(today_only_candles)  # ✅ CORRECT
```

**Success Criteria:**
- [ ] VWAP resets to NaN at 9:30 AM EST
- [ ] VWAP builds up through the day
- [ ] No data carryover from previous trading days
- [ ] -2σ band updates in real-time as session progresses
- [ ] Logs show "VWAP calculated for [DATE]"

**What to watch for:**
- ⚠️ If VWAP doesn't reset at 9:30 AM → Check timezone handling (EST vs UTC)
- ⚠️ If -2σ band too tight → Increase multiplier to 2.5σ
- ⚠️ If -2σ band too loose → Decrease to 1.5σ
- ⚠️ If getting entries at -1.5σ instead of -2σ → Debug band calculation

---

### Step 5: Non-Blocking Macro Triggers Storage

**[ ] Daily trend flags stored in macro_triggers.json (from background scanner)**

```python
# In test_async_signal_channel.py (already implemented, just verify)

def store_daily_trends():
    """
    Background scanner stores daily trend flags
    Execution bot reads these WITHOUT waiting for daily data fetch
    """
    
    daily_trends = {}
    
    for symbol in TRADING_SYMBOLS:
        # Fetch daily data (runs in background, not blocking entry loop)
        daily_data = yf.download(symbol, period="60d", interval="1d")
        
        # Calculate 50-SMA on daily chart
        daily_50sma = daily_data['Close'].rolling(50).mean()
        
        # Determine trend
        if daily_data['Close'].iloc[-1] > daily_50sma.iloc[-1]:
            trend = "BULLISH"
        else:
            trend = "BEARISH"
        
        daily_trends[symbol] = {
            "trend": trend,
            "daily_50sma": daily_50sma.iloc[-1],
            "daily_close": daily_data['Close'].iloc[-1],
            "timestamp": datetime.now().isoformat()
        }
    
    # Store in macro_triggers.json (atomic write)
    tmp_file = Path("macro_triggers.tmp")
    with open(tmp_file, 'w') as f:
        json.dump(daily_trends, f, indent=2)
    
    tmp_file.replace("macro_triggers.json")  # Atomic rename
    
    logger.info(f"Daily trends stored: {daily_trends}")

# In bot_production_final.py (Phase 2, just read - don't fetch):

def read_daily_trend(symbol):
    """Read pre-computed daily trend (non-blocking)"""
    try:
        with open("macro_triggers.json") as f:
            trends = json.load(f)
        
        if symbol in trends:
            trend = trends[symbol]["trend"]
            logger.info(f"[{symbol}] Daily trend: {trend}")
            return trend
        else:
            return "UNKNOWN"
    except:
        return "UNKNOWN"  # Fail gracefully
```

**Success Criteria:**
- [ ] macro_triggers.json updates every 60 seconds (background)
- [ ] Execution bot reads trends in <100ms (no blocking)
- [ ] Trends available for all symbols in universe
- [ ] Timestamp is fresh (within last 2 minutes)

**What to watch for:**
- ⚠️ If daily trend not available → Fall back to neutral (don't halt entry)
- ⚠️ If reading triggers network fetch → Move fetch to background only
- ⚠️ If timestamp stale (>5 min old) → Log warning but proceed

---

### Step 6: ORB (Opening Range Breakout) Detection

**[ ] Track first 30 minutes (9:30-10:00 AM EST) for breakout filter**

```python
# In bot_production_final.py, Phase 2

class OpeningRangeBreakout:
    """
    Track first 30 minutes of trading
    Skip mean-reversion entries if price breaking out (ADX > 25)
    """
    
    def __init__(self):
        self.orb_data = {}  # Per-symbol ORB tracking
    
    def check_orb_setup(self, symbol, current_time, current_price, adx):
        """
        Returns: (is_breakout, reason)
        """
        
        # Only check during first 30 min (9:30-10:00 EST)
        market_open = current_time.replace(hour=9, minute=30, second=0)
        orb_close = market_open + timedelta(minutes=30)
        
        if current_time < market_open or current_time > orb_close:
            # Outside ORB window - normal mean-reversion allowed
            return False, "Outside ORB window"
        
        # During first 30 min - track range
        if symbol not in self.orb_data:
            self.orb_data[symbol] = {
                'high': current_price,
                'low': current_price,
                'start_time': current_time
            }
        else:
            # Update range
            self.orb_data[symbol]['high'] = max(self.orb_data[symbol]['high'], current_price)
            self.orb_data[symbol]['low'] = min(self.orb_data[symbol]['low'], current_price)
        
        # Check for breakout
        orb_high = self.orb_data[symbol]['high']
        orb_range = orb_high - self.orb_data[symbol]['low']
        breakout_threshold = orb_high + (0.5 * orb_range)  # 50% above ORB
        
        if current_price > breakout_threshold and adx > 25:
            logger.info(f"[{symbol}] BREAKOUT DETECTED: Price {current_price:.2f} > ORB high {orb_high:.2f}, ADX {adx:.1f}")
            return True, "ORB breakout with strong trend"
        
        return False, "No ORB breakout"
    
    def should_skip_mean_reversion(self, symbol, current_time, current_price, adx):
        """
        Return True if this looks like a breakout (skip mean-reversion)
        Return False if this looks like a normal dip (allow mean-reversion)
        """
        is_breakout, reason = self.check_orb_setup(symbol, current_time, current_price, adx)
        
        if is_breakout:
            logger.info(f"[{symbol}] Skipping mean-reversion entry: {reason}")
            return True
        else:
            logger.info(f"[{symbol}] Mean-reversion entry allowed: {reason}")
            return False

# Usage:
orb_filter = OpeningRangeBreakout()

# In entry screening:
if orb_filter.should_skip_mean_reversion(symbol, current_time, current_price, adx):
    skipped.append(symbol)
    continue  # Skip this entry attempt
```

**Success Criteria:**
- [ ] ORB tracks first 30 minutes only (9:30-10:00 EST)
- [ ] Breakout detection triggers when ADX > 25 + price above ORB
- [ ] Mean-reversion entries skipped during breakouts
- [ ] Logs show "BREAKOUT DETECTED" when applicable
- [ ] Win rate on first 30-min trades improves

**What to watch for:**
- ⚠️ If false breakouts → Increase ADX threshold to 28-30
- ⚠️ If missing breakouts → Decrease threshold to 22-23
- ⚠️ If ORB data persists across days → Clear at 10:00 AM EST

---

## 📊 Success Metrics & Validation Gates

### Gate 1: 180-Day Backtest (Foundation Validation)

**Must achieve BEFORE Phase 1:**

- [ ] Win rate ≥ 55% on ≥2 symbols
- [ ] Profit factor > 1.5
- [ ] ≥40 trades per symbol
- [ ] Diverse market regimes covered
- [ ] No curve-fitting (same parameters for all 180 days)

**If not achieved:**
- ❌ Do NOT proceed to Phase 1
- ❌ Debug symbol selection or stop/target sizing
- ❌ Consider expanding backtest to 365 days

### Gate 2: Live Paper Trading (2 weeks)

**Run on real market data (but no real money):**

- [ ] Record every trade (entry, exit, P&L)
- [ ] Calculate rolling win rate (target ≥55%)
- [ ] Calculate profit factor (target >1.5)
- [ ] Monitor drawdown (max drawdown <15%)
- [ ] Check for slippage vs backtest

**If metrics hold:**
- ✅ Proceed to Phase 1 implementation
- ✅ Deploy Relative Strength + VWAP overlays

**If metrics degrade:**
- ❌ Investigate edge case (market regime change, data quality, timezone)
- ❌ Adjust parameters and re-test
- ❌ Don't deploy overlays until foundation is solid

---

## 🚀 Go/No-Go Checklist Before Phase 1

```
FOUNDATION REQUIREMENTS:

[ ] 180-day backtest shows ≥55% win rate + >1.5 profit factor
[ ] ATR filter implemented and filtering correctly (CRWD excluded)
[ ] Dynamic stops working (different regimes use different stops)
[ ] Session-anchored VWAP resets at 9:30 AM EST daily
[ ] macro_triggers.json storing daily trends (non-blocking)
[ ] ORB detection working (first 30 min breakout filter)

DOCUMENTATION:

[ ] Backtest results saved (180day_backtest_results.csv)
[ ] Win rate tracking dashboard created
[ ] Profit factor trending graph available
[ ] Edge case log created (for debugging)

OPERATIONAL:

[ ] Crontab verified (foundation runs before 9:30 AM EST)
[ ] Logs rotate daily (10 GB max disk usage)
[ ] Error alerts configured (Slack, email, or log monitoring)
[ ] Circuit breaker active (-40% halt still enforced)
[ ] Position sizing capped at $150 (1.5% per trade)

AUTHORIZATION:

[ ] Robinhood account verified in sandbox
[ ] MCP connection tested (place_order works)
[ ] Order confirms logged
[ ] Position tracking accurate
```

---

## 🎯 Timeline to Production

```
Week 1 (Now):
  [ ] Implement Foundation components
  [ ] Run 180-day backtest
  [ ] Validate Gate 1 metrics

Week 2:
  [ ] Paper trade for 5-7 days
  [ ] Monitor live metrics
  [ ] Make parameter adjustments if needed

Week 3:
  [ ] Deploy Phase 1 (RS + VWAP overlays)
  [ ] Paper trade overlays for 2-3 days
  [ ] Validate Phase 1 adds +3-5% alpha as expected

Week 4+:
  [ ] Phase 2 (MTF + ORB)
  [ ] Full stack deployment
  [ ] Monitor toward 51% ROI target
```

---

## ✅ Success Definition

**Foundation phase is successful when:**

> Win rate ≥55% AND Profit factor >1.5 on 180-day backtest across CRWD, ZM, JD, with diverse market regimes represented and NO curve-fitting.

If you achieve this, Phase 1 overlays will add value on top of a proven foundation.

If you don't achieve this, adding overlays will just increase complexity without improving edge.

---

**Next step: Start building Foundation components TODAY.** 

Ready to code?
