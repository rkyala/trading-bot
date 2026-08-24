#!/usr/bin/env python3
"""
Trading Bot - Official Robinhood MCP Server
Communicates with official @modelcontextprotocol/server-robinhood via stdio
Live trading enabled through official MCP protocol
"""

import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
import pandas as pd
import numpy as np
import yfinance as yf

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler('bot_official_mcp.log')]
)
logger = logging.getLogger(__name__)

# ============================================================================
# OFFICIAL MCP CLIENT
# ============================================================================

class OfficialMCPClient:
    """Client for official Robinhood MCP server"""

    def __init__(self):
        logger.info("[+] Connecting to official Robinhood MCP server...")
        self.process = subprocess.Popen(
            ["npx", "-y", "@modelcontextprotocol/server-robinhood"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        self.req_id = 1
        logger.info("✅ Connected to official MCP server\n")

    def _rpc(self, method: str, params: dict = None) -> dict:
        """Send JSON-RPC request to official server"""
        req = {
            "jsonrpc": "2.0",
            "id": self.req_id,
            "method": method,
            "params": params or {}
        }
        self.req_id += 1

        try:
            self.process.stdin.write(json.dumps(req) + "\n")
            self.process.stdin.flush()
            resp_line = self.process.stdout.readline()
            return json.loads(resp_line) if resp_line else {"error": "No response"}
        except Exception as e:
            return {"error": str(e)}

    def place_order(self, symbol: str, qty: int, side: str = "buy"):
        """Place order via official MCP"""
        return self._rpc("tools/call", {
            "name": "place_equity_order",
            "arguments": {
                "symbol": symbol,
                "quantity": qty,
                "side": side,
                "time_in_force": "day",
                "order_type": "market"
            }
        })

    def get_positions(self):
        """Get positions via official MCP"""
        return self._rpc("tools/call", {
            "name": "get_equity_positions",
            "arguments": {}
        })

    def get_portfolio(self):
        """Get portfolio via official MCP"""
        return self._rpc("tools/call", {
            "name": "get_portfolio",
            "arguments": {}
        })

    def stop(self):
        """Stop MCP server"""
        self.process.terminate()

# ============================================================================
# CONFIG & MARKET DATA
# ============================================================================

class Config:
    POSITION_SIZE_PCT = 0.005
    MIN_ADX = 20.0
    STOCH_OVERSOLD = 30.0
    FIB_LEVELS = [0.236, 0.382, 0.500, 0.618]
    SYMBOL_LIST = ['NVDA', 'TSLA', 'AMD', 'AAPL', 'MSFT', 'GOOGL', 'META', 'NFLX', 'QCOM', 'AVGO']

class MarketDataFetcher:
    @staticmethod
    def get_technicals(symbol: str) -> Optional[Dict]:
        try:
            df = yf.Ticker(symbol).history(period="5d", interval="30m").dropna()
            if len(df) < 30:
                return None
            df['Close'] = df['Close'].astype(float)
            high, low, close = df['High'].astype(float), df['Low'].astype(float), df['Close']
            tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
            up, down = high - high.shift(), low.shift() - low
            plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0), index=df.index)
            minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0), index=df.index)
            atr = tr.rolling(14).mean()
            plus_di = 100 * (plus_dm.rolling(14).mean() / atr)
            minus_di = 100 * (minus_dm.rolling(14).mean() / atr)
            dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
            df['ADX'] = dx.rolling(14).mean()
            low_min = df['Low'].rolling(14).min()
            high_max = df['High'].rolling(14).max()
            df['Stoch_K'] = 100 * ((df['Close'] - low_min) / (high_max - low_min).replace(0, np.nan))
            latest = df.iloc[-1]
            return {
                "symbol": symbol, "price": float(latest['Close']),
                "session_high": float(df['High'].iloc[-12:].max()),
                "session_low": float(df['Low'].iloc[-12:].min()),
                "adx": float(latest['ADX']), "stoch_k": float(latest['Stoch_K']),
                "timestamp": datetime.now().isoformat()
            }
        except:
            return None

def calc_fib(high: float, low: float):
    return {level: high - (high - low) * level for level in Config.FIB_LEVELS}

def at_fib(price: float, fibs: Dict) -> Tuple[bool, str]:
    for ratio, level_price in fibs.items():
        if level_price > 0 and abs(price - level_price) / level_price < 0.02:
            return True, f"{ratio*100:.1f}%"
    return False, "None"

class SignalGenerator:
    @staticmethod
    def entry(data: Dict) -> Optional[Dict]:
        if np.isnan(data.get("adx", 0)) or data.get("adx", 0) < Config.MIN_ADX:
            return None
        if data.get("stoch_k", 100) > Config.STOCH_OVERSOLD:
            return None
        fibs = calc_fib(data["session_high"], data["session_low"])
        confluence, fib_level = at_fib(data["price"], fibs)
        if not confluence:
            return None
        return {"symbol": data["symbol"], "price": data["price"], "fib_level": fib_level, "timestamp": data["timestamp"]}

# ============================================================================
# BOT
# ============================================================================

class BotOfficialMCP:
    def __init__(self):
        self.market = MarketDataFetcher()
        self.signals = SignalGenerator()
        self.mcp = OfficialMCPClient()

    def run(self):
        logger.info(f"\n{'='*80}")
        logger.info(f"CYCLE | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | OFFICIAL ROBINHOOD MCP")
        logger.info(f"{'='*80}")

        # Get portfolio status
        portfolio = self.mcp.get_portfolio()
        if "result" in portfolio and "error" not in portfolio["result"]:
            logger.info(f"✅ Connected to Robinhood account")
        else:
            logger.warning(f"⚠️  Portfolio fetch: {portfolio}")

        # Scan for signals
        entry_count = 0
        for symbol in Config.SYMBOL_LIST:
            data = self.market.get_technicals(symbol)
            if not data:
                continue
            sig = self.signals.entry(data)
            if sig:
                entry_count += 1
                qty = max(1, int(10000 * Config.POSITION_SIZE_PCT / sig["price"]))
                logger.info(f"📈 SIGNAL: {symbol} BUY {qty} @ ${sig['price']:.2f}")

                # Place via official MCP
                result = self.mcp.place_order(symbol, qty)
                if "result" in result:
                    result_data = result["result"]
                    if "error" in result_data:
                        logger.error(f"   ❌ {result_data['error']}")
                    else:
                        logger.info(f"   ✅ Order {result_data.get('order_id', '?')}")
                else:
                    logger.error(f"   ❌ {result}")

        logger.info(f"📋 Scanned {len(Config.SYMBOL_LIST)} | Found {entry_count} signals")
        logger.info(f"{'='*80}\n")
        self.mcp.stop()

if __name__ == "__main__":
    bot = BotOfficialMCP()
    bot.run()
