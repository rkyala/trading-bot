#!/usr/bin/env python3
"""
Charles Schwab Market Data Fetcher
Drop-in replacement for yfinance using official Schwab API
Calculates same technicals (ADX, Stochastic) from Schwab candles
"""

import json
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

try:
    import schwab
    from schwab.client import Client
except ImportError:
    print("ERROR: schwab-py not installed. Run: pip3.10 install schwab-py")
    exit(1)

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

CREDENTIALS_FILE = Path("schwab_credentials.json")
TOKEN_CACHE_FILE = Path("schwab_token.json")

if not CREDENTIALS_FILE.exists():
    print("❌ ERROR: schwab_credentials.json not found")
    exit(1)

CREDS = json.loads(CREDENTIALS_FILE.read_text())
API_KEY = CREDS["client_id"]
APP_SECRET = CREDS["client_secret"]
CALLBACK_URL = CREDS["redirect_uri"]
ACCOUNT_NUMBER = CREDS["account_number"]

# ============================================================================
# SCHWAB MARKET DATA FETCHER
# ============================================================================

class SchwabMarketDataFetcher:
    """Fetch live market data and technical indicators using Charles Schwab API"""

    _client = None  # Singleton client instance
    _cache = {}  # Cache for technicals (same as yfinance version)
    _cache_ttl_seconds = 300  # 5-minute cache

    @classmethod
    def _get_client(cls):
        """Get or create authenticated Schwab client (lazy initialization)"""
        if cls._client is not None:
            return cls._client

        logger.info("🔐 Authenticating with Charles Schwab API...")

        try:
            # Try to load cached token first
            if TOKEN_CACHE_FILE.exists():
                logger.info("📦 Loading cached OAuth token...")
                cls._client = schwab.auth.client_from_token_file(
                    token_path=str(TOKEN_CACHE_FILE),
                    api_key=API_KEY,
                    app_secret=APP_SECRET
                )
                logger.info("✅ Authenticated using cached token")
                return cls._client
        except Exception as e:
            logger.debug(f"Cache load failed: {e}, attempting browser auth...")

        try:
            # Perform OAuth2 flow (opens browser)
            logger.info("📱 Opening browser for Schwab OAuth authorization...")
            cls._client = schwab.auth.client_from_manual_flow(
                api_key=API_KEY,
                app_secret=APP_SECRET,
                callback_url=CALLBACK_URL,
                token_path=str(TOKEN_CACHE_FILE)
            )
            logger.info("✅ Authenticated via browser OAuth")
            return cls._client

        except Exception as e:
            logger.error(f"❌ Authentication failed: {e}")
            raise

    @staticmethod
    def get_price_history_df(symbol: str, period_type, period, frequency_type, frequency) -> pd.DataFrame:
        """
        Fetch price history from Schwab and convert to pandas DataFrame
        Handles both daily and minute-based frequencies
        """
        try:
            client = SchwabMarketDataFetcher._get_client()

            # Call appropriate API method based on frequency type
            if frequency_type == Client.PriceHistory.FrequencyType.DAILY:
                resp = client.get_price_history_every_day(
                    symbol,
                    period_type=period_type,
                    period=period,
                    frequency_type=frequency_type,
                    frequency=frequency
                )
            else:
                # Minute-based (1m, 5m, 30m, 60m)
                resp = client.get_price_history_every_minute(
                    symbol,
                    period_type=period_type,
                    period=period,
                    frequency_type=frequency_type,
                    frequency=frequency
                )

            data = resp.json()

            if "candles" not in data or not data["candles"]:
                logger.warning(f"⏭️  [{symbol}] No candle data returned from Schwab")
                return pd.DataFrame()

            # Convert to DataFrame
            df = pd.DataFrame(data["candles"])

            # Schwab returns timestamps in milliseconds epoch
            df['datetime'] = pd.to_datetime(df['datetime'], unit='ms')

            # Rename columns to match yfinance format
            df.rename(
                columns={
                    'open': 'Open',
                    'high': 'High',
                    'low': 'Low',
                    'close': 'Close',
                    'volume': 'Volume'
                },
                inplace=True
            )

            return df.dropna()

        except Exception as e:
            logger.error(f"❌ Price history fetch failed for {symbol}: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_technicals(symbol: str, use_cache: bool = True) -> Optional[Dict]:
        """
        Fetch Schwab candles and calculate Daily ADX and 30-Minute Stochastic
        Returns same dict format as yfinance version for drop-in compatibility

        Returns:
        {
            "symbol": "AAPL",
            "price": 150.30,
            "adx": 42.1,
            "stoch_k": 78.5,
            "stoch_d": 75.2,
            "high_14": 151.50,
            "low_14": 149.50,
            "range_14": 2.00
        }
        """
        try:
            # OPTIMIZATION: Check cache before fetching
            if use_cache and symbol in SchwabMarketDataFetcher._cache:
                cached_time, cached_data = SchwabMarketDataFetcher._cache[symbol]
                age_seconds = (datetime.now() - cached_time).total_seconds()
                if age_seconds < SchwabMarketDataFetcher._cache_ttl_seconds:
                    logger.debug(f"📦 [{symbol}] Using cached Schwab data (age: {age_seconds:.0f}s)")
                    return cached_data

            logger.info(f"📊 Fetching Schwab technicals for {symbol}...")

            # 1. Fetch Daily Candles for ADX (60 days lookback)
            df_daily = SchwabMarketDataFetcher.get_price_history_df(
                symbol,
                period_type=Client.PriceHistory.PeriodType.MONTH,
                period=2,  # ~60 days
                frequency_type=Client.PriceHistory.FrequencyType.DAILY,
                frequency=Client.PriceHistory.Frequency.DAILY
            )

            if len(df_daily) < 20:
                logger.warning(f"⏭️  [{symbol}] Insufficient daily candles: {len(df_daily)} < 20")
                return None

            # Calculate ADX from daily candles (same algorithm as yfinance version)
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

            plus_dm_d = pd.Series(
                np.where((up_d > down_d) & (up_d > 0), up_d, 0),
                index=df_daily.index
            )
            minus_dm_d = pd.Series(
                np.where((down_d > up_d) & (down_d > 0), down_d, 0),
                index=df_daily.index
            )

            plus_di_d = 100 * (plus_dm_d.rolling(14).mean() / atr_d)
            minus_di_d = 100 * (minus_dm_d.rolling(14).mean() / atr_d)
            di_diff_d = (plus_di_d - minus_di_d).abs()
            adx_d = di_diff_d.rolling(14).mean()

            # 2. Fetch 30-Minute Candles for Intraday Stochastic
            df_30m = SchwabMarketDataFetcher.get_price_history_df(
                symbol,
                period_type=Client.PriceHistory.PeriodType.DAY,
                period=5,  # Last 5 days
                frequency_type=Client.PriceHistory.FrequencyType.MINUTE,
                frequency=Client.PriceHistory.Frequency.EVERY_THIRTY_MINUTES
            )

            if len(df_30m) < 30:
                logger.warning(f"⏭️  [{symbol}] Insufficient 30m candles: {len(df_30m)} < 30")
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

            # 3. Get Real-Time Live Quote (most accurate current price)
            client = SchwabMarketDataFetcher._get_client()
            quote_resp = client.get_quote(symbol).json()

            if symbol not in quote_resp:
                logger.warning(f"⏭️  [{symbol}] No quote data available")
                return None

            current_price = quote_resp[symbol]['quote']['lastPrice']

            # Build result (same format as yfinance version)
            result_data = {
                "symbol": symbol,
                "price": float(current_price),
                "adx": float(adx_d.iloc[-1]),
                "stoch_k": float(stoch_k.iloc[-1]),
                "stoch_d": float(stoch_d.iloc[-1]),
                "high_14": float(high_max.iloc[-1]),
                "low_14": float(low_min.iloc[-1]),
                "range_14": float(range_hl.iloc[-1])
            }

            # Validate no NaN values
            for key, value in result_data.items():
                if pd.isna(value):
                    logger.warning(f"⚠️  [{symbol}] NaN in {key} - skipping")
                    return None

            # Cache the result
            if use_cache:
                SchwabMarketDataFetcher._cache[symbol] = (datetime.now(), result_data)
                logger.debug(f"📦 [{symbol}] Cached Schwab data for {SchwabMarketDataFetcher._cache_ttl_seconds}s")

            logger.info(f"✅ [{symbol}] ADX: {result_data['adx']:.1f} | Stoch: {result_data['stoch_k']:.1f}")

            return result_data

        except Exception as e:
            logger.error(f"❌ Error analyzing {symbol} via Schwab: {e}")
            return None


# ============================================================================
# TEST (FOR VERIFICATION)
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(message)s'
    )

    logger.info("🧪 Testing SchwabMarketDataFetcher")
    logger.info("=" * 80)

    # Test symbols
    test_symbols = ["AAPL", "MSFT", "GOOGL"]

    for symbol in test_symbols:
        logger.info(f"\n📊 Fetching {symbol}...")
        result = SchwabMarketDataFetcher.get_technicals(symbol, use_cache=False)

        if result:
            logger.info(f"✅ {symbol}:")
            logger.info(f"   Price: ${result['price']:.2f}")
            logger.info(f"   ADX: {result['adx']:.2f}")
            logger.info(f"   Stoch K: {result['stoch_k']:.2f}")
            logger.info(f"   Stoch D: {result['stoch_d']:.2f}")
        else:
            logger.warning(f"⏭️  {symbol}: Failed to fetch")

    logger.info("\n✅ Test complete!")
