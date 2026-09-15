#!/usr/bin/env python3
"""
Schwab Real-Time Quotes
Fetches live stock prices from Charles Schwab API
"""

import json
import logging
import requests
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

class SchwabQuotes:
    """Fetch real-time quotes from Schwab API"""

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
            log.info("✅ Using cached access token")
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

    def get_quote(self, symbol):
        """Get real-time quote for a symbol"""
        token = self.get_access_token()
        if not token:
            log.warning(f"No token, falling back to yfinance for {symbol}")
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

    def get_quotes_batch(self, symbols):
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


# Test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    schwab = SchwabQuotes()

    # Test single quote
    print("\n📊 Testing Schwab quotes...")
    price = schwab.get_quote("AAPL")
    print(f"AAPL: ${price}\n" if price else "AAPL: Failed\n")

    # Test batch
    symbols = ["AAPL", "MSFT", "NVDA", "TSLA"]
    prices = schwab.get_quotes_batch(symbols)
    for symbol, price in prices.items():
        print(f"{symbol}: ${price:.2f}")
