#!/usr/bin/env python3
"""
Test direct Robinhood API call to verify OAuth token works for trading.
"""
import os
import json
import requests
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

RH_ACCOUNT = "432591949"
RH_CLIENT_ID = os.environ.get("RH_CLIENT_ID", "")
RH_REFRESH_TOKEN = os.environ.get("RH_REFRESH_TOKEN", "")
RH_TOKEN_URL = "https://api.robinhood.com/oauth2/token/"

def get_rh_token():
    """Get Robinhood OAuth token."""
    if not RH_CLIENT_ID or not RH_REFRESH_TOKEN:
        log.error("Missing OAuth credentials: RH_CLIENT_ID=%s, RH_REFRESH_TOKEN=%s",
                 bool(RH_CLIENT_ID), bool(RH_REFRESH_TOKEN))
        return None

    try:
        r = requests.post(RH_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": RH_REFRESH_TOKEN,
            "client_id": RH_CLIENT_ID,
        }, timeout=10)

        if r.status_code != 200:
            log.error("Token refresh failed: %s - %s", r.status_code, r.text[:200])
            return None

        token = r.json().get("access_token")
        log.info("✅ Got Robinhood token: %s...", token[:20] if token else "NONE")
        return token
    except Exception as e:
        log.error("Error getting token: %s", e)
        return None

def check_robinhood_api():
    """Check if Robinhood API is accessible."""
    token = get_rh_token()
    if not token:
        log.error("Cannot proceed without token")
        return False

    # Try to get account info
    log.info("\n=== Testing Robinhood API Connectivity ===")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        # Get accounts
        r = requests.get("https://api.robinhood.com/accounts/", headers=headers, timeout=10)
        if r.status_code == 200:
            accounts = r.json().get("results", [])
            log.info("✅ API accessible! Found %d accounts", len(accounts))
            for acc in accounts:
                log.info("   - Account: %s (%s)", acc.get("account_number", "?"), acc.get("account_type", "?"))
            return True
        else:
            log.error("❌ API call failed: %s - %s", r.status_code, r.text[:200])
            return False
    except Exception as e:
        log.error("❌ Error: %s", e)
        return False

def try_place_test_order():
    """Try to place a test order via Robinhood API."""
    token = get_rh_token()
    if not token:
        log.error("Cannot proceed without token")
        return False

    log.info("\n=== Attempting Test Order via Robinhood API ===")
    headers = {"Authorization": f"Bearer {token}"}

    # Try to place a small market order
    order_data = {
        "account_number": RH_ACCOUNT,
        "instrument": {
            "symbol": "AAPL"
        },
        "quantity": "0.01",
        "side": "buy",
        "type": "market",
        "time_in_force": "gfd"
    }

    try:
        r = requests.post(
            "https://api.robinhood.com/orders/",
            json=order_data,
            headers=headers,
            timeout=10
        )

        if r.status_code in [200, 201]:
            order_result = r.json()
            log.info("✅ Order placed! Order ID: %s", order_result.get("id", "unknown"))
            log.info("   Status: %s", order_result.get("status", "?"))
            log.info("   Full response: %s", json.dumps(order_result, indent=2)[:500])
            return True
        else:
            log.error("❌ Order failed: %s", r.status_code)
            log.error("   Response: %s", r.text[:300])
            return False
    except Exception as e:
        log.error("❌ Error: %s", e)
        return False

if __name__ == "__main__":
    if check_robinhood_api():
        log.info("\n✅ Robinhood API is working. Token is valid.")
        log.info("\nNow testing if we can actually place orders...")
        try_place_test_order()
    else:
        log.error("\n❌ Robinhood API not accessible. OAuth token may be invalid or expired.")
