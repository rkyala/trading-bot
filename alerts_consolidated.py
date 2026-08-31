#!/usr/bin/env python3
"""
Consolidated Alert System - Every 15 Minutes
Scans all 22 symbols, groups by verdict, sends ONE consolidated Discord message
"""

import json
import logging
from datetime import datetime
from pathlib import Path
import yfinance as yf
import numpy as np
import requests
from requests import Session

from enhanced_alert_engine import EnhancedAlertEngine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/alerts_consolidated.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# Shared HTTP session for connection pooling & reuse
DISCORD_SESSION = Session()

# Configuration
EQUITY_WATCHLIST = ["TSLA", "NVDA", "AAPL", "MSFT", "AMZN", "AMD", "COIN", "AVGO", "MRVL", "SOXL", "IWM", "QQQ", "GOOG", "MRNA", "GLD", "SLV", "UNH"]
FUTURES_WATCHLIST = ["/ES", "/NQ", "/GC", "/CL", "/ZB"]
WATCHLIST = EQUITY_WATCHLIST + FUTURES_WATCHLIST

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1543798306650722374/hXV_yVr3S7VdHzMOGCkFoNhYxeukGQzTY7kW70lVpDC6Ei0my9OJ6elV6n4A37fclnXa"

def get_yfinance_symbol(symbol: str) -> str:
    """Convert symbol to yfinance format"""
    if symbol.startswith("/"):
        # Futures: /ES -> ES=F
        return symbol[1:] + "=F"
    return symbol

def scan_symbol(symbol: str, engine: EnhancedAlertEngine) -> dict:
    """Scan single symbol and return alert data or None"""
    try:
        yf_symbol = get_yfinance_symbol(symbol)
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period="60d", interval="1d")

        if df.empty or len(df) < 20:
            return None

        df.columns = [col.lower() for col in df.columns]

        price = float(df['close'].iloc[-1])

        # Calculate RSI (FIXED: handle avg_loss=0 case)
        closes = df['close'].values
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-14:])
        avg_loss = np.mean(losses[-14:])

        if avg_loss == 0:
            rsi = 100.0 if avg_gain > 0 else 50.0  # Pure gains = overbought RSI 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # Calculate RVOL
        current_vol = float(df['volume'].iloc[-1])
        avg_vol = float(df['volume'].rolling(20).mean().iloc[-1])
        rvol = current_vol / avg_vol if avg_vol > 0 else 1.0

        # Calculate ATR
        high_vals = df['high'].values
        low_vals = df['low'].values
        close_vals = df['close'].values
        high_low = high_vals - low_vals
        high_close = np.abs(high_vals - np.roll(close_vals, 1))
        low_close = np.abs(low_vals - np.roll(close_vals, 1))
        tr = np.maximum(high_low, np.maximum(high_close, low_close))
        atr = float(np.mean(tr[-14:]))

        # EMA/SMA
        ema_20 = df['close'].ewm(span=20, adjust=False).mean().iloc[-1]
        sma_200 = df['close'].rolling(200).mean().iloc[-1] if len(df) >= 200 else df['close'].mean()

        # Generate alert
        alert = engine.generate_alert(
            symbol=symbol,
            entry=price,
            stop_loss=price - (1.5 * atr),
            take_profit=price + (3.0 * atr),
            rvol=rvol,
            rsi=rsi,
            ema20=ema_20,
            sma200=sma_200
        )

        return alert

    except Exception as e:
        log.warning(f"Error scanning {symbol}: {e}")
        return None

