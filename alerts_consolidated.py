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
    """Send ONE consolidated Discord message with HIGH CONVICTION entry/exit details (field truncation safe)"""
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S CDT')
        total_scanned = len(high_conv) + len(caution) + len(skip)

        embed_fields = []

        # HIGH CONVICTION - FULL ENTRY/EXIT DETAILS (truncated for Discord field limit)
        if high_conv:
            high_text = ""
            for alert in high_conv[:5]:  # Show top 5 with full details
                entry = f"**{alert['symbol']}** | {alert.get('verdict', 'EXECUTE')}\n"
                entry += f"Entry: ${alert['entry']:.2f} | Stop: ${alert['stop_loss']:.2f} | Target: ${alert['take_profit']:.2f}\n"
                entry += f"R/R: {alert['risk_reward']:.2f}:1 | RSI: {alert['rsi']:.1f} | RVOL: {alert['rvol']:.2f}x | Conf: {alert['confidence']}%\n"

                # Options flow metrics + interpretation (alerts only)
                if "options" in alert:
                    from enhanced_alert_engine import EnhancedAlertEngine
                    opt = alert["options"]
                    opt_text = EnhancedAlertEngine.interpret_options_flow(opt)
                    if opt_text:
                        entry += f"📊 P/C {opt['pc_ratio']} | Vol/OI {opt['vol_oi_ratio']}x | IV {opt['avg_iv']}%\n"
                        entry += f"   → {opt_text}\n"

                    # Options strategy recommendation (for alerts only - user reference)
                    if "opt_strategy" in alert:
                        strat = alert["opt_strategy"]
                        entry += f"🎯 Opt Play: `{strat['strategy']}` ({strat['strikes']})\n"
                        entry += f"   💡 {strat['rationale']}\n"

                entry += "\n"
                high_text += entry

            if len(high_conv) > 5:
                high_text += f"... +{len(high_conv) - 5} more HIGH CONVICTION trades"

            # TRUNCATE for Discord 1024-char field limit
            high_text = high_text[:1020] + ("..." if len(high_text) > 1020 else "")

            embed_fields.append({
                "name": f"✅ HIGH CONVICTION ({len(high_conv)})",
                "value": high_text,
                "inline": False
            })

        # CAUTION - BRIEF (truncated)
        if caution:
            caution_text = ""
            for alert in caution[:3]:  # Show top 3 briefly
                caution_text += f"• **{alert['symbol']}**: ${alert['entry']:.2f} | Conf {alert['confidence']}% | {alert.get('verdict', 'Caution')}\n"

            if len(caution) > 3:
                caution_text += f"... +{len(caution) - 3} more"

            # TRUNCATE for Discord 1024-char field limit
            caution_text = caution_text[:1000] + ("..." if len(caution_text) > 1000 else "")

            embed_fields.append({
                "name": f"⚠️ CAUTION ({len(caution)})",
                "value": caution_text,
                "inline": False
            })

        # Summary
        embed_fields.append({
            "name": "📊 Scan Summary",
            "value": f"Scanned **{total_scanned}/22** | 🟢 HIGH: {len(high_conv)} | ⚠️ CAUTION: {len(caution)} | ❌ SKIP: {len(skip)}",
            "inline": False
        })

        # Determine color based on results
        embed_color = 3066993 if high_conv else (15158332 if caution else 3447003)  # Green/Red/Blue

        # Discord embed with field-based structure (safer than description)
        embed = {
            "title": f"📈 Alert Scan - HIGH CONVICTION • {timestamp}",
            "color": embed_color,
            "fields": embed_fields,
            "footer": {"text": "Alpha Engine v2.4 | 15-Min Consolidated Scan"}
        }

        payload = {
            "username": "Alert Scanner",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/3050/3050159.png",
            "embeds": [embed]
        }

        # Use shared session for connection pooling
        response = DISCORD_SESSION.post(DISCORD_WEBHOOK, json=payload, timeout=10)

        if response.status_code in [200, 204]:
            log.info(f"✅ Consolidated alert sent: {len(high_conv)} HIGH, {len(caution)} CAUTION, {len(skip)} SKIP")
            return True
        else:
            log.error(f"❌ Discord error {response.status_code}: {response.text[:200]}")
            return False

    except Exception as e:
        log.error(f"❌ Failed to send alert: {e}")
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
