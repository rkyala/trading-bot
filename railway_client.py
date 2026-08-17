#!/usr/bin/env python3
"""
Railway Client: Send trading decisions from Mac to Railway executor

Part of Option B: Hybrid Architecture
- Mac: Runs bot.py with Llama 2, sends decisions
- Railway: Runs mcp_executor.py, executes trades
"""

import os
import requests
import logging
from datetime import datetime

log = logging.getLogger(__name__)


class RailwayClient:
    """Client for sending trading decisions to Railway executor"""

    def __init__(self, railway_url=None, timeout=10):
        """
        Initialize Railway client

        Args:
            railway_url: URL of Railway executor (e.g., https://your-app.railway.app)
            timeout: Request timeout in seconds
        """
        self.railway_url = railway_url or os.getenv("RAILWAY_EXECUTOR_URL")
        self.timeout = timeout
        self.enabled = bool(self.railway_url)

        if self.enabled:
            log.info(f"✅ Railway client initialized: {self.railway_url}")
        else:
            log.warning("⚠️  Railway URL not configured, will execute locally")

    def is_available(self):
        """Check if Railway executor is reachable"""
        if not self.enabled:
            return False

        try:
            response = requests.get(
                f"{self.railway_url}/health",
                timeout=5
            )
            return response.status_code == 200
        except Exception as e:
            log.warning(f"Railway health check failed: {e}")
            return False

    def send_decisions(self, decisions):
        """
        Send trading decisions to Railway executor

        Args:
            decisions: List of decision dicts:
                [
                    {"symbol": "INTC", "action": "BUY", "confidence": 81},
                    {"symbol": "AMD", "action": "BUY", "confidence": 75}
                ]

        Returns:
            {
                "status": "success" | "error" | "offline",
                "executed": 2,
                "results": [...]
            }
        """

        if not decisions:
            return {
                "status": "skipped",
                "message": "No decisions to send"
            }

        if not self.enabled:
            return {
                "status": "offline",
                "message": "Railway URL not configured",
                "decisions_count": len(decisions)
            }

        try:
            log.info(f"Sending {len(decisions)} decision(s) to Railway...")

            response = requests.post(
                f"{self.railway_url}/execute_trades",
                json={"decisions": decisions},
                timeout=self.timeout
            )

            if response.status_code == 200:
                result = response.json()
                log.info(f"✅ Railway executed {result.get('executed', 0)}/{len(decisions)} trades")
                return result
            else:
                log.error(f"Railway error: {response.status_code} - {response.text}")
                return {
                    "status": "error",
                    "message": f"Railway returned {response.status_code}",
                    "decisions_count": len(decisions)
                }

        except requests.exceptions.Timeout:
            log.error("Railway request timed out")
            return {
                "status": "error",
                "message": "Request timeout",
                "decisions_count": len(decisions)
            }

        except requests.exceptions.ConnectionError as e:
            log.error(f"Cannot connect to Railway: {e}")
            return {
                "status": "error",
                "message": "Cannot connect to Railway executor",
                "decisions_count": len(decisions)
            }

        except Exception as e:
            log.error(f"Unexpected error: {e}")
            return {
                "status": "error",
                "message": str(e),
                "decisions_count": len(decisions)
            }

    def check_status(self):
        """Check Railway executor status"""
        if not self.enabled:
            return {
                "status": "offline",
                "message": "Railway URL not configured"
            }

        try:
            response = requests.get(
                f"{self.railway_url}/status",
                timeout=5
            )
            return response.json()
        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }


# ============================================================================
# FALLBACK: LOCAL EXECUTION (if Railway unavailable)
# ============================================================================

def execute_locally(decisions):
    """
    Fallback: Execute decisions locally if Railway unavailable

    For now, just logs decisions. In future, could use direct MCP.
    """
    log.info(f"Executing {len(decisions)} decision(s) locally (Railway offline)")

    results = []
    for decision in decisions:
        result = {
            "status": "local_execution",
            "symbol": decision.get("symbol"),
            "action": decision.get("action"),
            "confidence": decision.get("confidence"),
            "message": "Executed locally (Railway offline)"
        }
        results.append(result)
        log.info(f"  {decision['symbol']} {decision['action']} (confidence: {decision['confidence']}%)")

    return {
        "status": "local",
        "executed": len(decisions),
        "results": results
    }


# ============================================================================
# TEST
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    print("\n" + "="*70)
    print("  RAILWAY CLIENT TEST")
    print("="*70 + "\n")

    # Initialize client
    client = RailwayClient()

    print(f"Railway URL: {client.railway_url or 'NOT SET'}")
    print(f"Enabled: {client.enabled}\n")

    # Check status
    print("Checking Railway status...")
    status = client.check_status()
    print(f"Status: {status}\n")

    # Test with sample decisions
    test_decisions = [
        {"symbol": "INTC", "action": "BUY", "confidence": 81},
        {"symbol": "AMD", "action": "BUY", "confidence": 75},
    ]

    print(f"Sending {len(test_decisions)} test decision(s)...")
    result = client.send_decisions(test_decisions)
    print(f"Result: {result}\n")

    print("="*70 + "\n")
