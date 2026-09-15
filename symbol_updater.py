#!/usr/bin/env python3
"""
Dynamic Symbol Updater
Fetches NASDAQ top 50 + S&P 500 top 50 every trading day (24-hour cache)
Keeps symbol list fresh without manual updates
"""

import os
import json
import logging
from datetime import datetime, timedelta
import yfinance as yf

log = logging.getLogger(__name__)

class SymbolUpdater:
    """Manages dynamic symbol list updates"""

    def __init__(self, cache_file="symbol_cache.json"):
        self.cache_file = cache_file
        self.cache_dir = os.path.dirname(cache_file) if os.path.dirname(cache_file) else "."
        os.makedirs(self.cache_dir, exist_ok=True)

    def should_update(self):
        """Check if we should fetch fresh symbols (daily during market hours)"""
        if not os.path.exists(self.cache_file):
            return True  # No cache, fetch now

        try:
            with open(self.cache_file, 'r') as f:
                cache = json.load(f)

            last_update = datetime.fromisoformat(cache.get("last_updated", "2000-01-01"))
            hours_since = (datetime.now() - last_update).total_seconds() / 3600

            # Update if more than 24 hours have passed (daily refresh)
            if hours_since >= 24:
                return True

            return False
        except:
            return True

    def fetch_nasdaq_top_50(self):
        """Fetch NASDAQ top 50 companies"""
        try:
            log.info("Fetching NASDAQ top 50...")

            # Major NASDAQ constituents (tech, biotech, etc)
            nasdaq_top = [
                "AAPL", "MSFT", "NVDA", "AMZN", "TSLA", "META", "GOOGL", "GOOG", "AVGO", "CSCO",
                "AMD", "QCOM", "ADBE", "INTC", "INTU", "NFLX", "CMCSA", "ADP", "PYPL", "ASML",
                "COSTCO", "AMGN", "LRCX", "KLAC", "MCHP", "MU", "MRVL", "CDNS", "SNPS", "CTAS",
                "PAYX", "CRWD", "PALO", "ABNB", "ROST", "WDAY", "IDXX", "MTCH", "CPRT", "SBUX",
                "OKTA", "VRSK", "DDOG", "TEAM", "CDNA", "ROKU", "TRIP", "SPLK", "SNOW", "DBX"
            ]

            # Verify symbols exist by fetching a quick quote
            valid_symbols = []
            for symbol in nasdaq_top:
                try:
                    ticker = yf.Ticker(symbol)
                    info = ticker.info
                    if info.get("regularMarketPrice") or info.get("currentPrice"):
                        valid_symbols.append(symbol)
                except:
                    pass

            log.info(f"✅ NASDAQ: {len(valid_symbols)} valid symbols")
            return valid_symbols

        except Exception as e:
            log.error(f"❌ Error fetching NASDAQ: {e}")
            return []

    def fetch_sp500_top_50(self):
        """Fetch S&P 500 top 50 companies (by market cap)"""
        try:
            log.info("Fetching S&P 500 top 50...")

            # Top S&P 500 constituents (major sectors)
            sp500_top = [
                "MSFT", "AAPL", "NVDA", "AMZN", "TSLA", "META", "BERKB", "LLY", "JPM", "V",
                "JNJ", "WMT", "XOM", "MA", "PG", "HDFC", "MRK", "COST", "AVGO", "ACN",
                "CRM", "AMD", "NFLX", "ABT", "CMCSA", "ADBE", "QCOM", "INTU", "IBM", "CSCO",
                "TXN", "PYPL", "AMGN", "HON", "AXP", "BA", "INTC", "NOW", "GILD", "ORCL",
                "MU", "MMC", "ALL", "AMAT", "ASML", "GOOGL", "GOOG", "BKNG", "ELV", "DIS"
            ]

            # Verify symbols exist
            valid_symbols = []
            for symbol in sp500_top:
                try:
                    ticker = yf.Ticker(symbol)
                    info = ticker.info
                    if info.get("regularMarketPrice") or info.get("currentPrice"):
                        valid_symbols.append(symbol)
                except:
                    pass

            log.info(f"✅ S&P 500: {len(valid_symbols)} valid symbols")
            return valid_symbols

        except Exception as e:
            log.error(f"❌ Error fetching S&P 500: {e}")
            return []

    def get_symbols(self, force_update=False):
        """Get current symbol list, fetch fresh if needed"""

        # Check if we need to update
        if not force_update and not self.should_update():
            log.info("Using cached symbols (still fresh)")
            return self._load_cached_symbols()

        # Fetch fresh symbols
        log.info("Fetching fresh symbol list...")

        nasdaq = self.fetch_nasdaq_top_50()
        sp500 = self.fetch_sp500_top_50()

        # Combine and deduplicate
        all_symbols = sorted(list(set(nasdaq + sp500)))

        log.info(f"✅ Total unique symbols: {len(all_symbols)}")
        log.info(f"   NASDAQ: {len(nasdaq)}, S&P 500: {len(sp500)}, Overlap: {len(nasdaq) + len(sp500) - len(all_symbols)}")

        # Cache the result
        self._save_cached_symbols(all_symbols)

        return all_symbols

    def _save_cached_symbols(self, symbols):
        """Save symbols to cache"""
        try:
            cache_data = {
                "last_updated": datetime.now().isoformat(),
                "symbols": symbols,
                "count": len(symbols)
            }

            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)

            log.info(f"✅ Cached {len(symbols)} symbols to {self.cache_file}")
        except Exception as e:
            log.error(f"❌ Error caching symbols: {e}")

    def _load_cached_symbols(self):
        """Load symbols from cache"""
        try:
            with open(self.cache_file, 'r') as f:
                cache = json.load(f)

            symbols = cache.get("symbols", [])
            last_updated = cache.get("last_updated", "unknown")
            log.info(f"✅ Loaded {len(symbols)} symbols from cache (updated: {last_updated})")
            return symbols
        except Exception as e:
            log.error(f"❌ Error loading cache: {e}")
            return []


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(message)s'
    )

    updater = SymbolUpdater()

    # Force update to test
    symbols = updater.get_symbols(force_update=True)

    print(f"\n✅ Symbol list updated:")
    print(f"   Total: {len(symbols)}")
    print(f"   Symbols: {', '.join(symbols[:10])}... and {len(symbols)-10} more")
