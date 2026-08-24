#!/usr/bin/env python3
"""
Complete Trading Bot - Pure Local MCP
No Claude, no tokens, no external APIs
Bot → Local MCP Server → Robinhood API
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
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler('bot_local_mcp.log')]
)
logger = logging.getLogger(__name__)

# ============================================================================
# LOCAL MCP CLIENT
# ============================================================================

class LocalMCPClient:
    def __init__(self):
        self.process = subprocess.Popen(
            [sys.executable, "robinhood_mcp_local.py"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1
        )
        self.req_id = 1

    def _rpc(self, method: str, params: dict = None) -> dict:
        req = {"jsonrpc": "2.0", "id": self.req_id, "method": method, "params": params or {}}
        self.req_id += 1
        self.process.stdin.write(json.dumps(req) + "\n")
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline() or "{}")

    def place_order(self, symbol: str, qty: int):
        return self._rpc("tools/call", {"name": "place_equity_order", "arguments": {"symbol": symbol, "quantity": qty, "side": "buy"}})

    def get_positions(self):
        return self._rpc("tools/call", {"name": "get_equity_positions", "arguments": {}})

    def stop(self):
        self.process.terminate()

# ============================================================================
# CONFIG & MARKET DATA
# ============================================================================

class Config:
    POSITION_SIZE_PCT = 0.005
    MIN_ADX = 20.0
    STOCH_OVERSOLD = 30.0
    STOCH_RECOVERY = 50.0
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

class BotLocalMCP:
    def __init__(self):
        self.market = MarketDataFetcher()
        self.signals = SignalGenerator()
        self.mcp = LocalMCPClient()

    def run(self):
        logger.info(f"\n{'='*80}")
        logger.info(f"CYCLE | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | PURE LOCAL MCP")
        logger.info(f"{'='*80}")

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
                result = self.mcp.place_order(symbol, qty)
                logger.info(f"   Response: {str(result)[:100]}")

        logger.info(f"📋 Scanned {len(Config.SYMBOL_LIST)} | Found {entry_count} signals")
        logger.info(f"{'='*80}\n")
        self.mcp.stop()

if __name__ == "__main__":
    bot = BotLocalMCP()
    bot.run()
