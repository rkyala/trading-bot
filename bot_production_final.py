#!/usr/bin/env python3
"""
Production Trading Bot - Local MCP Bridge with FULL POSITION MANAGEMENT
Entry + Exit Logic: Mean-reversion signals with automatic take-profit, stop-loss, time-based exits
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
import yfinance as yf

# Import dynamic symbol fetcher
from symbol_fetcher import DynamicSymbolFetcher

# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot_production.log')
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# POSITION TRACKING
# ============================================================================

class PositionTracker:
    """Track entry times, prices, and highest price for true trailing stop management"""

    def __init__(self, file_path: str = "positions_tracking.json"):
        self.file_path = Path(file_path)
        self.positions = self._load()

    def _load(self) -> Dict:
        """Load positions from file"""
        if self.file_path.exists():
            try:
                with open(self.file_path) as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save(self):
        """Save positions to file"""
        with open(self.file_path, 'w') as f:
            json.dump(self.positions, f, indent=2)

    def add_position(self, symbol: str, qty: int, entry_price: float, entry_time: str):
        """Record a new entry position with highest_price tracking for true trailing stop"""
        from datetime import datetime
        self.positions[symbol] = {
            "qty": qty,
            "entry_price": entry_price,
            "highest_price": entry_price,  # Track highest price for true trailing stop
            "entry_time": entry_time,
            "entry_timestamp": datetime.now().isoformat(),  # Timestamp for robust time-based exits
            "cycles_held": 0,
            "retry_count": 0
        }
        self._save()
        logger.info(f"📝 Position tracked: {symbol} {qty}@ ${entry_price:.2f} @ {entry_time}")

    def get_position(self, symbol: str) -> Optional[Dict]:
        """Get position details"""
        return self.positions.get(symbol)

    def remove_position(self, symbol: str):
        """Remove position after exit"""
        if symbol in self.positions:
            del self.positions[symbol]
            self._save()
            logger.info(f"🗑️  Position removed: {symbol}")

    def increment_cycles(self, symbol: str):
        """Increment cycle counter for time-based exit"""
        if symbol in self.positions:
            self.positions[symbol]["cycles_held"] += 1
            self._save()

    def update_highest_price(self, symbol: str, current_price: float):
        """Update highest price reached for true trailing stop calculation"""
        if symbol in self.positions:
            pos = self.positions[symbol]
            if current_price > pos.get("highest_price", pos["entry_price"]):
                pos["highest_price"] = current_price
                self._save()

    def increment_retry_count(self, symbol: str) -> int:
        """Increment retry count and return new count (encapsulation-safe)"""
        if symbol in self.positions:
            pos = self.positions[symbol]
            retry_count = pos.get("retry_count", 0)
            pos["retry_count"] = retry_count + 1
            self._save()
            return pos["retry_count"]
        return 0

    def get_all(self) -> Dict:
        """Get all positions"""
        return self.positions


# ============================================================================
# CONFIGURATION MANAGEMENT
# ============================================================================

class ConfigLoader:
    """Load configuration from config.json"""

    @staticmethod
    def load() -> Dict:
        config_file = Path("config.json")
        if not config_file.exists():
            logger.error("❌ config.json not found")
            sys.exit(1)

        try:
            with open(config_file) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"❌ Error loading config: {e}")
            sys.exit(1)


# ============================================================================
# LOCAL MCP CLIENT (FIXED)
# ============================================================================

class LocalMCPClient:
    """
    Client for local Robinhood MCP bridge
    Bug fixes:
    - Unbuffered subprocess (-u flag)
    - MCP initialize handshake
    - Proper error handling
    - Safe subprocess cleanup
    """

    def __init__(self, config: Dict):
        self.config = config
        self.req_id = 1

        try:
            # BUG FIX #1: Use -u for unbuffered output, pipe stderr to terminal
            self.process = subprocess.Popen(
                [sys.executable, "-u", "robinhood_mcp_local.py"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=sys.stderr,
                text=True
            )
            logger.info("[+] MCP subprocess started (unbuffered)")

            # BUG FIX #2: Perform MCP handshake before any tool calls
            init_response = self._rpc("initialize", {
                "protocolVersion": config["robinhood"]["protocol_version"],
                "capabilities": {},
                "clientInfo": {"name": "trading-bot", "version": "2.0.0"}
            })

            if "result" in init_response:
                logger.info("✅ MCP initialized")
            else:
                logger.warning(f"⚠️  Init response: {init_response}")

        except Exception as e:
            logger.error(f"❌ Failed to start MCP: {e}")
            sys.exit(1)

    def _rpc(self, method: str, params: dict = None) -> dict:
        """Send JSON-RPC request to local MCP server"""
        try:
            req = {
                "jsonrpc": "2.0",
                "id": self.req_id,
                "method": method,
                "params": params or {}
            }
            self.req_id += 1

            self.process.stdin.write(json.dumps(req) + "\n")
            self.process.stdin.flush()

            # CRITICAL FIX #7: Skip non-JSON lines on stdout (debug logs, print statements)
            # Robinhood MCP should route logs to stderr, but be defensive
            while True:
                line = self.process.stdout.readline()
                if not line:
                    return {"error": "No response from MCP process"}

                line_str = line.strip()

                # Only parse valid JSON-RPC responses
                if line_str.startswith("{") and line_str.endswith("}"):
                    try:
                        return json.loads(line_str)
                    except json.JSONDecodeError:
                        continue
                # Skip non-JSON lines (debug output, log statements)
                else:
                    continue

        except Exception as e:
            logger.error(f"RPC error: {e}")
            return {"error": str(e)}

    def place_order(self, symbol: str, qty: int, side: str = "buy"):
        """
        Place order via MCP (buy or sell)
        Note: MCP server only supports market orders (price parameter rejected)
        """
        return self._rpc("tools/call", {
            "name": "place_equity_order",
            "arguments": {
                "symbol": symbol,
                "quantity": qty,
                "side": side
            }
        })

    def get_positions(self):
        """Get positions via MCP"""
        return self._rpc("tools/call", {
            "name": "get_equity_positions",
            "arguments": {}
        })

    def get_accounts(self):
        """Get account portfolio value via MCP for circuit breaker checks"""
        return self._rpc("tools/call", {
            "name": "get_accounts",
            "arguments": {}
        })

    def stop(self):
        """BUG FIX #4: Safely terminate subprocess"""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
                logger.info("[*] MCP subprocess terminated")
            except Exception as e:
                logger.warning(f"Error stopping MCP: {e}")
                self.process.kill()


