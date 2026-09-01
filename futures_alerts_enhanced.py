#!/usr/bin/env python3
"""
Enhanced Futures Alerts with Institutional Flow Detection
Monitors: /GC, /SIL, /CL, /ZB (Bonds), DXY with BUY/SELL verdicts
5 PM - 12 AM CDT with entry/exit levels
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

class InstitutionalFuturesAlerter:
    def __init__(self):
        self.fetcher = SchwabMarketDataFetcher()
        self.futures_symbols = {
            '/GC': {'name': 'Gold', 'type': 'metal'},
            '/SIL': {'name': 'Silver', 'type': 'metal'},
            '/CL': {'name': 'Crude Oil', 'type': 'energy'},
            '/ZB': {'name': '10Y Bond', 'type': 'fixed_income'},
            'DXY': {'name': 'US Dollar Index', 'type': 'currency'}
        }
        self.discord_webhook = "https://discord.com/api/webhooks/1543798306650722374/hXV_yVr3S7VdHzMOGCkFoNhYxeukGQzTY7kW70lVpDC6Ei0my9OJ6elV6n4A37fclnXa"
        self.alerts = []

    def is_afterhours(self):
        """Check if current time is within 5 PM - 12 AM CDT"""
        now = datetime.now()
        hour = now.hour
        if hour >= 17 or hour < 1:
            return True
        return False

    def fetch_futures_data(self, symbol):
        """Fetch recent 30-min data for futures"""
        try:
            df = self.fetcher.get_price_history_df(symbol, frequency='thirty_min')
            if df is None or len(df) < 20:
                return None
            return df.tail(100)
        except Exception as e:
            log.warning(f"⚠️ {symbol}: {e}")
            return None

    def calculate_indicators(self, df):
        """Calculate technical indicators + volume analysis"""
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

        # ATR (volatility)
        high_low = df['High'] - df['Low']
        high_close = (df['High'] - df['Close'].shift()).abs()
        low_close = (df['Low'] - df['Close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(14).mean()

        # Stochastic
        low_min = df['Low'].rolling(14).min()
        high_max = df['High'].rolling(14).max()
        df['Stoch'] = 100 * ((df['Close'] - low_min) / (high_max - low_min + 1e-9))

        # Volume Analysis (institutional accumulation/distribution)
        if 'Volume' in df.columns:
            df['Volume_MA'] = df['Volume'].rolling(20).mean()
            df['Volume_Ratio'] = df['Volume'] / df['Volume_MA']
            # On-Balance Volume
            df['OBV'] = (np.sign(df['Close'].diff()) * df['Volume']).fillna(0).cumsum()
        else:
            df['Volume_Ratio'] = 1.0
            df['OBV'] = 0

        # Price momentum (institutional buying/selling pressure)
        df['Momentum'] = df['Close'].pct_change(5) * 100  # 5-period momentum

        df = df.fillna(method='ffill').fillna(method='bfill')
        return df

    def detect_institutional_flow(self, df, symbol):
        """Detect institutional accumulation/distribution"""
        latest = df.iloc[-1]
        prev = df.iloc[-5]

        volume_spike = latest['Volume_Ratio'] > 1.5  # Volume above average
        price_momentum = latest['Momentum']
        obv_trend = latest['OBV'] > prev['OBV']  # OBV increasing

        # Institutional BUY: Volume spike + positive momentum + rising OBV
        inst_buy = volume_spike and price_momentum > 0.5 and obv_trend

        # Institutional SELL: Volume spike + negative momentum + falling OBV
        inst_sell = volume_spike and price_momentum < -0.5 and not obv_trend

        return {
            'buy': inst_buy,
            'sell': inst_sell,
            'volume_spike': volume_spike,
            'momentum': price_momentum,
            'obv_rising': obv_trend
        }

    def generate_alert(self, symbol, name, price, rsi, macd, stoch, atr, df):
        """Generate comprehensive alert with institutional flow"""
        alerts = []
        latest = df.iloc[-1]

        # Detect institutional flow
        inst_flow = self.detect_institutional_flow(df, symbol)

        # ==== INSTITUTIONAL BUY SIGNALS ====
        if inst_flow['buy']:
            alerts.append({
                'type': '🟢 INSTITUTIONAL BUY',
                'reason': f"Volume spike + positive momentum ({inst_flow['momentum']:.2f}%) + rising OBV",
                'entry': f'Buy dips at {price * 0.99:.2f}',
                'exit': f'Stop at {price * 0.97:.2f}, Target {price * 1.03:.2f}',
                'verdict': '🟢 STRONG BUY - Institutional Accumulation',
                'confidence': 'HIGH'
            })

        # ==== INSTITUTIONAL SELL SIGNALS ====
        if inst_flow['sell']:
            alerts.append({
                'type': '🔴 INSTITUTIONAL SELL',
                'reason': f"Volume spike + negative momentum ({inst_flow['momentum']:.2f}%) + falling OBV",
                'entry': f'Short rallies near {price * 1.01:.2f}',
                'exit': f'Cover at {price * 1.03:.2f}, Stop at {price * 1.05:.2f}',
                'verdict': '🔴 STRONG SELL - Institutional Distribution',
                'confidence': 'HIGH'
            })

        # ==== MOMENTUM TRADES (without institutional confirmation) ====
        # Strong uptrend with overbought potential
        if rsi > 65 and macd > 0 and stoch > 70 and not inst_flow['sell']:
            alerts.append({
                'type': '🟢 MOMENTUM BUY',
                'reason': f'Strong uptrend (RSI {rsi:.0f}, MACD +, Stoch {stoch:.0f})',
                'entry': f'Buy on pullbacks near {price * 0.995:.2f}',
                'exit': f'Trail stop 2%, Target {price * 1.05:.2f}',
                'verdict': '🟢 BUY MOMENTUM - Ride the trend',
                'confidence': 'MEDIUM'
            })

        # Downtrend with oversold bounce
        if rsi < 35 and macd < 0 and stoch < 30 and not inst_flow['buy']:
            alerts.append({
                'type': '🔴 DOWNTREND',
                'reason': f'Downtrend confirmed (RSI {rsi:.0f}, MACD -, Stoch {stoch:.0f})',
                'entry': f'Short on rallies near {price * 1.005:.2f}',
                'exit': f'Cover at {price * 1.02:.2f}, Stop at {price * 1.04:.2f}',
                'verdict': '🔴 SELL PRESSURE - Downtrend',
                'confidence': 'MEDIUM'
            })

        # Overbought reversal (no institutional buy)
        if rsi > 70 and macd < 0 and not inst_flow['buy']:
            alerts.append({
                'type': '🔴 OVERBOUGHT REVERSAL',
                'reason': f'Overbought (RSI {rsi:.0f}) with bearish MACD divergence',
                'entry': f'Short below {price:.2f}',
                'exit': f'Target {price * 0.98:.2f}, Stop {price * 1.02:.2f}',
                'verdict': '🔴 SHORT SETUP - Mean reversion',
                'confidence': 'MEDIUM'
            })

        # Oversold bounce (no institutional sell)
        if rsi < 30 and macd > 0 and not inst_flow['sell']:
            alerts.append({
                'type': '🟢 OVERSOLD BOUNCE',
                'reason': f'Oversold (RSI {rsi:.0f}) with bullish MACD',
                'entry': f'Buy near {price:.2f}',
                'exit': f'Target {price * 1.03:.2f}, Stop {price * 0.98:.2f}',
                'verdict': '🟢 BUY SETUP - Bounce play',
                'confidence': 'MEDIUM'
            })

        # Extreme volatility alert
        atr_high = np.percentile(df['ATR'], 80)
        if atr > atr_high:
            alerts.append({
                'type': '⚡ HIGH VOLATILITY',
                'reason': f'Extreme volatility detected (ATR {atr:.2f})',
                'entry': 'Breakout play - wait for direction confirmation',
                'exit': f'Tight stop {atr * 1.5:.2f} away from entry',
                'verdict': '⚡ CAUTION - Wide ranges, use tight stops',
                'confidence': 'INFO'
            })

        return alerts

    def send_discord_alert(self, symbol, name, price, alerts, rsi, macd, stoch, inst_flow):
        """Send rich Discord embed with full trading details"""
        if not self.discord_webhook or not alerts:
            return

        try:
            for alert in alerts:
                # Color mapping by signal type
                colors = {
                    '🟢 INSTITUTIONAL BUY': 32768,     # Dark green
                    '🔴 INSTITUTIONAL SELL': 11141120,  # Dark red
                    '🟢 MOMENTUM BUY': 65280,           # Bright green
                    '🔴 DOWNTREND': 16711680,           # Bright red
                    '🔴 OVERBOUGHT REVERSAL': 16744192, # Red-orange
                    '🟢 OVERSOLD BOUNCE': 32896,        # Light green
                    '⚡ HIGH VOLATILITY': 16776960,      # Yellow
                }

                color = colors.get(alert['type'], 11447295)

                # Institutional flow details
                inst_details = []
                if inst_flow['buy'] or inst_flow['sell']:
                    inst_details.append(f"Volume Spike: {inst_flow['volume_spike']}")
                    inst_details.append(f"Momentum: {inst_flow['momentum']:+.2f}%")
                    inst_details.append(f"OBV Rising: {inst_flow['obv_rising']}")

                embed = {
                    'title': f'{symbol} - {name}',
                    'color': color,
                    'fields': [
                        {'name': '🎯 Signal', 'value': alert['type'], 'inline': False},
                        {'name': '📊 Analysis', 'value': alert['reason'], 'inline': False},
                        {'name': '💼 Institutional Flow',
                         'value': '\n'.join(inst_details) if inst_details else 'No institutional activity',
                         'inline': False},
                        {'name': '💰 Entry Level', 'value': alert['entry'], 'inline': False},
                        {'name': '🚪 Exit Strategy', 'value': alert['exit'], 'inline': False},
                        {'name': '📋 Verdict', 'value': alert['verdict'], 'inline': False},
                        {'name': '🎲 Confidence', 'value': alert['confidence'], 'inline': True},
                        {'name': 'Price', 'value': f'${price:.2f}', 'inline': True},
                        {'name': 'RSI', 'value': f'{rsi:.1f}', 'inline': True},
                        {'name': 'MACD', 'value': f'{macd:.4f}', 'inline': True},
                        {'name': 'Stoch', 'value': f'{stoch:.0f}', 'inline': True},
                    ]
                }

                payload = {
                    'embeds': [embed],
                    'username': '📊 Institutional Futures Alerts'
                }

                requests.post(self.discord_webhook, json=payload, timeout=5)

            log.info(f"✅ Discord alert sent: {symbol} ({len(alerts)} signal(s))")
        except Exception as e:
            log.warning(f"⚠️ Discord send failed: {e}")

    def run(self):
        """Execute alert cycle"""
        if not self.is_afterhours():
            log.info(f"⏭️ Outside alert window (5 PM - 12 AM CDT)")
            return

        log.info("\n" + "="*80)
        log.info("INSTITUTIONAL FUTURES ALERTS - After Hours Edition")
        log.info("="*80)

        for symbol, info in self.futures_symbols.items():
            name = info['name']
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

            log.info(f"  Price: ${price:.2f} | RSI: {rsi:.1f} | MACD: {macd:.4f} | Stoch: {stoch:.0f} | Vol: {latest['Volume_Ratio']:.2f}x")

            # Detect institutional flow
            inst_flow = self.detect_institutional_flow(df, symbol)
            if inst_flow['buy'] or inst_flow['sell']:
                flow_status = "🟢 BUY Flow" if inst_flow['buy'] else "🔴 SELL Flow"
                log.info(f"  {flow_status} (Momentum: {inst_flow['momentum']:+.2f}%)")

            # Generate alerts
            alerts = self.generate_alert(symbol, name, price, rsi, macd, stoch, atr, df)

            if alerts:
                log.info(f"  🚨 {len(alerts)} SIGNAL(S):")
                for alert in alerts:
                    log.info(f"     {alert['type']}")
                    log.info(f"     → {alert['verdict']}")

                # Send to Discord
                self.send_discord_alert(symbol, name, price, alerts, rsi, macd, stoch, inst_flow)
            else:
                log.info(f"  ✅ No alerts (neutral conditions)")

        log.info("\n" + "="*80)
        log.info("Alert cycle complete")
        log.info("="*80 + "\n")

if __name__ == "__main__":
    alerter = InstitutionalFuturesAlerter()
    alerter.run()
