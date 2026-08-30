#!/usr/bin/env python3
"""
Day Trading Alerts System - Phase 1
Generates 5-minute technical signals and sends email alerts

Usage:
    python alerts_system.py
"""

import json
import logging
import smtplib
from datetime import datetime, timedelta
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from schwab_quotes import SchwabQuotes
from alerts_technical import TechnicalAnalysis

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/alerts.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# Configuration
WATCHLIST = ["TSLA", "NVDA", "AAPL", "MSFT", "AMZN", "GME", "AMD", "COIN", "SHOP", "ABNB"]
CONFIDENCE_THRESHOLD = 65  # Minimum confidence to send alert
ALERT_COOLDOWN_MINUTES = 30  # Don't send same alert more than once per 30 min
STATE_FILE = "alerts_state.json"

# Email configuration
EMAIL_CONFIG = {
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "sender_email": "your_email@gmail.com",  # UPDATE THIS
    "sender_password": "your_app_password",  # UPDATE THIS (use Gmail app password)
    "recipient_email": "kris.yalala@yahoo.com"
}

class AlertsState:
    """Track alert timestamps to prevent spam"""

    def __init__(self):
        self.file = STATE_FILE
        self.state = self.load()

    def load(self) -> dict:
        """Load state from JSON"""
        try:
            if Path(self.file).exists():
                with open(self.file, "r") as f:
                    return json.load(f)
        except Exception as e:
            log.warning(f"Could not load state: {e}")
        return {}

    def save(self):
        """Save state to JSON"""
        try:
            with open(self.file, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            log.error(f"Could not save state: {e}")

    def should_alert(self, symbol: str) -> bool:
        """Check if enough time has passed since last alert"""
        last_alert = self.state.get(symbol)
        if not last_alert:
            return True

        last_time = datetime.fromisoformat(last_alert)
        cooldown = datetime.now() - timedelta(minutes=ALERT_COOLDOWN_MINUTES)

        return last_time < cooldown

    def record_alert(self, symbol: str):
        """Record alert timestamp"""
        self.state[symbol] = datetime.now().isoformat()
        self.save()


class AlertSystem:
    """Main alerts engine"""

    def __init__(self):
        self.schwab = SchwabQuotes()
        self.ta = TechnicalAnalysis()
        self.state = AlertsState()

    def get_5min_candles(self, symbol: str, count: int = 60) -> list:
        """Get last N 5-minute candles"""
        try:
            candles = self.schwab.get_historical(symbol, period="5min")
            if candles:
                # Return last 'count' candles
                return candles[-count:]
            return None
        except Exception as e:
            log.error(f"Error fetching candles for {symbol}: {e}")
            return None

    def scan_symbol(self, symbol: str) -> dict:
        """Scan single symbol and return alert if qualified"""
        try:
            # Get current price
            price = self.schwab.get_quote(symbol)
            if not price:
                log.warning(f"Could not fetch price for {symbol}")
                return None

            # Get 5-min candles
            candles = self.get_5min_candles(symbol, count=60)
            if not candles:
                log.warning(f"Could not fetch candles for {symbol}")
                return None

            # Score signal
            signal = self.ta.score_signal(symbol, candles, price)

            # Check if alert-worthy
            if signal.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
                signal["price"] = price
                signal["timestamp"] = datetime.now().isoformat()
                return signal

            return None

        except Exception as e:
            log.error(f"Error scanning {symbol}: {e}")
            return None

    def send_email_alert(self, alerts: list):
        """Send email with all alerts"""
        if not alerts:
            return

        try:
            # Build email body
            subject = f"🟢 {len(alerts)} Day Trading Alert(s) - {datetime.now().strftime('%I:%M %p')}"

            html_body = f"""
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; }}
        table {{ border-collapse: collapse; margin-top: 20px; }}
        td, th {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
        .high {{ color: green; font-weight: bold; }}
        .medium {{ color: orange; font-weight: bold; }}
        .low {{ color: red; }}
    </style>
</head>
<body>
    <h2>Day Trading Alerts</h2>
    <p>Generated: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}</p>

    <table>
        <tr>
            <th>Symbol</th>
            <th>Price</th>
            <th>Confidence</th>
            <th>Signal</th>
        </tr>
"""

            for alert in alerts:
                symbol = alert.get("symbol", "?")
                price = alert.get("price", 0)
                confidence = alert.get("confidence", 0)
                reason = alert.get("reason", "")

                conf_class = "high" if confidence >= 75 else "medium" if confidence >= 65 else "low"

                html_body += f"""
        <tr>
            <td>{symbol}</td>
            <td>${price:.2f}</td>
            <td class="{conf_class}">{confidence}%</td>
            <td>{reason}</td>
        </tr>
"""

            html_body += """
    </table>

    <p style="margin-top: 20px; font-size: 12px; color: #666;">
        Alerts generated by day_trading_alerts v1.0<br/>
        Next scan: 5 minutes
    </p>
</body>
</html>
"""

            # Send email
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = EMAIL_CONFIG["sender_email"]
            msg["To"] = EMAIL_CONFIG["recipient_email"]

            part = MIMEText(html_body, "html")
            msg.attach(part)

            with smtplib.SMTP(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"]) as server:
                server.starttls()
                server.login(EMAIL_CONFIG["sender_email"], EMAIL_CONFIG["sender_password"])
                server.sendmail(
                    EMAIL_CONFIG["sender_email"],
                    EMAIL_CONFIG["recipient_email"],
                    msg.as_string()
                )

            log.info(f"✅ Sent email alert with {len(alerts)} signals")

        except Exception as e:
            log.error(f"Error sending email: {e}")

    def run_scan(self):
        """Run full scan on all symbols in watchlist"""
        log.info(f"🔍 Scanning {len(WATCHLIST)} symbols...")

        alerts = []

        for symbol in WATCHLIST:
            signal = self.scan_symbol(symbol)

            if signal and self.state.should_alert(symbol):
                alerts.append(signal)
                self.state.record_alert(symbol)
                log.info(f"✅ ALERT: {symbol} {signal['confidence']}% - {signal['reason']}")

        # Send combined email
        if alerts:
            self.send_email_alert(alerts)
        else:
            log.info("No alerts generated this cycle")

        log.info(f"✅ Scan complete. Next scan in 5 minutes.\n")


def main():
    """Main entry point"""
    log.info("=" * 80)
    log.info("DAY TRADING ALERTS - PHASE 1 (Technical Signals)")
    log.info("=" * 80)

    # Ensure logs directory exists
    Path("logs").mkdir(exist_ok=True)

    # Run scan
    alerts = AlertSystem()
    alerts.run_scan()


if __name__ == "__main__":
    main()
