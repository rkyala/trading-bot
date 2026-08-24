#!/usr/bin/env python3
"""
Trading Bot - MCP Client
Communicates with self-hosted Robinhood MCP server
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
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot_mcp_client.log')
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# MCP CLIENT
# ============================================================================

class MCPClient:
    """Client for communicating with MCP server via stdin/stdout"""
    
    def __init__(self):
        self.process = None
        self.start_server()
    
    def start_server(self):
        """Start MCP server process"""
        try:
            self.process = subprocess.Popen(
                [sys.executable, "robinhood_mcp_server.py"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=Path.cwd()
            )
            # Read initialization response
            init_response = self.process.stdout.readline()
            logger.info(f"✅ MCP server started")
        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")
            self.process = None
    
    def call_tool(self, tool_name: str, args: Dict) -> Optional[Dict]:
        """Call a tool on the MCP server"""
        if not self.process:
            logger.error("MCP server not running")
            return None
        
        message = {
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": args
            }
        }
        
        try:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()
            
            response_line = self.process.stdout.readline()
            if response_line:
                return json.loads(response_line)
            return None
        except Exception as e:
            logger.error(f"MCP call error: {e}")
            return None
    
    def place_order(self, symbol: str, qty: int, side: str = "buy") -> Dict:
        """Place order via MCP"""
        return self.call_tool("place_equity_order", {
            "symbol": symbol,
            "quantity": qty,
            "side": side
        })
    
    def get_positions(self) -> Dict:
        """Get positions via MCP"""
        return self.call_tool("get_equity_positions", {})
    
    def get_portfolio(self) -> Dict:
        """Get portfolio via MCP"""
        return self.call_tool("get_portfolio", {})


# ============================================================================
# CONFIG & MARKET DATA (same as before)
# ============================================================================

class Config:
    ACCOUNT_SIZE = 10000.0
    POSITION_SIZE_PCT = 0.005
    MAX_DRAWDOWN_PCT = -0.40
    MAX_CONSECUTIVE_LOSSES = 29
    MIN_ADX = 20.0
    STOCH_OVERSOLD = 30.0
    STOCH_RECOVERY = 50.0
    FIB_LEVELS = [0.236, 0.382, 0.500, 0.618]
    BALANCED_HIGH_VOL_MULT = 1.1
    VIX_HIGH_THRESHOLD = 35.0
    SYMBOL_LIST = ['NVDA', 'TSLA', 'AMD', 'AAPL', 'MSFT', 'GOOGL', 'META', 'NFLX', 'QCOM', 'AVGO']


class VolatilityMonitor:
    @staticmethod
    def get_vix() -> float:
        try:
            vix_data = yf.Ticker("^VIX").history(period="1d")
            if not vix_data.empty:
                return float(vix_data['Close'].iloc[-1])
        except:
            return 20.0
        return 20.0

    @staticmethod
    def get_position_multiplier() -> Tuple[float, str]:
        vix = VolatilityMonitor.get_vix()
        if vix > Config.VIX_HIGH_THRESHOLD:
            return Config.BALANCED_HIGH_VOL_MULT, f"PANIC (VIX {vix:.1f})"
        return 1.0, f"NORMAL (VIX {vix:.1f})"


class MarketDataFetcher:
    @staticmethod
    def get_technicals(symbol: str) -> Optional[Dict]:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="5d", interval="30m").dropna()
            if len(df) < 30:
                return None
            df['Close'] = df['Close'].astype(float)
            df['High'] = df['High'].astype(float)
            df['Low'] = df['Low'].astype(float)
            high, low, close = df['High'], df['Low'], df['Close']
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
            df['Stoch_D'] = df['Stoch_K'].rolling(3).mean()
            latest = df.iloc[-1]
            return {
                "symbol": symbol, "price": float(latest['Close']),
                "session_high": float(df['High'].iloc[-12:].max()),
                "session_low": float(df['Low'].iloc[-12:].min()),
                "adx": float(latest['ADX']), "stoch_k": float(latest['Stoch_K']),
                "stoch_d": float(latest['Stoch_D']), "timestamp": datetime.now().isoformat()
            }
        except:
            return None


# Simplified signal generation (same as before)
def calc_fib(high: float, low: float) -> Dict:
    diff = high - low
    return {level: high - (diff * level) for level in Config.FIB_LEVELS}

def at_fib(price: float, fibs: Dict) -> Tuple[bool, str]:
    for ratio, level_price in fibs.items():
        if level_price > 0 and abs(price - level_price) / level_price < 0.02:
            return True, f"{ratio*100:.1f}%"
    return False, "None"


class SignalGenerator:
    @staticmethod
    def entry(data: Dict, mult: float) -> Optional[Dict]:
        if np.isnan(data.get("adx", 0)) or data.get("adx", 0) < Config.MIN_ADX:
            return None
        if data.get("stoch_k", 100) > Config.STOCH_OVERSOLD or data["stoch_k"] <= data["stoch_d"]:
            return None
        fibs = calc_fib(data["session_high"], data["session_low"])
        confluence, fib_level = at_fib(data["price"], fibs)
        if not confluence:
            return None
        return {"symbol": data["symbol"], "price": data["price"], "adx": data["adx"],
                "stoch_k": data["stoch_k"], "fib_level": fib_level, "mult": mult, "timestamp": data["timestamp"]}


# ============================================================================
# MAIN BOT
# ============================================================================

class BotMCPClient:
    def __init__(self):
        self.market = MarketDataFetcher()
        self.signals = SignalGenerator()
        self.vol = VolatilityMonitor()
        self.mcp = MCPClient()
        self.positions = self._load_positions()
    
    def _load_positions(self):
        file = Path("positions.json")
        if file.exists():
            try:
                return json.loads(file.read_text())
            except:
                pass
        return []
    
    def _save_positions(self):
        Path("positions.json").write_text(json.dumps(self.positions, indent=2))
    
    def run(self):
        logger.info(f"\n{'='*100}")
        logger.info(f"CYCLE | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | MCP CLIENT")
        logger.info(f"{'='*100}")
        
        mult, vol_status = self.vol.get_position_multiplier()
        logger.info(f"📊 Volatility: {vol_status} | Mult: {mult:.1f}x")
        
        # Scan for signals
        entry_count = 0
        for symbol in Config.SYMBOL_LIST:
            data = self.market.get_technicals(symbol)
            if not data:
                continue
            sig = self.signals.entry(data, mult)
            if sig:
                entry_count += 1
                qty = max(1, int(Config.ACCOUNT_SIZE * Config.POSITION_SIZE_PCT * mult / sig["price"]))
                logger.info(f"📈 SIGNAL: {symbol} BUY {qty}")
                
                # Place via MCP
                result = self.mcp.place_order(symbol, qty)
                if result and result.get("content"):
                    logger.info(f"✅ {result['content'][0]['text'][:100]}")
        
        logger.info(f"📋 Scanned {len(Config.SYMBOL_LIST)} | Found {entry_count} signals")
        logger.info(f"{'='*100}\n")


if __name__ == "__main__":
    bot = BotMCPClient()
    bot.run()