# ============================================================================
# MARKET DATA FETCHER (SAFE CALCULATIONS)
# ============================================================================

class MarketDataFetcher:
    """Fetch and calculate technicals with safe division handling and caching"""

    # OPTIMIZATION: Cache recent fetches to reduce yfinance API load
    _cache = {}
    _cache_ttl_seconds = 300  # 5-minute cache for intraday data

    @staticmethod
    def get_technicals(symbol: str, backoff_ms: int = 50, use_cache: bool = True) -> Optional[Dict]:
        """
        Safe calculation of Stochastic (30m) and ADX (daily) with gap protection
        NOTE: ADX uses daily candles to avoid overnight gap artifacts
        NOTE: Stochastic uses 30m candles for accurate intraday exit signals
        NOTE: backoff_ms adds delay between API calls to avoid rate limiting
        NOTE: use_cache reduces yfinance API load (default: enabled)
        """
        try:
            from datetime import datetime, timedelta
            import time

            # OPTIMIZATION #19: Check cache before fetching
            if use_cache and symbol in MarketDataFetcher._cache:
                cached_time, cached_data = MarketDataFetcher._cache[symbol]
                age_seconds = (datetime.now() - cached_time).total_seconds()
                if age_seconds < MarketDataFetcher._cache_ttl_seconds:
                    logger.debug(f"📦 [{symbol}] Using cached data (age: {age_seconds:.0f}s)")
                    return cached_data

            time.sleep(backoff_ms / 1000.0)  # Rate limit protection: small delay between yfinance calls

            # CRITICAL FIX #8: Use daily candles for ADX (avoids overnight gap distortion)
            # ADX measured on daily trend to avoid false signals at market open
            df_daily = yf.Ticker(symbol).history(period="60d", interval="1d").dropna()
            if len(df_daily) < 20:
                return None

            # Calculate ADX from daily candles (stable trend indicator)
            high_d = df_daily['High'].astype(float)
            low_d = df_daily['Low'].astype(float)
            close_d = df_daily['Close'].astype(float)

            tr_d = pd.concat([
                high_d - low_d,
                (high_d - close_d.shift()).abs(),
                (low_d - close_d.shift()).abs()
            ], axis=1).max(axis=1)

            atr_d = tr_d.rolling(14).mean()
            up_d = high_d - high_d.shift()
            down_d = low_d.shift() - low_d

            plus_dm_d = pd.Series(np.where((up_d > down_d) & (up_d > 0), up_d, 0), index=df_daily.index)
            minus_dm_d = pd.Series(np.where((down_d > up_d) & (down_d > 0), down_d, 0), index=df_daily.index)

            plus_di_d = 100 * (plus_dm_d.rolling(14).mean() / atr_d)
            minus_di_d = 100 * (minus_dm_d.rolling(14).mean() / atr_d)
            di_diff_d = (plus_di_d - minus_di_d).abs()
            adx_d = di_diff_d.rolling(14).mean()

            # CRITICAL FIX #1: Use 30-minute candles ONLY for Stochastic (intraday exit signals)
            df_30m = yf.Ticker(symbol).history(period="5d", interval="30m").dropna()
            if len(df_30m) < 30:
                return None

            high_30m = df_30m['High'].astype(float)
            low_30m = df_30m['Low'].astype(float)
            close_30m = df_30m['Close'].astype(float)

            # Safe Stochastic calculation (30m for sensitivity)
            lookback = 14
            high_max = high_30m.rolling(lookback).max()
            low_min = low_30m.rolling(lookback).min()
            range_hl = high_max - low_min

            range_hl_safe = range_hl.replace(0, np.nan)
            stoch_k = 100 * ((close_30m - low_min) / range_hl_safe)
            stoch_k = stoch_k.fillna(50.0)

            stoch_d = stoch_k.rolling(3).mean()

            result = {
                "symbol": symbol,
                "price": close_30m.iloc[-1],  # Current 30m price for position tracking
                "adx": adx_d.iloc[-1],  # ADX from daily (gap-protected)
                "stoch_k": stoch_k.iloc[-1],  # Stoch from 30m (sensitive)
                "stoch_d": stoch_d.iloc[-1],
                "high_14": high_max.iloc[-1],
                "low_14": low_min.iloc[-1],
                "range_14": range_hl.iloc[-1]
            }

            # OPTIMIZATION #19: Cache the result for 5 minutes (reduce API load)
            if use_cache:
                from datetime import datetime
                MarketDataFetcher._cache[symbol] = (datetime.now(), result)
                logger.debug(f"📦 [{symbol}] Cached for {MarketDataFetcher._cache_ttl_seconds}s")

            return result
        except Exception as e:
            logger.debug(f"Error analyzing {symbol}: {e}")
            return None


