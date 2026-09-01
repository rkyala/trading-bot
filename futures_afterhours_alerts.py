#!/usr/bin/env python3
"""
Futures After-Hours Alerts (5 PM - 12 AM CDT)
Monitors /GC, /NQ, /SIL, /CL for trading opportunities
"""

import sys
import json
import logging
import os
from datetime import datetime, timedelta
import requests
import pandas as pd
import numpy as np

sys.path.insert(0, '/Users/ramayalala/trading_bot')

from schwab_marketdata_fetcher import SchwabMarketDataFetcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)

class FuturesAlerter:
    def __init__(self):
        self.fetcher = SchwabMarketDataFetcher()
        self.futures_symbols = {
            '/GC': 'Gold',
            '/NQ': 'Nasdaq 100',
            '/SIL': 'Silver',
            '/CL': 'Crude Oil'
        }
        # Use existing Discord webhook for alerts
        self.discord_webhook = "https://discord.com/api/webhooks/1543798306650722374/hXV_yVr3S7VdHzMOGCkFoNhYxeukGQzTY7kW70lVpDC6Ei0my9OJ6elV6n4A37fclnXa"
        self.alerts = []

    def is_afterhours(self):
        """Check if current time is within 5 PM - 12 AM CDT"""
        now = datetime.now()
        hour = now.hour

        # CDT is UTC-5, but we're already in local time
        # 5 PM = 17:00, 12 AM = 00:00
        # So alert window is 17:00-23:59 (same day) or 00:00-00:59 (next day)
        if hour >= 17 or hour < 1:
            return True
        return False

    def fetch_futures_data(self, symbol):
        """Fetch recent 30-min data for futures"""
        try:
            # Map /GC to Schwab symbol (GCUZ26, etc - need to handle current contract)
            # For now, try direct symbol
            df = self.fetcher.get_price_history_df(symbol, frequency='thirty_min')

            if df is None or len(df) < 10:
                return None

            return df.tail(50)
        except Exception as e:
            log.warning(f"⚠️ {symbol}: {e}")
            return None

    def calculate_indicators(self, df):
        """Calculate technical indicators"""
        df = df.copy()
        df.columns = [col.capitalize() if col.lower() in ['close', 'open', 'high', 'low', 'volume']
                      else col for col in df.columns]

        # RSI
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df['RSI'] = 100 - (100 / (1 + rs))

        # MACD
        ema12 = df['Close'].ewm(span=12).mean()
        ema26 = df['Close'].ewm(span=26).mean()
        df['MACD'] = ema12 - ema26
        df['Signal'] = df['MACD'].ewm(span=9).mean()
        df['MACD_Hist'] = df['MACD'] - df['Signal']

        # Bollinger Bands
        df['BB_Mid'] = df['Close'].rolling(20).mean()
        bb_std = df['Close'].rolling(20).std()
        df['BB_Upper'] = df['BB_Mid'] + (bb_std * 2)
        df['BB_Lower'] = df['BB_Mid'] - (bb_std * 2)
        df['BB_Percent'] = (df['Close'] - df['BB_Lower']) / (df['BB_Upper'] - df['BB_Lower'] + 1e-9)

        # ATR
        high_low = df['High'] - df['Low']
        high_close = (df['High'] - df['Close'].shift()).abs()
        low_close = (df['Low'] - df['Close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(14).mean()

        # Stochastic
        low_min = df['Low'].rolling(14).min()
        high_max = df['High'].rolling(14).max()
        df['Stoch'] = 100 * ((df['Close'] - low_min) / (high_max - low_min + 1e-9))

        df = df.fillna(method='ffill').fillna(method='bfill')
        return df

    def generate_alert(self, symbol, name, price, rsi, macd, stoch, atr):
        """Generate alert if conditions met"""
        alerts = []

        # Overbought pullback (potential short)
        if rsi > 70 and macd < 0:
            alerts.append({
                'type': '🔴 SHORT',
                'reason': f'Overbought (RSI {rsi:.0f}) + negative MACD',
                'target': 'Reversal to lower BB'
            })

        # Oversold bounce (potential long)
        if rsi < 30 and macd > 0:
            alerts.append({
                'type': '🟢 LONG',
                'reason': f'Oversold (RSI {rsi:.0f}) + positive MACD',
                'target': 'Bounce to mid-BB'
            })

        # Strong momentum (overbought but climbing)
        if rsi > 65 and macd > 0 and stoch > 70:
            alerts.append({
                'type': '🟢 MOMENTUM',
                'reason': 'Strong uptrend forming',
                'target': 'Continue to upper BB'
            })

        # Weakness (oversold and falling)
        if rsi < 35 and macd < 0 and stoch < 30:
            alerts.append({
                'type': '🔴 WEAKNESS',
                'reason': 'Downtrend confirmed',
                'target': 'Test lower support'
            })

        # High volatility (big ATR move)
        if atr > np.percentile([0.1, 0.5, 1.0, 2.0, 5.0], 75):  # Top quartile
            alerts.append({
                'type': '⚡ VOLATILE',
                'reason': f'High volatility (ATR {atr:.2f})',
                'target': 'Watch for breakout'
            })

        return alerts

    def send_discord_alert(self, symbol, name, price, alerts, rsi, macd, stoch):
        """Send alert to Discord"""
        if not self.discord_webhook or not alerts:
            return

        try:
            embed = {
                'title': f'{symbol} - {name}',
                'color': 16711680 if any('SHORT' in a['type'] for a in alerts) else 65280,
                'fields': [
                    {'name': 'Price', 'value': f'${price:.2f}', 'inline': True},
                    {'name': 'RSI', 'value': f'{rsi:.1f}', 'inline': True},
                    {'name': 'MACD', 'value': f'{macd:.4f}', 'inline': True},
                ],
                'description': '\n'.join([f"{a['type']}: {a['reason']}" for a in alerts])
            }

            payload = {
                'embeds': [embed],
                'username': 'Futures Alerts'
            }

            requests.post(self.discord_webhook, json=payload, timeout=5)
            log.info(f"✅ Discord alert sent: {symbol}")
        except Exception as e:
            log.warning(f"⚠️ Discord send failed: {e}")

    def run(self):
        """Execute alert cycle"""
        if not self.is_afterhours():
            log.info(f"⏭️ Outside alert window (5 PM - 12 AM CDT)")
            return

        log.info("\n" + "="*80)
        log.info("FUTURES AFTER-HOURS ALERTS")
        log.info("="*80)

        for symbol, name in self.futures_symbols.items():
            log.info(f"\n📊 {symbol} ({name})")

            # Fetch data
            df = self.fetch_futures_data(symbol)
            if df is None:
                log.warning(f"⏭️ No data available")
                continue

            # Calculate indicators
            df = self.calculate_indicators(df)
            latest = df.iloc[-1]

            price = latest['Close']
            rsi = latest['RSI']
            macd = latest['MACD']
            stoch = latest['Stoch']
            atr = latest['ATR']

            log.info(f"  Price: ${price:.2f} | RSI: {rsi:.1f} | MACD: {macd:.4f} | Stoch: {stoch:.0f}")

            # Generate alerts
            alerts = self.generate_alert(symbol, name, price, rsi, macd, stoch, atr)

            if alerts:
                log.info(f"  🚨 ALERTS:")
                for alert in alerts:
                    log.info(f"     {alert['type']}: {alert['reason']}")
                    log.info(f"     → {alert['target']}")

                # Send to Discord
                self.send_discord_alert(symbol, name, price, alerts, rsi, macd, stoch)
            else:
                log.info(f"  ✅ No alerts (neutral conditions)")

        log.info("\n" + "="*80)
        log.info("Alert cycle complete")
        log.info("="*80 + "\n")

if __name__ == "__main__":
    alerter = FuturesAlerter()
    alerter.run()
