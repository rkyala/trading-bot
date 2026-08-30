#!/usr/bin/env python3
"""
Schwab Real-Time Quotes & Historical Data
For day_trading_alerts: Fetch live prices and OHLCV candles for technical analysis
"""

import json
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

class SchwabQuotes:
    """Fetch real-time quotes and historical data from Schwab API"""

    def __init__(self):
        self.config = self.load_config()
        self.access_token = None
        self.token_expires = None
        self.token_file = "schwab_token.json"
        self.load_cached_token()

    def load_config(self):
        """Load Schwab API config"""
        try:
            with open("schwab_config.json", "r") as f:
                return json.load(f)
        except FileNotFoundError:
            log.error("schwab_config.json not found!")
            return None

    def load_cached_token(self):
        """Load previously cached access token"""
        try:
            with open(self.token_file, "r") as f:
                data = json.load(f)
                self.access_token = data.get("access_token")
                expires_str = data.get("expires")
                if expires_str:
                    self.token_expires = datetime.fromisoformat(expires_str)
                log.info(f"✅ Loaded cached Schwab token")
        except:
            log.info("No cached token found, will get new one")

    def save_cached_token(self):
        """Save access token for reuse"""
        try:
            data = {
                "access_token": self.access_token,
                "expires": self.token_expires.isoformat() if self.token_expires else None
            }
            with open(self.token_file, "w") as f:
                json.dump(data, f)
        except:
            pass

    def get_access_token(self):
        """Get access token from Schwab using auth code"""
        if self.access_token and self.token_expires and datetime.now() < self.token_expires:
            log.debug("✅ Using cached access token")
            return self.access_token

        if not self.config:
            log.error("Config not loaded")
            return None

        try:
            log.info("🔐 Exchanging auth code for access token...")

            payload = {
                "grant_type": "authorization_code",
                "code": self.config["auth_code"],
                "redirect_uri": self.config["redirect_uri"],
                "client_id": self.config["client_id"],
                "client_secret": self.config["client_secret"]
            }

            response = requests.post(
                self.config["token_url"],
                data=payload,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get("access_token")
                expires_in = data.get("expires_in", 1800)  # Default 30 min
                self.token_expires = datetime.now() + timedelta(seconds=expires_in)

                log.info(f"✅ Got access token (expires in {expires_in}s)")
                self.save_cached_token()
                return self.access_token
            else:
                log.error(f"❌ Token exchange failed: {response.status_code}")
                log.error(f"Response: {response.text}")
                return None

        except Exception as e:
            log.error(f"❌ Error getting token: {e}")
            return None

    def get_quote(self, symbol: str) -> Optional[float]:
        """Get real-time quote for a symbol"""
        token = self.get_access_token()
        if not token:
            log.warning(f"No token, cannot fetch quote for {symbol}")
            return None

        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            }

            params = {
                "symbols": symbol,
                "fields": "quote"
            }

            response = requests.get(
                self.config["quotes_url"],
                headers=headers,
                params=params,
                timeout=5
            )

            if response.status_code == 200:
                data = response.json()

                # Schwab returns data as {symbol: {quote: {data}}}
                if symbol in data:
                    quote = data[symbol].get("quote", {})
                    price = quote.get("lastPrice") or quote.get("mark")

                    if price:
                        log.debug(f"✅ Schwab {symbol}: ${price}")
                        return price
                    else:
                        log.warning(f"No price in Schwab response for {symbol}")
                        return None
                else:
                    log.warning(f"Symbol {symbol} not in Schwab response")
                    return None
            else:
                log.warning(f"Schwab API error {response.status_code} for {symbol}")
                return None

        except Exception as e:
            log.warning(f"Error fetching {symbol} from Schwab: {e}")
            return None

    def get_quotes_batch(self, symbols: List[str]) -> Dict[str, float]:
        """Get quotes for multiple symbols at once (more efficient)"""
        token = self.get_access_token()
        if not token:
            return {}

        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            }

            # Schwab allows comma-separated symbols
            symbols_str = ",".join(symbols)
            params = {
                "symbols": symbols_str,
                "fields": "quote"
            }

            response = requests.get(
                self.config["quotes_url"],
                headers=headers,
                params=params,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                prices = {}

                for symbol in symbols:
                    if symbol in data:
                        quote = data[symbol].get("quote", {})
                        price = quote.get("lastPrice") or quote.get("mark")
                        if price:
                            prices[symbol] = price

                log.info(f"✅ Schwab batch: {len(prices)}/{len(symbols)} quotes")
                return prices
            else:
                log.warning(f"Schwab batch API error: {response.status_code}")
                return {}

        except Exception as e:
            log.warning(f"Error fetching batch from Schwab: {e}")
            return {}

    def get_historical(self, symbol: str, period: str = "5min") -> Optional[List[Dict]]:
        """
        Get historical OHLCV data for technical analysis

        period: "5min", "15min", "30min", "60min", "daily"
        Returns: List of candles with [time, open, high, low, close, volume]
        """
        token = self.get_access_token()
        if not token:
            log.warning(f"No token, cannot fetch historical for {symbol}")
            return None

        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            }

            # Map period to Schwab format
            period_map = {
                "5min": "every5min",
                "15min": "every15min",
                "30min": "every30min",
                "60min": "every1hour",
                "daily": "daily"
            }

            schwab_period = period_map.get(period, "daily")

            # For intraday: get last 60 candles (5 hours of 5-min data)
            if period in ["5min", "15min", "30min"]:
                lookback_days = 5  # Get 5 days of data to cover any gaps
            else:
                lookback_days = 60  # 60 days for daily/weekly analysis

            end_date = datetime.now()
            start_date = end_date - timedelta(days=lookback_days)

            params = {
                "symbol": symbol,
                "periodType": "day",
                "period": lookback_days,
                "frequencyType": schwab_period,
                "frequency": 1,
                "endDate": int(end_date.timestamp() * 1000),
                "startDate": int(start_date.timestamp() * 1000),
                "needExtendedHoursData": False
            }

            response = requests.get(
                self.config["historicals_url"],
                headers=headers,
                params=params,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()

                if "candles" in data:
                    candles = data["candles"]
                    log.info(f"✅ Schwab historical: {symbol} got {len(candles)} candles ({period})")
                    return candles
                else:
                    log.warning(f"No candles in Schwab response for {symbol}")
                    return None
            else:
                log.warning(f"Schwab historical API error {response.status_code} for {symbol}")
                return None

        except Exception as e:
            log.warning(f"Error fetching historical for {symbol}: {e}")
            return None


# Test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    schwab = SchwabQuotes()

    # Test single quote
    print("\n📊 Testing Schwab quotes...")
    price = schwab.get_quote("AAPL")
    print(f"AAPL: ${price}\n" if price else "AAPL: Failed\n")

    # Test batch
    symbols = ["TSLA", "NVDA", "AAPL", "MSFT"]
    prices = schwab.get_quotes_batch(symbols)
    for symbol, price in prices.items():
        print(f"{symbol}: ${price:.2f}")

    # Test historical
    print("\n📈 Testing historical data...")
    historical = schwab.get_historical("TSLA", period="5min")
    if historical:
        print(f"Got {len(historical)} 5-min candles for TSLA")
        print(f"Latest: {historical[-1]}")
