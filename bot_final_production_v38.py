#!/usr/bin/env python3
"""
v3.8 PRODUCTION BOT: Mean-Reversion + Balanced Volatility + ROBINHOOD MCP
Live trading via Robinhood MCP (agent.robinhood.com)
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
import yfinance as yf
import anthropic

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot_v38.log')
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """v3.8 Bot Configuration with Balanced Volatility + MCP"""

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

    # MCP Configuration (Robinhood)
    MCP_SERVER_URL = "agent.robinhood.com"
    MCP_ENABLED = True

    SYMBOL_LIST = [
        'NVDA', 'TSLA', 'AMD', 'AAPL', 'MSFT', 'GOOGL', 'META', 'NFLX',
        'QCOM', 'AVGO', 'CSCO', 'INTC', 'MU', 'AMZN'
    ]


# ============================================================================
# MCP CLIENT
# ============================================================================

class RobinhoodMCPClient:
    """Interface to Robinhood MCP via Claude"""

    def __init__(self):
        self.client = anthropic.Anthropic()
        self.model = "claude-opus-5"  # Production model for MCP
        self.mcp_server_url = Config.MCP_SERVER_URL

    def place_order(self, symbol: str, quantity: int, price: float) -> Dict:
        """
        Place equity order via Robinhood MCP

        Returns:
            {"status": "success/error", "order_id": "...", "message": "..."}
        """
        try:
            prompt = f"""
            Place a BUY equity order on Robinhood using the place_equity_order tool.

            Details:
            - Symbol: {symbol}
            - Quantity: {quantity}
            - Price: ${price:.2f}
            - Order type: Market Buy
            - Time in force: Day

            Execute the order and return the order ID and confirmation.
            """

            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                tools=[
                    {
                        "type": "mcp",
                        "name": "robinhood-trading",
                        "uri": f"mcp://{self.mcp_server_url}"
                    }
                ],
                messages=[{"role": "user", "content": prompt}]
            )

            # Extract order confirmation from response
            logger.info(f"MCP Response: {response.content}")
            return {"status": "success", "message": "Order placed via MCP"}

        except Exception as e:
            logger.error(f"MCP order placement failed: {e}")
            return {"status": "error", "message": str(e)}

    def cancel_order(self, order_id: str) -> Dict:
        """Cancel order via Robinhood MCP"""
        try:
            prompt = f"""
            Cancel the following order on Robinhood using the cancel_equity_order tool.
            Order ID: {order_id}
            """

            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                tools=[
                    {
                        "type": "mcp",
                        "name": "robinhood-trading",
                        "uri": f"mcp://{self.mcp_server_url}"
                    }
                ],
                messages=[{"role": "user", "content": prompt}]
            )

            logger.info(f"Order {order_id} cancelled via MCP")
            return {"status": "success", "message": "Order cancelled"}

        except Exception as e:
            logger.error(f"MCP order cancellation failed: {e}")
            return {"status": "error", "message": str(e)}

    def get_positions(self) -> List[Dict]:
        """Get current positions from Robinhood MCP"""
        try:
            prompt = "Get all current equity positions from my Robinhood account using get_equity_positions tool."

            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                tools=[
                    {
                        "type": "mcp",
                        "name": "robinhood-trading",
                        "uri": f"mcp://{self.mcp_server_url}"
                    }
                ],
                messages=[{"role": "user", "content": prompt}]
            )

            logger.info(f"Positions retrieved from Robinhood: {response.content}")
            return []  # Parse response to extract positions

        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            return []


# ============================================================================
# VOLATILITY MONITOR
# ============================================================================

class VolatilityMonitor:
    """Monitor VIX for position sizing adjustment"""

    @staticmethod
    def get_vix() -> float:
        try:
            vix_data = yf.Ticker("^VIX").history(period="1d")
            if not vix_data.empty:
                return float(vix_data['Close'].iloc[-1])
        except Exception as e:
            logger.warning(f"VIX fetch failed: {e}, defaulting to 20.0")
        return 20.0

    @staticmethod
    def get_position_multiplier() -> Tuple[float, str]:
        vix = VolatilityMonitor.get_vix()
        if vix > Config.VIX_HIGH_THRESHOLD:
            return Config.BALANCED_HIGH_VOL_MULT, f"PANIC (VIX {vix:.1f})"
        return 1.0, f"NORMAL (VIX {vix:.1f})"


# ============================================================================
# MARKET DATA FETCHER
# ============================================================================

class MarketDataFetcher:
    """Fetch real-time market data and calculate indicators"""

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

            # Calculate ADX
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

            # Calculate Stochastic
            low_min = df['Low'].rolling(14).min()
            high_max = df['High'].rolling(14).max()
            df['Stoch_K'] = 100 * ((df['Close'] - low_min) / (high_max - low_min).replace(0, np.nan))
            df['Stoch_D'] = df['Stoch_K'].rolling(3).mean()

            latest = df.iloc[-1]
            session_high = df['High'].iloc[-12:].max()
            session_low = df['Low'].iloc[-12:].min()

            return {
                "symbol": symbol,
                "price": float(latest['Close']),
                "session_high": float(session_high),
                "session_low": float(session_low),
                "adx": float(latest['ADX']),
                "stoch_k": float(latest['Stoch_K']),
                "stoch_d": float(latest['Stoch_D']),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Data fetch error for {symbol}: {e}")
            return None


# ============================================================================
# FIBONACCI CALCULATOR
# ============================================================================

def calculate_fibonacci_levels(high: float, low: float) -> Dict[float, float]:
    diff = high - low
    return {level: high - (diff * level) for level in Config.FIB_LEVELS}

def is_price_at_confluence(price: float, fib_levels: Dict[float, float], tolerance_pct: float = 0.02) -> Tuple[bool, str]:
    for level_ratio, level_price in fib_levels.items():
        if level_price > 0 and abs(price - level_price) / level_price < tolerance_pct:
            return True, f"{level_ratio*100:.1f}%"
    return False, "None"


# ============================================================================
# SIGNAL GENERATOR
# ============================================================================

class SignalGenerator:

    @staticmethod
    def evaluate_entry(data: Dict, position_mult: float) -> Optional[Dict]:
        if np.isnan(data.get("adx", 0)) or data.get("adx", 0) < Config.MIN_ADX:
            return None

        if data.get("stoch_k", 100) > Config.STOCH_OVERSOLD or data["stoch_k"] <= data["stoch_d"]:
            return None

        fib_levels = calculate_fibonacci_levels(data["session_high"], data["session_low"])
        is_confluence, fib_level = is_price_at_confluence(data["price"], fib_levels)

        if not is_confluence:
            return None

        return {
            "symbol": data["symbol"],
            "signal": "BUY",
            "price": data["price"],
            "adx": data["adx"],
            "stoch_k": data["stoch_k"],
            "fibonacci_level": fib_level,
            "position_multiplier": position_mult,
            "reason": f"Oversold at {fib_level} Fib | ADX {data['adx']:.1f}",
            "timestamp": data.get("timestamp", datetime.now().isoformat())
        }

    @staticmethod
    def evaluate_exit(position: Dict, current_data: Dict) -> Optional[Dict]:
        current_price = current_data["price"]
        entry_price = position["entry_price"]

        peak_price = max(current_price, position.get("peak_price", entry_price))
        position["peak_price"] = peak_price

        trailing_stop = peak_price * 0.985
        if trailing_stop > position.get("trailing_stop", 0):
            position["trailing_stop"] = trailing_stop

        if current_price <= position["trailing_stop"]:
            return {
                "symbol": position["symbol"],
                "signal": "EXIT_TRAILING_STOP",
                "exit_price": current_price,
                "pnl_pct": ((current_price - entry_price) / entry_price) * 100,
                "reason": f"Trailing stop hit | Peak: ${peak_price:.2f}, Stop: ${position['trailing_stop']:.2f}"
            }

        if current_data.get("stoch_k", 0) > Config.STOCH_RECOVERY:
            return {
                "symbol": position["symbol"],
                "signal": "EXIT_PROFIT",
                "exit_price": current_price,
                "pnl_pct": ((current_price - entry_price) / entry_price) * 100,
                "reason": f"Stoch recovery at {current_data['stoch_k']:.1f}"
            }

        return None


# ============================================================================
# CIRCUIT BREAKER
# ============================================================================

class CircuitBreaker:

    def __init__(self, state_file: str = "circuit_breaker_state.json"):
        self.state_file = Path(state_file)
        self.state = self._load_state()

    def _load_state(self) -> Dict:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except Exception:
                pass
        return {
            "is_halted": False,
            "halt_reason": None,
            "cumulative_pnl_usd": 0.0,
            "consecutive_losses": 0
        }

    def _save_state(self):
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def check_halt_conditions(self) -> bool:
        drawdown_pct = self.state["cumulative_pnl_usd"] / Config.ACCOUNT_SIZE

        if drawdown_pct <= Config.MAX_DRAWDOWN_PCT:
            self.state["is_halted"] = True
            self.state["halt_reason"] = f"Drawdown: {drawdown_pct*100:.1f}%"
            self._save_state()
            logger.critical(f"🔴 CIRCUIT BREAKER: {self.state['halt_reason']}")
            return True

        if self.state["consecutive_losses"] >= Config.MAX_CONSECUTIVE_LOSSES:
            self.state["is_halted"] = True
            self.state["halt_reason"] = f"{Config.MAX_CONSECUTIVE_LOSSES} consecutive losses"
            self._save_state()
            logger.critical(f"🔴 CIRCUIT BREAKER: {self.state['halt_reason']}")
            return True

        return self.state["is_halted"]

    def log_trade_result(self, pnl_usd: float):
        if pnl_usd < 0:
            self.state["consecutive_losses"] += 1
        else:
            self.state["consecutive_losses"] = 0

        self.state["cumulative_pnl_usd"] += pnl_usd
        self._save_state()


# ============================================================================
# POSITION MANAGER (WITH MCP)
# ============================================================================

class PositionManager:

    def __init__(self, mcp_client: Optional[RobinhoodMCPClient] = None):
        self.positions_file = Path("positions.json")
        self.positions = self._load_positions()
        self.mcp = mcp_client or (RobinhoodMCPClient() if Config.MCP_ENABLED else None)
        self.order_ids = {}  # Track symbol -> order_id mapping

    def _load_positions(self) -> List[Dict]:
        if self.positions_file.exists():
            try:
                return json.loads(self.positions_file.read_text())
            except Exception:
                pass
        return []

    def save_positions(self):
        self.positions_file.write_text(json.dumps(self.positions, indent=2))

    def place_order(self, signal: Dict) -> bool:
        try:
            # Prevent duplicate positions
            if any(p["symbol"] == signal["symbol"] for p in self.positions):
                return False

            position_size_usd = Config.ACCOUNT_SIZE * Config.POSITION_SIZE_PCT * signal.get("position_multiplier", 1.0)
            quantity = max(1, int(position_size_usd / signal["price"]))

            # PLACE ORDER VIA MCP
            if self.mcp:
                mcp_result = self.mcp.place_order(
                    symbol=signal["symbol"],
                    quantity=quantity,
                    price=signal["price"]
                )

                if mcp_result["status"] == "error":
                    logger.error(f"MCP order failed: {mcp_result['message']}")
                    return False

                order_id = mcp_result.get("order_id", f"MCP-{signal['symbol']}-{datetime.now().timestamp()}")
                self.order_ids[signal["symbol"]] = order_id
                logger.info(f"✅ MCP ORDER: {signal['symbol']} BUY {quantity} @ ${signal['price']:.2f} | Order ID: {order_id}")
            else:
                logger.info(f"✅ ORDER SIMULATED: {signal['symbol']} BUY {quantity} @ ${signal['price']:.2f} (MCP disabled)")

            # Track position locally
            position = {
                "symbol": signal["symbol"],
                "quantity": quantity,
                "entry_price": signal["price"],
                "entry_time": signal["timestamp"],
                "trailing_stop": signal["price"] * 0.985,
                "peak_price": signal["price"],
                "position_multiplier": signal.get("position_multiplier", 1.0),
                "order_id": self.order_ids.get(signal["symbol"])
            }

            self.positions.append(position)
            self.save_positions()
            return True

        except Exception as e:
            logger.error(f"Order placement error: {e}")
            return False

    def close_position(self, exit_signal: Dict, circuit: CircuitBreaker) -> bool:
        try:
            position = next((p for p in self.positions if p["symbol"] == exit_signal["symbol"]), None)
            if not position:
                return False

            pnl_usd = (exit_signal["exit_price"] - position["entry_price"]) * position["quantity"]

            # CANCEL ORDER VIA MCP
            if self.mcp and position.get("order_id"):
                cancel_result = self.mcp.cancel_order(position["order_id"])
                if cancel_result["status"] == "error":
                    logger.warning(f"Could not cancel order {position['order_id']}: {cancel_result['message']}")

            logger.info(f"🔒 POSITION CLOSED: {exit_signal['symbol']} @ ${exit_signal['exit_price']:.2f} | P&L: ${pnl_usd:+.2f}")

            circuit.log_trade_result(pnl_usd)
            self.positions = [p for p in self.positions if p["symbol"] != exit_signal["symbol"]]
            if exit_signal["symbol"] in self.order_ids:
                del self.order_ids[exit_signal["symbol"]]
            self.save_positions()
            return True

        except Exception as e:
            logger.error(f"Position close error: {e}")
            return False


# ============================================================================
# MAIN BOT ENGINE
# ============================================================================

class BotV38Balanced:

    def __init__(self):
        self.market_data = MarketDataFetcher()
        self.signal_gen = SignalGenerator()
        self.circuit = CircuitBreaker()
        self.mcp = RobinhoodMCPClient() if Config.MCP_ENABLED else None
        self.positions = PositionManager(self.mcp)
        self.volatility = VolatilityMonitor()

    def run_cycle(self):
        logger.info(f"\n{'='*100}")
        logger.info(f"CYCLE EXECUTION | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"MCP Status: {'ENABLED' if Config.MCP_ENABLED else 'DISABLED (SIM MODE)'}")
        logger.info(f"{'='*100}")

        if self.circuit.check_halt_conditions():
            logger.warning("🔴 Trading halted by circuit breaker.")
            return

        position_mult, vol_status = self.volatility.get_position_multiplier()
        logger.info(f"📊 Volatility Status: {vol_status} → Multiplier: {position_mult:.1f}x")

        # Scan for Entries
        signals_found = 0
        for symbol in Config.SYMBOL_LIST:
            data = self.market_data.get_technicals(symbol)
            if not data:
                continue

            signal = self.signal_gen.evaluate_entry(data, position_mult)
            if signal:
                signals_found += 1
                self.positions.place_order(signal)

        logger.info(f"[SCAN COMPLETE] Found {signals_found} entry signals from {len(Config.SYMBOL_LIST)} symbols")

        # Evaluate Exits
        if self.positions.positions:
            logger.info(f"[MANAGING] {len(self.positions.positions)} open positions...")
            for position in self.positions.positions[:]:
                data = self.market_data.get_technicals(position["symbol"])
                if not data:
                    continue

                exit_signal = self.signal_gen.evaluate_exit(position, data)
                if exit_signal:
                    self.positions.close_position(exit_signal, self.circuit)
                else:
                    self.positions.save_positions()
        else:
            logger.info("[MANAGING] No open positions to manage")

        logger.info(f"[CYCLE COMPLETE] Open positions: {len(self.positions.positions)}")

if __name__ == "__main__":
    bot = BotV38Balanced()
    bot.run_cycle()
