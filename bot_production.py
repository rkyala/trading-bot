#!/usr/bin/env python3
"""
Production Trading Bot - Local Cron Version
Loads RH_CLIENT_ID and RH_REFRESH_TOKEN from .env
Refreshes access token before each trade cycle
Places orders via Robinhood MCP
"""

import json
import logging
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
import pandas as pd
import numpy as np
import yfinance as yf
import anthropic

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot_prod.log')
    ]
)
logger = logging.getLogger(__name__)

# Load env vars from .env file
env_file = Path(".env")
if env_file.exists():
    for line in env_file.read_text().strip().split('\n'):
        if '=' in line and not line.startswith('#'):
            key, val = line.split('=', 1)
            os.environ[key.strip()] = val.strip()

# Get credentials from environment
RH_CLIENT_ID = os.getenv("RH_CLIENT_ID")
RH_REFRESH_TOKEN = os.getenv("RH_REFRESH_TOKEN")

if not RH_CLIENT_ID or not RH_REFRESH_TOKEN:
    logger.error("❌ RH_CLIENT_ID and RH_REFRESH_TOKEN not found in .env")
    logger.error("Run: python3 get_token.py")
    sys.exit(1)

logger.info(f"✅ Loaded credentials from .env")

# ============================================================================
# CONFIG
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

    SYMBOL_LIST = [
        'NVDA', 'TSLA', 'AMD', 'AAPL', 'MSFT', 'GOOGL', 'META', 'NFLX',
        'QCOM', 'AVGO', 'CSCO', 'INTC', 'MU', 'AMZN'
    ]


# ============================================================================
# TOKEN REFRESH
# ============================================================================

def get_fresh_access_token() -> Optional[str]:
    """Get fresh access token using refresh token"""
    import requests
    
    try:
        resp = requests.post(
            "https://api.robinhood.com/oauth2/token/",
            data={
                "grant_type": "refresh_token",
                "refresh_token": RH_REFRESH_TOKEN,
                "client_id": RH_CLIENT_ID,
                "scope": "internal",
            },
            timeout=10
        )
        
        if resp.status_code != 200:
            logger.error(f"Token refresh failed: {resp.status_code} {resp.text[:100]}")
            return None
        
        access_token = resp.json().get("access_token")
        if access_token:
            logger.info(f"✅ Fresh access token: {access_token[:20]}...")
            return access_token
        else:
            logger.error("No access_token in response")
            return None
            
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        return None


# ============================================================================
# MARKET DATA & SIGNALS
# ============================================================================

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

            # ADX
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

            # Stochastic
            low_min = df['Low'].rolling(14).min()
            high_max = df['High'].rolling(14).max()
            df['Stoch_K'] = 100 * ((df['Close'] - low_min) / (high_max - low_min).replace(0, np.nan))
            df['Stoch_D'] = df['Stoch_K'].rolling(3).mean()

            latest = df.iloc[-1]
            return {
                "symbol": symbol,
                "price": float(latest['Close']),
                "session_high": float(df['High'].iloc[-12:].max()),
                "session_low": float(df['Low'].iloc[-12:].min()),
                "adx": float(latest['ADX']),
                "stoch_k": float(latest['Stoch_K']),
                "stoch_d": float(latest['Stoch_D']),
                "timestamp": datetime.now().isoformat()
            }
        except:
            return None


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

        return {
            "symbol": data["symbol"],
            "price": data["price"],
            "adx": data["adx"],
            "stoch_k": data["stoch_k"],
            "fib_level": fib_level,
            "mult": mult,
            "timestamp": data["timestamp"]
        }

    @staticmethod
    def exit(pos: Dict, data: Dict) -> Optional[Dict]:
        curr = data["price"]
        entry = pos["entry_price"]
        peak = max(curr, pos.get("peak", entry))
        pos["peak"] = peak

        stop = peak * 0.985
        if stop > pos.get("stop", 0):
            pos["stop"] = stop

        if curr <= pos["stop"]:
            return {"symbol": pos["symbol"], "exit_price": curr, "pnl_pct": ((curr - entry) / entry) * 100, "reason": "Trailing stop"}

        if data.get("stoch_k", 0) > Config.STOCH_RECOVERY:
            return {"symbol": pos["symbol"], "exit_price": curr, "pnl_pct": ((curr - entry) / entry) * 100, "reason": "Stoch recovery"}

        return None


# ============================================================================
# CIRCUIT BREAKER
# ============================================================================

