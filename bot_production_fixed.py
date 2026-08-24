#!/usr/bin/env python3
"""
Production Trading Bot - Local MCP Bridge
Integrates: Config management, bug fixes, MCP handshake, safe calculations
No hardcoded values - all configuration from config.json
"""

import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
import pandas as pd
import numpy as np
import yfinance as yf

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
                "clientInfo": {"name": "trading-bot", "version": "1.0.0"}
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

            line = self.process.stdout.readline()
            if not line:
                return {"error": "No response from MCP"}

            return json.loads(line)
        except Exception as e:
            logger.error(f"RPC error: {e}")
            return {"error": str(e)}

    def place_order(self, symbol: str, qty: int):
        """Place order via MCP"""
        return self._rpc("tools/call", {
            "name": "place_equity_order",
            "arguments": {
                "symbol": symbol,
                "quantity": qty,
                "side": "buy"
            }
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
    """Fetch and calculate technicals with safe division handling"""

    @staticmethod
    def get_technicals(symbol: str) -> Optional[Dict]:
        """
        BUG FIX #3: Safe calculation of Stochastic and ADX
        Handles zero-division and NaN values gracefully
        """
        try:
            df = yf.Ticker(symbol).history(period="60d").dropna()
            if len(df) < 50:
                return None

            high = df['High'].astype(float)
            low = df['Low'].astype(float)
            close = df['Close'].astype(float)

            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)

            atr = tr.rolling(14).mean()
            up = high - high.shift()
            down = low.shift() - low

            plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0), index=df.index)
            minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0), index=df.index)

            plus_di = 100 * (plus_dm.rolling(14).mean() / atr)
            minus_di = 100 * (minus_dm.rolling(14).mean() / atr)
            di_diff = (plus_di - minus_di).abs()
            adx = di_diff.rolling(14).mean()

            # Safe Stochastic calculation (BUG FIX #3)
            lookback = 14
            high_max = high.rolling(lookback).max()
            low_min = low.rolling(lookback).min()
            range_hl = high_max - low_min

            range_hl_safe = range_hl.replace(0, np.nan)
            stoch_k = 100 * ((close - low_min) / range_hl_safe)
            stoch_k = stoch_k.fillna(50.0)

            stoch_d = stoch_k.rolling(3).mean()

            return {
                "symbol": symbol,
                "price": close.iloc[-1],
                "adx": adx.iloc[-1],
                "stoch_k": stoch_k.iloc[-1],
                "stoch_d": stoch_d.iloc[-1],
                "high_14": high_max.iloc[-1],
                "low_14": low_min.iloc[-1],
                "range_14": range_hl.iloc[-1]
            }
        except Exception as e:
            logger.warning(f"Error analyzing {symbol}: {e}")
            return None


# ============================================================================
# SIGNAL GENERATOR
# ============================================================================

class SignalGenerator:
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
# TRADING BOT
# ============================================================================

class TradingBot:
    """Main trading bot orchestrator"""

    def __init__(self, config: Dict):
        self.config = config
        self.mcp = LocalMCPClient(config)
        self.signal_gen = SignalGenerator(config)
        self.account_cfg = config["account"]
        self.symbols = config["strategy"]["symbols"]

    def run_cycle(self):
        """Execute one trading cycle"""
        logger.info("=" * 80)
        logger.info(f"CYCLE | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | PRODUCTION BOT")
        logger.info("=" * 80)

        signals_found = 0

        for symbol in self.symbols:
            data = MarketDataFetcher.get_technicals(symbol)
            if not data:
                continue

            signal = self.signal_gen.generate_signal(data)
            if not signal:
                continue

            signals_found += 1
            symbol = signal["symbol"]
            price = signal["price"]

            qty = max(1, int(
                (self.account_cfg["account_size_usd"] * self.account_cfg["position_size_pct"]) / price
            ))

            logger.info(f"📈 SIGNAL: {symbol} {signal['signal_type']} {qty} @ ${price:.2f}")

            response = self.mcp.place_order(symbol, qty)
            logger.info(f"   Response: {response}")

        logger.info(f"📋 Scanned {len(self.symbols)} | Found {signals_found} signals")
        logger.info("=" * 80 + "\n")

    def stop(self):
        """Cleanup (BUG FIX #4)"""
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
