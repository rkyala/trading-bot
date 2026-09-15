#!/usr/bin/env python3
"""
Live Data Test: v3.8 Strategy on Real Market Data
Shows what the bot sees today without placing orders
"""

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

class V38LiveTest:
    """v3.8 Strategy testing on live market data"""

    def __init__(self):
        self.signals = []
        self.tested = 0

    def test_symbol(self, symbol):
        """Test one symbol on live data"""
        try:
            self.tested += 1
            logger.info(f"\n[{self.tested}/10] {symbol}")

            # Fetch 180 days of data
            hist = yf.download(symbol, period="180d", progress=False)
            if len(hist) < 50:
                logger.info(f"  ❌ Not enough data")
                return

            close = hist['Close'].values
            current_price = float(close[-1])

            # Simple moving averages
            sma_20 = float(np.mean(close[-20:]))
            sma_50 = float(np.mean(close[-50:]))

            # Simple trend detection
            recent_high = float(np.max(close[-20:]))
            recent_low = float(np.min(close[-20:]))

            # Price position
            price_pct_from_high = ((recent_high - current_price) / recent_high) * 100
            price_pct_from_low = ((current_price - recent_low) / (recent_high - recent_low)) * 100

            logger.info(f"  Price: ${current_price:.2f} | SMA20: ${sma_20:.2f} | SMA50: ${sma_50:.2f}")
            logger.info(f"  20-day High: ${recent_high:.2f} | Low: ${recent_low:.2f}")

            # v3.8 Entry Signals
            signal = None
            reason = ""

            # Breakout: price > SMA20 by 2%, and close to 20-day high
            if current_price > sma_20 * 1.02 and price_pct_from_high < 5:
                signal = "BREAKOUT"
                reason = f"Price above SMA20, near 20-day high ({price_pct_from_high:.1f}% down)"
                logger.info(f"  ✅ BREAKOUT SIGNAL: {reason}")

            # Mean reversion: price < SMA50, near 20-day low
            elif current_price < sma_50 * 0.98 and price_pct_from_low < 20:
                signal = "MEAN_REVERSION"
                reason = f"Price below SMA50, near 20-day low ({price_pct_from_low:.1f}% up)"
                logger.info(f"  ✅ MEAN REVERSION: {reason}")

            else:
                logger.info(f"  ❌ No signal (price at {price_pct_from_low:.0f}% of 20-day range)")

            if signal:
                self.signals.append({
                    'symbol': symbol,
                    'price': current_price,
                    'signal': signal,
                    'reason': reason,
                    'sma20': sma_20,
                    'sma50': sma_50
                })

        except Exception as e:
            logger.warning(f"  Error: {str(e)[:80]}")

    def run(self):
        """Run live data test"""
        # Top 50 NASDAQ
        nasdaq_top = [
            "NVDA", "MSFT", "AAPL", "TSLA", "AMZN", "META", "GOOGL", "GOOG", "AVGO", "NFLX",
            "QCOM", "AMD", "INTC", "ASML", "CSCO", "ADBE", "INTU", "AMAT", "LRCX", "KLAC",
            "MU", "SNPS", "CDNS", "MCHP", "NXPI", "PYPL", "CRWD", "ZS", "DDOG", "NET",
            "PSTG", "SNOW", "OKTA", "SPLK", "VEEV", "MSTR", "DOCU", "DBX", "COIN", "RIOT",
            "MARA", "MRVL", "UPST", "ULTI", "SGEN", "ALKS", "ZENV", "PRPL", "ROKU", "FUBO"
        ]

        # Top 50 S&P 500 (by market cap)
        sp500_top = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "BERKB", "META", "MAGNIFICO", "JNJ",
            "V", "WMT", "JPM", "PG", "MA", "HD", "DIS", "COST", "KO", "AVGO",
            "MCD", "BAC", "ABBV", "ASML", "NVO", "INTC", "VZ", "CMCSA", "ACN", "MRK",
            "ADBE", "PEP", "LLY", "MMM", "AMGN", "AXP", "HON", "IBM", "QCOM", "CVX",
            "XOM", "UNH", "RTX", "CAT", "BA", "GE", "INTU", "CSCO", "CRM", "LOW"
        ]

        symbols = list(set(nasdaq_top + sp500_top))[:100]  # Unique symbols, max 100

        logger.info("\n" + "="*100)
        logger.info("LIVE DATA TEST: What Would v3.8 Trade Today?")
        logger.info("Real market data, no orders placed")
        logger.info("="*100)

        for symbol in symbols:
            self.test_symbol(symbol)

        # Summary
        logger.info("\n" + "="*100)
        logger.info("LIVE DATA TEST RESULTS")
        logger.info("="*100)
        logger.info(f"Symbols Tested: {len(symbols)}")
        logger.info(f"Tradeable Setups Found: {len(self.signals)}")

        if self.signals:
            logger.info(f"\n{'='*100}")
            logger.info("ENTRY SIGNALS (Would place $50 orders on Aug 26)")
            logger.info(f"{'='*100}")
            for sig in self.signals:
                logger.info(f"  {sig['symbol']:6} @ ${sig['price']:7.2f} | {sig['signal']:20} | {sig['reason']}")
        else:
            logger.info(f"\n❌ No signals today")
            logger.info("   Market conditions don't match v3.8 filters")
            logger.info("   (This is normal - bot is selective, not every day has setups)")

        logger.info("="*100)
        logger.info("✅ LIVE DATA TEST COMPLETE - Bot ready for Aug 26\n")

if __name__ == "__main__":
    tester = V38LiveTest()
    tester.run()