def send_consolidated_alert(high_conv: list, caution: list, skip: list):
    """Send HIGH CONVICTION alerts as MULTIPLE messages (2-3) to avoid truncation"""
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S CDT')
        total_scanned = len(high_conv) + len(caution) + len(skip)
        from enhanced_alert_engine import EnhancedAlertEngine

        messages_sent = 0

        # MESSAGE 1: HIGH CONVICTION - FIRST BATCH (TOP 2-3)
        if high_conv:
            high_detail = ""
            batch_size = 3 if len(high_conv) >= 3 else len(high_conv)

            for alert in high_conv[:batch_size]:
                entry = f"**{alert['symbol']}** | {alert.get('verdict', 'EXECUTE')}\n"
                entry += f"Entry: ${alert['entry']:.2f} | Stop: ${alert['stop_loss']:.2f} | Target: ${alert['take_profit']:.2f}\n"
                entry += f"R/R: {alert['risk_reward']:.2f}:1 | RSI: {alert['rsi']:.1f} | RVOL: {alert['rvol']:.2f}x | Conf: {alert['confidence']}%\n"

                # Options flow + strategy
                if "options" in alert:
                    opt = alert["options"]
                    opt_text = EnhancedAlertEngine.interpret_options_flow(opt)
                    if opt_text:
                        entry += f"📊 P/C {opt['pc_ratio']} | Vol/OI {opt['vol_oi_ratio']}x | IV {opt['avg_iv']}%\n"
                        entry += f"   → {opt_text}\n"

                    if "opt_strategy" in alert:
                        strat = alert["opt_strategy"]
                        entry += f"🎯 Opt: `{strat['strategy']}` ({strat['strikes']})\n"

                entry += "\n"
                high_detail += entry

            embed1 = {
                "title": f"📈 Alert Scan - HIGH CONVICTION • {timestamp}",
                "color": 3066993,  # Green
                "description": high_detail[:2000],  # Discord description limit
                "footer": {"text": f"Alpha Engine v2.4 | Showing {batch_size}/{len(high_conv)} HIGH CONVICTION"}
            }

            payload1 = {
                "username": "Alert Scanner",
                "avatar_url": "https://cdn-icons-png.flaticon.com/512/3050/3050159.png",
                "embeds": [embed1]
            }

            resp = DISCORD_SESSION.post(DISCORD_WEBHOOK, json=payload1, timeout=10)
            if resp.status_code in [200, 204]:
                messages_sent += 1

        # MESSAGE 2: HIGH CONVICTION - REMAINING (if > batch_size)
        if len(high_conv) > batch_size:
            remaining_text = ""
            for alert in high_conv[batch_size:]:
                remaining_text += f"**{alert['symbol']}**: ${alert['entry']:.2f} | R/R {alert['risk_reward']:.2f}:1 | Conf {alert['confidence']}%\n"
                if "options" in alert:
                    opt = alert["options"]
                    remaining_text += f"  📊 P/C {opt['pc_ratio']} | IV {opt['avg_iv']}%\n"
                remaining_text += "\n"

            embed2 = {
                "title": f"✅ HIGH CONVICTION - Additional ({len(high_conv) - batch_size})",
                "color": 3066993,
                "description": remaining_text[:2000]
            }

            payload2 = {
                "username": "Alert Scanner",
                "avatar_url": "https://cdn-icons-png.flaticon.com/512/3050/3050159.png",
                "embeds": [embed2]
            }

            resp = DISCORD_SESSION.post(DISCORD_WEBHOOK, json=payload2, timeout=10)
            if resp.status_code in [200, 204]:
                messages_sent += 1

        # MESSAGE 3: CAUTION + SUMMARY
        summary_text = ""
        if caution:
            summary_text += "⚠️ **CAUTION**\n"
            for alert in caution[:5]:
                summary_text += f"• **{alert['symbol']}**: ${alert['entry']:.2f} | Conf {alert['confidence']}%\n"
            if len(caution) > 5:
                summary_text += f"... +{len(caution) - 5} more\n"
            summary_text += "\n"

        summary_text += f"📊 **Summary**: Scanned 22/22 | 🟢 HIGH: {len(high_conv)} | ⚠️ CAUTION: {len(caution)} | ❌ SKIP: {len(skip)}"

        embed3 = {
            "title": "📊 Scan Summary",
            "color": 3447003,  # Blue
            "description": summary_text
        }

        payload3 = {
            "username": "Alert Scanner",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/3050/3050159.png",
            "embeds": [embed3]
        }

        resp = DISCORD_SESSION.post(DISCORD_WEBHOOK, json=payload3, timeout=10)
        if resp.status_code in [200, 204]:
            messages_sent += 1

        if messages_sent > 0:
            log.info(f"✅ Sent {messages_sent} messages: {len(high_conv)} HIGH, {len(caution)} CAUTION, {len(skip)} SKIP")
            return True
        else:
            log.error(f"❌ Discord error: no messages sent")
            return False

    except Exception as e:
        log.error(f"❌ Failed to send alerts: {e}")
        return False

def run_consolidated_scan():
    """Run consolidated 15-minute scan"""
    log.info("="*80)
    log.info("🔍 CONSOLIDATED ALERT SCAN - 22 SYMBOLS")
    log.info("="*80)

    engine = EnhancedAlertEngine(account_balance=50000, risk_pct_per_trade=1.0)

    high_conviction = []
    caution = []
    skip = []

    # Scan all symbols
    for symbol in WATCHLIST:
        alert = scan_symbol(symbol, engine)

        if alert:
            verdict = alert.get('verdict', '')

            if 'HIGH CONVICTION' in verdict:
                high_conviction.append(alert)
            elif 'CAUTION' in verdict:
                caution.append(alert)
            else:  # SKIP
                skip.append(alert)

    log.info(f"\n✅ Scan complete:")
    log.info(f"   HIGH CONVICTION: {len(high_conviction)}")
    log.info(f"   CAUTION: {len(caution)}")
    log.info(f"   SKIP: {len(skip)}")

    # Send consolidated alert
    send_consolidated_alert(high_conviction, caution, skip)

    log.info("="*80)

if __name__ == "__main__":
    Path("logs").mkdir(exist_ok=True)
    run_consolidated_scan()