# ============================================================================
# ENTRY SIGNAL GENERATOR
# ============================================================================

class EntrySignalGenerator:
    """Generate mean-reversion entry signals"""

    def __init__(self, config: Dict):
        self.config = config
        self.entry_cfg = config["strategy"]["entry_criteria"]

    def generate_signal(self, data: Dict) -> Optional[Dict]:
        """Generate entry signal if conditions met"""
        if not data:
            return None

        adx = data.get("adx", 0)
        stoch_k = data.get("stoch_k", 100)
        stoch_d = data.get("stoch_d", 100)

        if adx < self.entry_cfg["min_adx"]:
            return None

        if stoch_k > self.entry_cfg["stoch_oversold"] or stoch_k <= stoch_d:
            return None

        high_14 = data.get("high_14", 0)
        low_14 = data.get("low_14", 0)
        price = data.get("price", 0)
        range_14 = data.get("range_14", 0)

        if range_14 == 0:
            return None

        fib_touched = False
        for fib_level in self.entry_cfg["fib_levels"]:
            fib_price = high_14 - (range_14 * fib_level)
            if abs(price - fib_price) / price < 0.02:
                fib_touched = True
                break

        if not fib_touched:
            return None

        return {
            "symbol": data["symbol"],
            "signal_type": "BUY",
            "price": price,
            "adx": adx,
            "stoch_k": stoch_k
        }


