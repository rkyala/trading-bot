# Bot Modification: Use Cached Schwab Signals

**Goal:** Bot reads from `schwab_signals.json` (updated every 10 min) instead of calling yfinance  
**Result:** No yfinance, 100% pure Schwab, super fast  
**Compatibility:** Drop-in replacement, no other bot code changes needed  

---

## How It Works

### Before (Current)
```
Bot runs every 30 min
  → Calls yfinance for each symbol (slow)
  → Gets rate limited sometimes
  → Calculates technicals
  → Finds signals
  → Executes trades
```

### After (New Architecture)
```
Signal Fetcher runs every 10 min
  → Calls Schwab API
  → Saves to schwab_signals.json
  
Bot runs every 30 min
  → Reads schwab_signals.json (cached)
  → Zero API calls
  → Super fast
  → Executes trades based on cached signals
```

---

## Modification 1: Update Imports

### File: `bot_production_final.py`

**BEFORE (Lines 1-20):**
```python
#!/usr/bin/python3
"""
Production Trading Bot - Local MCP Bridge with FULL POSITION MANAGEMENT
"""

import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List
import pandas as pd
import numpy as np
import yfinance as yf  # ← REMOVE THIS

# Import dynamic symbol fetcher
from symbol_fetcher import DynamicSymbolFetcher
```

**AFTER:**
```python
#!/usr/bin/python3
"""
Production Trading Bot - Local MCP Bridge with FULL POSITION MANAGEMENT
Uses Schwab API for market data (cached every 10 minutes)
"""

import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, List
import pandas as pd
import numpy as np
# import yfinance as yf  # Disabled - using Schwab cached signals

# Import dynamic symbol fetcher
from symbol_fetcher import DynamicSymbolFetcher
```

---

## Modification 2: Replace MarketDataFetcher

### File: `bot_production_final.py`

**BEFORE (Around line 267, ~150 lines of code):**
```python
class MarketDataFetcher:
    """Fetch and calculate technicals with safe division handling and caching"""

    # OPTIMIZATION: Cache recent fetches to reduce yfinance API load
    _cache = {}
    _cache_ttl_seconds = 300  # 5-minute cache for intraday data

    @staticmethod
    def get_technicals(symbol: str, backoff_ms: int = 50, use_cache: bool = True) -> Optional[Dict]:
        """
        Safe calculation of Stochastic (30m) and ADX (daily) with gap protection
        ...
        [150+ lines of yfinance code]
        ...
        """
```

**AFTER (Simple wrapper):**
```python
class MarketDataFetcher:
    """
    Fetch technicals from cached Schwab signals
    Updated every 10 minutes by schwab_signal_fetcher.py
    """

    _cached_signals = None
    _cached_timestamp = None

    @staticmethod
    def load_schwab_signals() -> Dict:
        """Load signals from schwab_signals.json"""
        signals_file = Path("schwab_signals.json")

        if not signals_file.exists():
            logger.warning("⚠️  schwab_signals.json not found - running signal fetcher first")
            # Optional: auto-run fetcher if signals missing
            return {"signals": []}

        try:
            data = json.loads(signals_file.read_text())
            return data
        except Exception as e:
            logger.error(f"❌ Failed to load Schwab signals: {e}")
            return {"signals": []}

    @staticmethod
    def get_technicals(symbol: str, use_cache: bool = True) -> Optional[Dict]:
        """
        Get technicals for symbol from cached Schwab signals
        Called by bot entry screening logic
        """
        # Load signals once per bot cycle
        signals_data = MarketDataFetcher.load_schwab_signals()
        
        # Check signal freshness
        if "fetched_at" in signals_data:
            last_fetch = datetime.fromisoformat(signals_data["timestamp"])
            age = (datetime.now() - last_fetch).total_seconds() / 60  # minutes
            
            if age > 30:
                logger.warning(f"⚠️  Schwab signals are {age:.0f} min old - may be stale")

        # Find symbol in signals
        for signal in signals_data.get("signals", []):
            if signal["symbol"] == symbol:
                # Return signal data in same format as yfinance
                logger.debug(f"📊 [{symbol}] Using cached Schwab signal")
                return {
                    "symbol": symbol,
                    "price": signal.get("price", 0),
                    "adx": signal.get("adx", 0),
                    "stoch_k": signal.get("stoch_k", 100),
                    "stoch_d": signal.get("stoch_d", 100),
                    "high_14": signal.get("high_14", 0),
                    "low_14": signal.get("low_14", 0),
                    "range_14": signal.get("high_14", 0) - signal.get("low_14", 0)
                }

        # Symbol not in latest signals (no entry signal for this cycle)
        logger.debug(f"⏭️  [{symbol}] Not in Schwab signals - no entry signal")
        return None
```

---

## Modification 3: Update Logging

### Optional: Show which data source is active

In the main cycle logging (around line 500):

**ADD:**
```python
logger.info("=" * 80)
logger.info("DATA SOURCE: Charles Schwab API (cached every 10 minutes)")
logger.info("=" * 80)
```

---

## Modification 4: Add Signal Freshness Check

### Optional: Skip trading if signals are stale

Add to `run_cycle()` method:

```python
def run_cycle(self):
    """Execute one trading cycle"""
    
    # Check Schwab signal freshness FIRST
    signals_file = Path("schwab_signals.json")
    if signals_file.exists():
        signals_data = json.loads(signals_file.read_text())
        last_fetch = datetime.fromisoformat(signals_data["timestamp"])
        age_minutes = (datetime.now() - last_fetch).total_seconds() / 60
        
        if age_minutes > 30:
            logger.warning(f"⚠️  Schwab signals are {age_minutes:.0f} min old - skipping trading")
            logger.info("   (Signal fetcher may be down - will retry next cycle)")
            return
    
    # Continue with normal cycle...
```

