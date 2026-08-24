#!/usr/bin/env python3
"""
Trading Bot - Robinhood Agentic Trading MCP
Connects via HTTPS/SSE to Robinhood's official Agentic MCP endpoint
Live trading enabled through remote MCP protocol
"""

import json
import logging
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
import pandas as pd
import numpy as np
import yfinance as yf
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler('bot_agentic_mcp.log')]
)
logger = logging.getLogger(__name__)

# ============================================================================
# ROBINHOOD AGENTIC MCP CLIENT
# ============================================================================

class AgenticMCPClient:
    """Client for Robinhood Agentic Trading MCP via HTTPS/SSE"""

    def __init__(self, mcp_url: str, access_token: str):
        """
        Initialize connection to Robinhood Agentic MCP endpoint

        Args:
            mcp_url: Robinhood Agentic MCP endpoint (https://agentic.robinhood.com/v1/mcp/...)
            access_token: OAuth access token from rh_oauth.json
        """
        self.mcp_url = mcp_url.rstrip('/')
        self.access_token = access_token
        self.req_id = 1

        # Setup session with retries
        self.session = requests.Session()
        retry = Retry(connect=3, backoff_factor=0.5)
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount('https://', adapter)

        logger.info(f"[+] Connecting to Robinhood Agentic MCP: {self.mcp_url[:50]}...")
        self._verify_connection()
        logger.info("✅ Connected to Robinhood Agentic MCP\n")

    def _verify_connection(self):
        """Verify MCP endpoint is accessible"""
        headers = self._get_headers()
        try:
            # List available tools to verify connection
            resp = self._rpc("tools/list", {})
            if "result" in resp and "tools" in resp["result"]:
                return True
            elif "error" in resp:
                logger.error(f"MCP Error: {resp['error']}")
                return False
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    def _get_headers(self) -> dict:
        """Get headers for MCP API requests"""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def _rpc(self, method: str, params: dict = None) -> dict:
        """
        Send JSON-RPC 2.0 request to Robinhood Agentic MCP endpoint

        Args:
            method: RPC method (e.g., "tools/list", "tools/call")
            params: Parameters for the method

        Returns:
            JSON-RPC response
        """
        req = {
            "jsonrpc": "2.0",
            "id": self.req_id,
            "method": method,
            "params": params or {}
        }
        self.req_id += 1

        try:
            headers = self._get_headers()

            # POST to MCP endpoint
            response = self.session.post(
                f"{self.mcp_url}/messages",
                json=req,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"MCP Request Error: {e}")
            return {"error": str(e)}
        except json.JSONDecodeError as e:
            logger.error(f"MCP Response Parse Error: {e}")
            return {"error": str(e)}

    def place_order(self, symbol: str, qty: int, side: str = "buy", price: float = None):
        """Place order via Robinhood Agentic MCP"""
        arguments = {
            "symbol": symbol,
            "quantity": qty,
            "side": side,
            "time_in_force": "day",
            "order_type": "market" if not price else "limit"
        }
        if price:
            arguments["price"] = round(price, 2)

        return self._rpc("tools/call", {
            "name": "place_equity_order",
            "arguments": arguments
        })

    def get_positions(self):
        """Get current positions"""
        return self._rpc("tools/call", {
            "name": "get_equity_positions",
            "arguments": {}
        })

    def get_portfolio(self):
        """Get portfolio summary"""
        return self._rpc("tools/call", {
            "name": "get_portfolio",
            "arguments": {}
        })

# ============================================================================
# TRADING STRATEGY
# ============================================================================