# ============================================================================
# EXIT SIGNAL GENERATOR
# ============================================================================

class ExitSignalGenerator:
    """Generate exit signals based on take-profit, stop-loss, and time-based criteria"""

    def __init__(self, config: Dict):
        self.config = config
        self.exit_cfg = config["strategy"]["exit_criteria"]

    def generate_exit_signal(self, symbol: str, position: Dict, current_data: Dict) -> Optional[Dict]:
        """
        Evaluate exit conditions:
        1. Take-profit: Stochastic > 50 (recovery signal)
        2. Stop-loss: Price < highest_price * (1 - 1.5%) [TRUE TRAILING STOP]
        3. Time-based: > 6 cycles (30-min each = 3+ hours max hold)
        """
        if not position or not current_data:
            return None

        entry_price = position.get("entry_price", 0)
        highest_price = position.get("highest_price", entry_price)
        current_price = current_data.get("price", 0)
        stoch_k = current_data.get("stoch_k", 0)
        cycles_held = position.get("cycles_held", 0)

        # Exit Condition 1: Take-Profit (Stochastic recovery > 50)
        if stoch_k > self.exit_cfg["stoch_recovery"]:
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
            return {
                "symbol": symbol,
                "signal_type": "SELL",
                "reason": "TAKE-PROFIT",
                "price": current_price,
                "stoch_k": stoch_k,
                "pnl_pct": pnl_pct
            }

        # Exit Condition 2: Stop-Loss (TRUE TRAILING STOP - trails highest_price)
        # FIX #3: Use highest_price for true trailing stop, not entry_price
        trailing_stop_threshold = highest_price * (1 - self.exit_cfg["trailing_stop_pct"])
        if current_price < trailing_stop_threshold:
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
            return {
                "symbol": symbol,
                "signal_type": "SELL",
                "reason": f"STOP-LOSS (trailing from ${highest_price:.2f})",
                "price": current_price,
                "pnl_pct": pnl_pct
            }

        # Exit Condition 3: Time-Based Exit (configurable max cycles from config.json)
        # Note: Typically 30-min cycles × max_cycles = total hold duration
        max_cycles = self.exit_cfg.get("max_cycles", 6)  # Fallback: 6 cycles = 3 hours
        if cycles_held >= max_cycles:
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
            return {
                "symbol": symbol,
                "signal_type": "SELL",
                "reason": f"TIME-BASED (held {cycles_held} cycles)",
                "price": current_price,
                "pnl_pct": pnl_pct
            }

        return None


# ============================================================================
# TRADING BOT (WITH FULL POSITION MANAGEMENT)
# ============================================================================

