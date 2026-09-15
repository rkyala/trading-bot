#!/usr/bin/env python3
"""
Mid-Day Email Report
Sends daily summary to email at noon
"""

import json
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

def load_config():
    """Load email config"""
    try:
        with open("email_config.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ email_config.json not found!")
        print("Create it with your Yahoo app password")
        return None

def get_current_stats():
    """Get current bot statistics"""
    try:
        with open("dry_run_logs/bot_20260820.log", "r") as f:
            content = f.read()

        # Count trades
        buy_trades = len(re.findall(r"| BUY |", content))
        skip_trades = len(re.findall(r"| SKIP |", content))

        # Get profit
        profit_matches = re.findall(r"Total profit: \+\$([0-9.]+)", content)
        total_profit = sum(float(p) for p in profit_matches) if profit_matches else 0

        # Count cycles
        cycles = len(re.findall(r"CYCLE #", content))

        return {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S CDT"),
            "buy_trades": buy_trades,
            "skip_trades": skip_trades,
            "total_profit": total_profit,
            "cycles": cycles
        }
    except:
        return None

def generate_email_body(stats):
    """Generate email HTML body"""
    if not stats:
        body = "<p>Unable to load statistics</p>"
    else:
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2 style="color: #2c3e50;">🤖 Trading Bot Mid-Day Report</h2>

            <p><strong>Time:</strong> {stats['timestamp']}</p>

            <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <h3 style="color: #27ae60;">📊 Performance Summary</h3>

                <table style="width: 100%; border-collapse: collapse;">
                    <tr style="background-color: #ecf0f1;">
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>Metric</strong></td>
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>Value</strong></td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #ddd;">Cycles Completed</td>
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>{stats['cycles']}</strong></td>
                    </tr>
                    <tr style="background-color: #f9f9f9;">
                        <td style="padding: 10px; border: 1px solid #ddd;">Buy Signals</td>
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>{stats['buy_trades']}</strong></td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #ddd;">Skipped (Below Threshold)</td>
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>{stats['skip_trades']}</strong></td>
                    </tr>
                    <tr style="background-color: #f9f9f9;">
                        <td style="padding: 10px; border: 1px solid #ddd; font-weight: bold;">Daily Profit</td>
                        <td style="padding: 10px; border: 1px solid #ddd; font-weight: bold; color: #27ae60;">+${stats['total_profit']:.2f}</td>
                    </tr>
                </table>
            </div>

            <div style="background-color: #e8f8f5; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #27ae60;">
                <h3 style="color: #27ae60;">✅ Status</h3>
                <p>
                    <strong>Bot Version:</strong> v3.5 (Fibonacci + Stochastic)<br>
                    <strong>Mode:</strong> Dry-run (Week-long validation)<br>
                    <strong>Deployment:</strong> Live on Monday 8/26<br>
                    <strong>Next Cycle:</strong> ~30 minutes
                </p>
            </div>

            <div style="background-color: #fef5e7; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #f39c12;">
                <h3 style="color: #f39c12;">📈 Exit Strategy</h3>
                <p>
                    Positions are being monitored hourly for exits:<br>
                    • Profit Target: +1.5%<br>
                    • Stop Loss: -1.5%<br>
                    • Time Exit: 4 hours<br>
                    • Trailing Stop: +0.5% after gain<br><br>
                    <strong>Dashboard:</strong> <a href="http://localhost:8890">http://localhost:8890</a>
                </p>
            </div>

            <hr style="margin: 30px 0; border: none; border-top: 1px solid #ddd;">

            <p style="font-size: 12px; color: #95a5a6;">
                This is an automated report from your trading bot.<br>
                Next report: Tomorrow at 12:00 PM CDT
            </p>
        </body>
        </html>
        """

    return body

def send_email(config, stats):
    """Send email report"""
    try:
        # Generate email content
        subject = f"🤖 Trading Bot Mid-Day Report - {datetime.now().strftime('%Y-%m-%d')}"
        body = generate_email_body(stats)

        # Create email
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = config["email_address"]
        msg["To"] = config["email_address"]

        # Attach HTML
        msg.attach(MIMEText(body, "html"))

        # Send email
        print(f"📧 Connecting to {config['smtp_server']}...")
        with smtplib.SMTP_SSL(config["smtp_server"], config["smtp_port"]) as server:
            server.login(config["email_address"], config["email_password"])
            server.send_message(msg)

        print(f"✅ Email sent to {config['email_address']}")
        print(f"   Subject: {subject}")
        return True

    except Exception as e:
        print(f"❌ Email failed: {e}")
        return False

def main():
    """Main function"""
    print("📧 Mid-Day Email Report Generator\n")

    # Load config
    config = load_config()
    if not config:
        return False

    # Get stats
    print("📊 Fetching statistics...")
    stats = get_current_stats()
    if not stats:
        print("❌ Could not fetch statistics")
        return False

    print(f"   Cycles: {stats['cycles']}")
    print(f"   Trades: {stats['buy_trades']}")
    print(f"   Profit: +${stats['total_profit']:.2f}")
    print()

    # Send email
    return send_email(config, stats)

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