class TradingBot:
    """Mean-reversion trading strategy using Robinhood Agentic MCP"""

    SYMBOLS = ['NVDA', 'TSLA', 'AMD', 'AAPL', 'MSFT', 'GOOGL', 'META', 'NFLX', 'QCOM', 'AVGO']
    ACCOUNT_SIZE = 10000
    POSITION_SIZE_PCT = 0.005  # 0.5% = $50 per trade

    def __init__(self, mcp_client: AgenticMCPClient):
        self.mcp = mcp_client
        self.positions = {}

    def analyze_symbol(self, symbol: str) -> Tuple[Optional[str], Optional[float]]:
        """
        Analyze symbol for mean-reversion signal
        Returns: (signal_type, entry_price) or (None, None)
        """
        try:
            # Download data
            data = yf.download(symbol, period='60d', progress=False)
            close = data['Close']
            high = data['High']
            low = data['Low']

            if len(data) < 50:
                return None, None

            # Calculate ADX (simple approximation)
            adx = self._calculate_adx(data)

            # Calculate Stochastic
            stoch_k, stoch_d = self._calculate_stochastic(close)

            # Calculate Fibonacci
            lookback = 20
            period_high = high[-lookback:].max()
            period_low = low[-lookback:].min()
            range_val = period_high - period_low
            fib_38 = period_high - (range_val * 0.382)
            fib_50 = period_high - (range_val * 0.5)
            fib_62 = period_high - (range_val * 0.618)

            current_price = close.iloc[-1]

            # Entry signal: ADX > 20, Stoch < 30, price at Fibonacci
            if adx > 20 and stoch_k < 30:
                if fib_38 - 2 <= current_price <= fib_62 + 2:
                    return "BUY", current_price

            return None, None
        except Exception as e:
            logger.warning(f"Error analyzing {symbol}: {e}")
            return None, None

    def _calculate_adx(self, data: pd.DataFrame) -> float:
        """Calculate ADX (simple version)"""
        high = data['High']
        low = data['Low']
        close = data['Close']

        plus_dm = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)

        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)

        atr = tr.rolling(14).mean()
        di_plus = 100 * (plus_dm.rolling(14).mean() / atr)
        di_minus = 100 * (minus_dm.rolling(14).mean() / atr)
        di_diff = (di_plus - di_minus).abs()
        adx = di_diff.rolling(14).mean()

        return adx.iloc[-1]

    def _calculate_stochastic(self, close: pd.Series) -> Tuple[float, float]:
        """Calculate Stochastic Oscillator"""
        lookback = 14
        high = close.rolling(lookback).max()
        low = close.rolling(lookback).min()

        k = 100 * ((close - low) / (high - low))
        d = k.rolling(3).mean()

        return k.iloc[-1], d.iloc[-1]

    def run_cycle(self):
        """Execute one trading cycle"""
        logger.info("=" * 80)
        logger.info(f"CYCLE | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | ROBINHOOD AGENTIC MCP")
        logger.info("=" * 80)

        signals_found = 0

        for symbol in self.SYMBOLS:
            signal, price = self.analyze_symbol(symbol)

            if signal == "BUY":
                signals_found += 1
                qty = max(1, int((self.ACCOUNT_SIZE * self.POSITION_SIZE_PCT) / price))

                logger.info(f"📈 SIGNAL: {symbol} {signal} {qty} @ ${price:.2f}")

                # Place order via Agentic MCP
                response = self.mcp.place_order(symbol, qty, "buy", price)
                logger.info(f"   Response: {response}")

                if "result" in response:
                    result = response["result"]
                    if "error" not in result:
                        logger.info(f"   ✅ Order placed: {result}")
                    else:
                        logger.warning(f"   ⚠️  {result['error']}")
                elif "error" in response:
                    logger.warning(f"   ❌ Error: {response['error']}")

        logger.info(f"📋 Scanned {len(self.SYMBOLS)} | Found {signals_found} signals")
        logger.info("=" * 80 + "\n")

# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main entry point"""

    # Load OAuth credentials
    oauth_file = Path('rh_oauth.json')
    if not oauth_file.exists():
        logger.error("❌ rh_oauth.json not found. Run get_token.py first.")
        sys.exit(1)

    try:
        with open(oauth_file) as f:
            oauth = json.load(f)
        access_token = oauth.get('access_token')
        if not access_token:
            logger.error("❌ No access_token in rh_oauth.json")
            sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Error loading OAuth: {e}")
        sys.exit(1)

    # Get MCP URL from environment
    mcp_url = os.getenv('ROBINHOOD_MCP_URL')
    if not mcp_url:
        logger.error("❌ ROBINHOOD_MCP_URL not set. Set it with:")
        logger.error("   export ROBINHOOD_MCP_URL='https://agentic.robinhood.com/v1/mcp/...'")
        sys.exit(1)

    # Initialize MCP client
    try:
        mcp = AgenticMCPClient(mcp_url, access_token)
    except Exception as e:
        logger.error(f"❌ Failed to connect to Agentic MCP: {e}")
        sys.exit(1)

    # Initialize bot and run
    try:
        bot = TradingBot(mcp)
        bot.run_cycle()
    except KeyboardInterrupt:
        logger.info("\n[*] Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Bot error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