---

## Complete Example

Here's a minimal complete replacement for `MarketDataFetcher`:

```python
class MarketDataFetcher:
    """Reads cached Schwab signals (updated every 10 min by schwab_signal_fetcher.py)"""

    @staticmethod
    def get_technicals(symbol: str, use_cache: bool = True) -> Optional[Dict]:
        """
        Get technicals from cached Schwab signals
        No API calls - just reads JSON file
        Returns same format as yfinance for compatibility
        """
        try:
            signals_file = Path("schwab_signals.json")
            if not signals_file.exists():
                return None

            signals_data = json.loads(signals_file.read_text())

            # Find symbol in signals
            for signal in signals_data.get("signals", []):
                if signal["symbol"] == symbol:
                    return {
                        "symbol": symbol,
                        "price": float(signal.get("price", 0)),
                        "adx": float(signal.get("adx", 0)),
                        "stoch_k": float(signal.get("stoch_k", 100)),
                        "stoch_d": float(signal.get("stoch_d", 100)),
                        "high_14": float(signal.get("high_14", 0)),
                        "low_14": float(signal.get("low_14", 0)),
                        "range_14": float(signal.get("high_14", 0) - signal.get("low_14", 0))
                    }

            return None

        except Exception as e:
            logger.warning(f"⚠️  Could not get technicals for {symbol}: {e}")
            return None
```

---

## Testing

### Test 1: Manually verify bot reads signals

```bash
# Run signal fetcher first
/opt/homebrew/bin/python3.10 schwab_signal_fetcher.py

# Run bot - should read from schwab_signals.json
/opt/homebrew/bin/python3.10 bot_production_final.py

# Look for in logs:
# "Using cached Schwab signal"
# or
# "Not in Schwab signals - no entry signal"
```

### Test 2: Verify correct signals used

```bash
# Check what signals are cached
cat schwab_signals.json | jq '.signals[] | .symbol'
# Should show: MSFT, TSLA, etc.

# Run bot
/opt/homebrew/bin/python3.10 bot_production_final.py

# Verify bot found same signals in logs
grep "ENTRY SIGNAL" bot_production.log
# Should show: MSFT, TSLA
```

### Test 3: Check no yfinance calls

```bash
# Verify no yfinance errors in logs
grep -i "yfinance\|rate.*limit" bot_production.log
# Should be empty

# Verify no import errors
grep "ImportError" bot_production.log
# Should be empty
```

---

## Deployment Steps

### 1. Backup current bot
```bash
cp bot_production_final.py bot_production_final.py.backup
```

### 2. Make modifications
- Update imports (remove `import yfinance`)
- Replace `MarketDataFetcher` class
- Add signal freshness check (optional)

### 3. Test locally
```bash
/opt/homebrew/bin/python3.10 schwab_signal_fetcher.py  # Generate signals
/opt/homebrew/bin/python3.10 bot_production_final.py   # Run bot
```

### 4. Commit changes
```bash
git add bot_production_final.py
git commit -m "Switch bot to use cached Schwab signals (no yfinance)

- MarketDataFetcher now reads from schwab_signals.json
- Signals updated every 10 min by schwab_signal_fetcher.py
- Zero API calls from bot (only cached JSON reads)
- Removed yfinance dependency
- 100% pure Schwab data"
```

### 5. Deploy to Railway
```bash
git push origin feature/local-bot-production
```

---

## Advantages

✅ **No yfinance:** Completely removed, no rate limit conflicts  
✅ **Super fast:** Bot just reads JSON (milliseconds)  
✅ **Frequent updates:** Signals refreshed every 10 minutes  
✅ **Reliable:** Cached signals available even if Schwab briefly fails  
✅ **Observable:** Separate logs for fetcher vs bot  
✅ **Scalable:** Can add more data sources to same signals file  

---

## Rollback

If issues arise:

```bash
# Revert to previous version
git revert HEAD

# Or restore backup
cp bot_production_final.py.backup bot_production_final.py

# Redeploy
git push origin feature/local-bot-production
```

Takes ~2 minutes.

---

## Troubleshooting

### Bot says "schwab_signals.json not found"

**Solution:** Signal fetcher hasn't run yet
```bash
# Run it manually
/opt/homebrew/bin/python3.10 schwab_signal_fetcher.py

# Then run bot
/opt/homebrew/bin/python3.10 bot_production_final.py
```

### Bot says "Not in Schwab signals - no entry signal"

**Normal behavior** - symbol didn't meet entry criteria (ADX > 20, Stoch < 30)

### Bot says "Schwab signals are XX min old - skipping trading"

**Signals are stale** - Signal fetcher hasn't run in 30+ minutes
- Check if fetcher cron is active: `crontab -l`
- Check fetcher logs: `tail schwab_signal_fetcher.log`
- Manually run: `/opt/homebrew/bin/python3.10 schwab_signal_fetcher.py`

---

## Summary

This modification transforms the bot from:
- **Before:** Calling yfinance every 30 minutes → Rate limits, slow
- **After:** Reading cached JSON every 30 minutes → Fast, reliable, 100% Schwab

**Result:** Pure Schwab-powered trading with no external dependencies!

---

**Next:** Deploy cron jobs (see `SCHWAB_CRON_SETUP.md`)