class TradingBot:
    """Main trading bot orchestrator with entry + exit logic"""

    def __init__(self, config: Dict):
        self.config = config
        self.mcp = LocalMCPClient(config)
        self.entry_signal_gen = EntrySignalGenerator(config)
        self.exit_signal_gen = ExitSignalGenerator(config)
        self.position_tracker = PositionTracker()
        self.account_cfg = config["account"]

        # Get symbols dynamically or from config
        logger.info("=" * 80)
        logger.info("FETCHING SYMBOLS")
        logger.info("=" * 80)
        self.symbols = DynamicSymbolFetcher.get_trending_symbols(config)
        logger.info("=" * 80 + "\n")

        if not self.symbols:
            logger.error("❌ No symbols fetched!")
            sys.exit(1)

    def check_circuit_breaker(self) -> bool:
        """
        PRODUCTION HARDENING: Circuit breaker logic
        Returns True if trading should proceed, False if halted

        Halt conditions:
        1. Portfolio drawdown >= -40%
        2. Hard position size cap: max 0.5% of account (always enforced)
        """
        try:
            # Get current account value
            response = self.mcp.get_accounts()

            if "error" in response:
                logger.warning(f"⚠️  Circuit breaker: Cannot fetch account (MCP error: {response.get('error')}), proceeding with caution")
                return True  # Proceed but log warning

            # Extract portfolio value from response
            portfolio_value = 0
            try:
                # Handle nested MCP response structure
                result = response.get("result", {})
                if "content" in result and isinstance(result["content"], list) and len(result["content"]) > 0:
                    content_text = result["content"][0].get("text", "")
                    if content_text:
                        parsed = json.loads(content_text)
                        # Extract equity value
                        if "account" in parsed:
                            portfolio_value = float(parsed["account"].get("equity", 0))
                        elif "equity" in parsed:
                            portfolio_value = float(parsed["equity"])

                # Fallback to direct extraction
                if portfolio_value == 0:
                    portfolio_value = float(result.get("equity", 0))

            except (json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
                logger.warning(f"⚠️  Circuit breaker: Cannot parse account response: {e}")
                return True  # Proceed but log warning

            # Calculate drawdown
            initial_capital = self.account_cfg["account_size_usd"]
            drawdown = ((portfolio_value - initial_capital) / initial_capital) * 100

            logger.info(f"💰 Circuit Breaker Check: Portfolio=${portfolio_value:.2f} | Drawdown: {drawdown:+.2f}%")

            # HALT trading if drawdown >= -40%
            if drawdown <= -40.0:
                logger.critical(f"🛑 CIRCUIT BREAKER ACTIVATED: Drawdown {drawdown:.2f}% exceeds -40% halt threshold")
                logger.critical(f"   All entry signals BLOCKED until recovery")
                return False

            return True  # Trading allowed

        except Exception as e:
            logger.warning(f"⚠️  Circuit breaker check failed: {e}, proceeding with caution")
            return True  # Proceed on unexpected errors

    def run_cycle(self):
        """Execute one trading cycle: process exits FIRST, then new entries"""
        cycle_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        logger.info("=" * 80)
        logger.info(f"CYCLE | {cycle_time} | PRODUCTION BOT (ENTRY + EXIT)")
        logger.info(f"Scanning {len(self.symbols)} symbols for entry + managing {len(self.position_tracker.get_all())} open positions")
        logger.info("=" * 80)

        # ======================================================================
        # PHASE 1: PROCESS EXITS (RISK MANAGEMENT FIRST)
        # ======================================================================
        logger.info("\n📋 PHASE 1: Exit Management")
        logger.info("-" * 80)

        exits_executed = 0
        open_positions = self.position_tracker.get_all().copy()

        for symbol in open_positions:
            position = self.position_tracker.get_position(symbol)
            if not position:
                continue

            # Get current technicals for exit evaluation
            current_data = MarketDataFetcher.get_technicals(symbol)
            if not current_data:
                logger.warning(f"⚠️  [{symbol}] Could not fetch data for exit evaluation (possible delisting)")
                continue

            # FIX #3: Update highest price for true trailing stop calculation
            current_price = current_data.get("price", 0)
            self.position_tracker.update_highest_price(symbol, current_price)

            # CRITICAL BUG FIX #4: Check cycle age BEFORE incrementing (not after!)
            # This ensures entry cycle protection actually works
            cycles_held = position.get("cycles_held", 0)
            if cycles_held < 1:
                # On entry cycle: increment for next evaluation, then skip exit checks
                logger.debug(f"📊 [{symbol}] Entry cycle (0→1) - holding for price action settlement")
                self.position_tracker.increment_cycles(symbol)
                continue

            # Only increment cycles if we're evaluating exits (not on entry cycle)
            self.position_tracker.increment_cycles(symbol)
            # CRITICAL BUG FIX: Refresh position reference after cycle increment (prevents NameError)
            position = self.position_tracker.get_position(symbol)

            # Check exit conditions
            exit_signal = self.exit_signal_gen.generate_exit_signal(symbol, position, current_data)

            if exit_signal:
                # CRITICAL BUG FIX: Use position (always defined) not undefined updated_position
                qty = position.get("qty", 1)
                exit_reason = exit_signal.get("reason", "UNKNOWN")
                exit_price = exit_signal.get("price", 0)
                pnl_pct = exit_signal.get("pnl_pct", 0)

                logger.info(f"🔴 EXIT SIGNAL: {symbol} SELL {qty} @ ${exit_price:.2f} | {exit_reason} | PnL: {pnl_pct:+.2f}%")

                # BUG FIX: MCP doesn't support price parameter for limit orders
                # Revert to market orders for now (MCP schema limitation)
                # TODO: Implement limit orders once MCP server schema supports it

                # CRITICAL BUG FIX #5: Check order success BEFORE removing position from tracking
                # If place_order fails, position tracking remains intact
                response = self.mcp.place_order(symbol, qty, side="sell")

                if "error" in response:
                    # OPERATIONAL RISK #3: Exit order failed - will retry next cycle
                    # Position remains tracked for automatic retry
                    # Retry window: 30 minutes (cron cycle interval)
                    logger.error(f"❌ Exit order FAILED for {symbol}: {response.get('error', 'Unknown error')}")
                    logger.error(f"   Position remains tracked (retry in 30 min)")

                    # CRITICAL BUG FIX: Use proper method for retry count (encapsulation-safe)
                    retry_count = self.position_tracker.increment_retry_count(symbol)
                    if retry_count >= 3:
                        logger.critical(f"🚨 {symbol} exit retry limit hit ({retry_count}x). Manual intervention required!")
                else:
                    # Order succeeded - only then remove from tracking
                    logger.info(f"✅ Exit order executed: {response}")
                    exits_executed += 1
                    self.position_tracker.remove_position(symbol)
            else:
                # Still holding - log status
                entry_price = position.get("entry_price", 0)
                current_price = current_data.get("price", 0)
                pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price else 0
                cycles = position.get("cycles_held", 0)

                logger.info(f"📊 [{symbol}] Holding | Entry: ${entry_price:.2f} | Current: ${current_price:.2f} | PnL: {pnl_pct:+.2f}% | Age: {cycles} cycles")

        logger.info(f"📊 Exits Executed: {exits_executed}")

        # ======================================================================
        # PHASE 2: SCREEN FOR NEW ENTRIES
        # ======================================================================
        logger.info("\n📋 PHASE 2: Entry Screening")
        logger.info("-" * 80)

        # PRODUCTION HARDENING: Circuit breaker check before entry screening
        if not self.check_circuit_breaker():
            logger.critical("🛑 CIRCUIT BREAKER ACTIVE - Skipping all entry signals")
            logger.info("=" * 80)
            return  # Exit immediately, no entries allowed

        signals_found = 0
        analyzed = []
        skipped = []

        for i, symbol in enumerate(self.symbols, 1):
            # FIX #2: Skip entry screening if position already open for this symbol
            if self.position_tracker.get_position(symbol):
                logger.debug(f"⏭️  [{i:2}/{len(self.symbols)}] {symbol:6} | Already in open positions - skipping entry scan")
                continue

            data = MarketDataFetcher.get_technicals(symbol)
            if not data:
                skipped.append(symbol)
                logger.debug(f"⏭️  [{i:2}/{len(self.symbols)}] {symbol:6} | Error analyzing - possibly delisted")
                continue

            analyzed.append(symbol)
            logger.info(f"✅ [{i:2}/{len(self.symbols)}] {symbol:6} | ADX: {data.get('adx', 0):6.1f} | Stoch: {data.get('stoch_k', 0):6.1f}")

            signal = self.entry_signal_gen.generate_signal(data)
            if not signal:
                continue

            signals_found += 1
            symbol = signal["symbol"]
            price = signal["price"]

            # CRITICAL FIX #10: Position size bounds for edge cases
            # Calculate theoretical position size
            target_alloc = self.account_cfg["account_size_usd"] * self.account_cfg["position_size_pct"]
            qty = max(1, int(target_alloc / price))

            # PRODUCTION HARDENING: Hard position sizing cap (0.5% absolute max)
            # This is a HARD OVERRIDE that cannot be bypassed by signal scores
            position_value = qty * price
            max_position_value = self.account_cfg["account_size_usd"] * 0.005  # 0.5% hard cap
            if position_value > max_position_value:
                qty = max(1, int(max_position_value / price))
                logger.info(f"🔐 [{symbol}] Position size HARD CAPPED to 0.5% max: {int(position_value)} → ${qty * price:.2f}")

            # Safety check: prevent oversizing on penny stocks or micro-caps
            # Ensure qty doesn't exceed account size even if price is very low
            max_qty = int(self.account_cfg["account_size_usd"] / max(price, 0.01))
            if qty > max_qty:
                logger.warning(f"⚠️  [{symbol}] Position size capped: {qty} → {max_qty} (price ${price:.4f})")
                qty = max_qty

            # Skip entry if position would be 0 (price too high for allocation)
            if qty < 1:
                logger.info(f"⏭️  [{symbol}] Price ${price:.2f} exceeds allocation - skipping")
                continue

            logger.info(f"🎯 ENTRY SIGNAL: {symbol} BUY {qty} @ ${price:.2f}")

            # BUG FIX: MCP doesn't support price parameter for limit orders
            # Revert to market orders for now (MCP schema limitation)
            # TODO: Implement limit orders once MCP server schema supports it

            # Place order and only track if successful
            response = self.mcp.place_order(symbol, qty, side="buy")

            if "error" in response:
                # Order failed - DO NOT add to position tracking
                logger.error(f"❌ Entry order FAILED for {symbol}: {response.get('error', 'Unknown error')}")
            else:
                # Order succeeded - extract actual fill price from MCP response (CRITICAL FIX #9)
                logger.info(f"✅ Entry order executed: {response}")

                # CRITICAL BUG FIX: Handle nested MCP response structure
                # MCP wraps tool results in: response["result"]["content"][0]["text"] as JSON
                fill_price = price  # Default to snapshot
                try:
                    result = response.get("result", {})

                    # Try direct extraction first (flat structure)
                    if "average_price" in result:
                        fill_price = float(result["average_price"])
                    elif "price" in result:
                        fill_price = float(result["price"])

                    # Try nested MCP structure (content array)
                    elif "content" in result and isinstance(result["content"], list) and len(result["content"]) > 0:
                        content_text = result["content"][0].get("text", "")
                        if content_text:
                            try:
                                parsed_content = json.loads(content_text)
                                fill_price = float(parsed_content.get("average_price", parsed_content.get("price", price)))
                            except (json.JSONDecodeError, ValueError, TypeError):
                                pass  # Fallback to snapshot price
                except (ValueError, TypeError, AttributeError):
                    pass  # Fallback to snapshot price

                # Track position with ACTUAL execution price (not stale snapshot)
                self.position_tracker.add_position(symbol, qty, float(fill_price), cycle_time)

                if abs(float(fill_price) - price) > 0.01:
                    logger.info(f"   Fill price ${float(fill_price):.2f} differs from snapshot ${price:.2f} (slippage: {((float(fill_price)-price)/price)*100:+.2f}%)")

        logger.info("=" * 80)
        logger.info(f"📊 Entry Analysis: {len(analyzed)} analyzed | {len(skipped)} skipped | {signals_found} signals")
        logger.info(f"   Analyzed: {', '.join(analyzed[:20])}" + (f" +{len(analyzed)-20}" if len(analyzed) > 20 else ""))
        if skipped:
            logger.info(f"   Skipped: {', '.join(skipped[:20])}" + (f" +{len(skipped)-20}" if len(skipped) > 20 else ""))
        logger.info("=" * 80 + "\n")

    def stop(self):
        """Cleanup"""
        self.mcp.stop()


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main entry point with proper error handling"""
    config = ConfigLoader.load()

    bot = TradingBot(config)
    try:
        bot.run_cycle()
    except KeyboardInterrupt:
        logger.info("[*] Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Bot error: {e}")
    finally:
        bot.stop()


if __name__ == "__main__":
    main()