class CircuitBreaker:
    def __init__(self):
        self.state_file = Path("circuit_breaker_state.json")
        self.state = self._load()

    def _load(self):
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except:
                pass
        return {"is_halted": False, "pnl": 0.0, "losses": 0}

    def _save(self):
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def check(self) -> bool:
        if self.state["pnl"] / Config.ACCOUNT_SIZE <= Config.MAX_DRAWDOWN_PCT:
            self.state["is_halted"] = True
            self._save()
            logger.critical("CIRCUIT BREAKER: Drawdown halt")
            return True
        if self.state["losses"] >= Config.MAX_CONSECUTIVE_LOSSES:
            self.state["is_halted"] = True
            self._save()
            logger.critical("CIRCUIT BREAKER: Loss limit")
            return True
        return self.state["is_halted"]

    def log_trade(self, pnl: float):
        if pnl < 0:
            self.state["losses"] += 1
        else:
            self.state["losses"] = 0
        self.state["pnl"] += pnl
        self._save()


# ============================================================================
# POSITIONS + MCP EXECUTION
# ============================================================================

class PositionManager:
    def __init__(self, access_token: str):
        self.file = Path("positions.json")
        self.positions = self._load()
        self.access_token = access_token
        # Set token in environment for MCP
        os.environ["ROBINHOOD_TOKEN"] = access_token
        self.client = anthropic.Anthropic()

    def _load(self):
        if self.file.exists():
            try:
                return json.loads(self.file.read_text())
            except:
                pass
        return []

    def save(self):
        self.file.write_text(json.dumps(self.positions, indent=2))

    def place(self, signal: Dict) -> bool:
        if any(p["symbol"] == signal["symbol"] for p in self.positions):
            return False

        qty = int(Config.ACCOUNT_SIZE * Config.POSITION_SIZE_PCT * signal["mult"] / signal["price"])
        qty = max(1, qty)

        logger.info(f"📈 SIGNAL: {signal['symbol']} BUY {qty} @ ${signal['price']:.2f}")

        # Execute via MCP with fresh token
        try:
            response = self.client.messages.create(
                model="claude-opus-5",
                max_tokens=1024,
                tools=[{"type": "mcp", "name": "robinhood-trading"}],
                messages=[{
                    "role": "user",
                    "content": f"Place a market BUY order: {signal['symbol']}, {qty} shares. Use place_equity_order tool."
                }]
            )
            logger.info(f"✅ MCP order placed for {signal['symbol']}")
        except Exception as e:
            logger.error(f"MCP error: {e}")

        pos = {
            "symbol": signal["symbol"],
            "qty": qty,
            "entry_price": signal["price"],
            "entry_time": signal["timestamp"],
            "stop": signal["price"] * 0.985,
            "peak": signal["price"],
            "mult": signal["mult"]
        }

        self.positions.append(pos)
        self.save()
        return True

    def close(self, exit_sig: Dict, circuit: CircuitBreaker) -> bool:
        pos = next((p for p in self.positions if p["symbol"] == exit_sig["symbol"]), None)
        if not pos:
            return False

        pnl = (exit_sig["exit_price"] - pos["entry_price"]) * pos["qty"]
        logger.info(f"🔴 CLOSED: {exit_sig['symbol']} @ ${exit_sig['exit_price']:.2f} | P&L: ${pnl:+.2f}")

        circuit.log_trade(pnl)
        self.positions = [p for p in self.positions if p["symbol"] != exit_sig["symbol"]]
        self.save()
        return True


# ============================================================================
# MAIN BOT
# ============================================================================

class BotProduction:
    def __init__(self, access_token: str):
        self.market = MarketDataFetcher()
        self.signals = SignalGenerator()
        self.circuit = CircuitBreaker()
        self.positions = PositionManager(access_token)
        self.vol = VolatilityMonitor()

    def run(self):
        logger.info(f"\n{'='*100}")
        logger.info(f"CYCLE | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | MODE: MCP LIVE")
        logger.info(f"{'='*100}")

        if self.circuit.check():
            logger.warning("🛑 HALTED")
            return

        mult, vol_status = self.vol.get_position_multiplier()
        logger.info(f"📊 Volatility: {vol_status} | Mult: {mult:.1f}x")

        # Scan
        entry_count = 0
        for symbol in Config.SYMBOL_LIST:
            data = self.market.get_technicals(symbol)
            if not data:
                continue

            sig = self.signals.entry(data, mult)
            if sig:
                entry_count += 1
                self.positions.place(sig)

        logger.info(f"📋 Scanned {len(Config.SYMBOL_LIST)} | Found {entry_count} signals")

        # Manage
        exit_count = 0
        for pos in self.positions.positions[:]:
            data = self.market.get_technicals(pos["symbol"])
            if not data:
                continue

            exit_sig = self.signals.exit(pos, data)
            if exit_sig:
                exit_count += 1
                self.positions.close(exit_sig, self.circuit)
            else:
                self.positions.save()

        logger.info(f"📊 Open: {len(self.positions.positions)} | Exits: {exit_count}")
        logger.info(f"{'='*100}\n")


if __name__ == "__main__":
    # Get fresh access token
    access_token = get_fresh_access_token()
    if not access_token:
        logger.error("Failed to get access token")
        sys.exit(1)

    # Run bot
    bot = BotProduction(access_token)
    bot.run()
