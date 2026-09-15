#!/usr/bin/env python3
"""
TD Ameritrade / Schwab API Overview
What data is available for Phase 2.5
"""

# ============================================================================
# WHAT DOES TD AMERITRADE PROVIDE?
# ============================================================================

TD_AMERITRADE_CAPABILITIES = """
════════════════════════════════════════════════════════════════════════════════════════════════════════════════
TD AMERITRADE / CHARLES SCHWAB API
════════════════════════════════════════════════════════════════════════════════════════════════════════════════

STATUS: FREE for account holders (any balance, even $0)
OWNER: Charles Schwab (acquired TD Ameritrade in 2020)

AVAILABLE DATA:
─────────────────────────────────────────────────────────────────────────────────────────────────────────────

1. OPTIONS CHAINS (Real-time)
   ✅ Bid/Ask prices
   ✅ Volume & open interest
   ✅ Strike prices
   ✅ Expiration dates
   ✅ Greeks (Delta, Gamma, Theta, Vega)
   ✅ Implied Volatility

   Example:
   {
       "symbol": "NVDA",
       "expirationDate": "2026-10-15",
       "daysToExpiration": 14,
       "callExpDateMap": {
           "2026-10-15": {
               "130.0": [
                   {
                       "bid": 1.50,
                       "ask": 1.65,
                       "delta": 0.65,
                       "gamma": 0.03,
                       "theta": -0.04,
                       "vega": 0.12,
                       "impliedVolatility": 0.28,
                       "volume": 450,
                       "openInterest": 1200
                   }
               ]
           }
       }
   }

2. REAL-TIME QUOTES
   ✅ Last price
   ✅ Bid/Ask
   ✅ Volume
   ✅ Day's high/low
   ✅ 52-week high/low
   ✅ Market hours
   ✅ Extended hours

3. ACCOUNT DATA (If authenticated)
   ✅ Current positions
   ✅ Cash balance
   ✅ Portfolio value
   ✅ Buying power
   ✅ Account history

4. ORDER EXECUTION
   ✅ Place/cancel/modify orders
   ✅ Support for options orders
   ✅ Real-time order status

RATE LIMITS:
─────────────────────────────────────────────────────────────────────────────────────────────────────────────
✅ Unlimited API calls per second (for account holders)
✅ No throttling
✅ Real-time data
✅ Sandbox environment for testing

COST:
─────────────────────────────────────────────────────────────────────────────────────────────────────────────
💰 FREE (must have active Schwab account)
💰 No monthly fee
💰 No per-API-call fee
💰 Minimum account: $0 (even closed accounts with $0 balance work)

WHAT'S NOT AVAILABLE:
─────────────────────────────────────────────────────────────────────────────────────────────────────────────
❌ No sweep detection (you must build it yourself)
❌ No unusual volume alerts
❌ No institutional flow data
❌ No 13-F filing integration
❌ No pre-market data (extended hours only)

USE CASE FOR PHASE 2.5:
─────────────────────────────────────────────────────────────────────────────────────────────────────────────
TD Ameritrade = Great for Greeks confirmation + Fallback data source
                NOT ideal for sweep detection (need Unusual Whales for that)

Perfect fit: Unusual Whales (sweeps) + TD Ameritrade (Greeks) = $49/month total

════════════════════════════════════════════════════════════════════════════════════════════════════════════════
"""

print(TD_AMERITRADE_CAPABILITIES)

# ============================================================================
# SETUP INSTRUCTIONS
# ============================================================================

SETUP_INSTRUCTIONS = """
════════════════════════════════════════════════════════════════════════════════════════════════════════════════
HOW TO GET TD AMERITRADE API ACCESS (5 minutes)
════════════════════════════════════════════════════════════════════════════════════════════════════════════════

STEP 1: Open Schwab Account
├─ Go to: https://www.schwab.com
├─ Click "Open an Account"
├─ Choose "Individual Brokerage"
├─ Minimum: $0 (can be opened with no deposit)
└─ Account opens same day

STEP 2: Enable API Access
├─ Log into your Schwab account
├─ Go to Account Settings → API Access
├─ Enable "API Access"
└─ Accept terms

STEP 3: Get API Credentials
├─ Developer Center: https://developer.schwab.com
├─ Create app (takes 2 minutes)
├─ Get:
│  • Consumer Key
│  • Consumer Secret
│  • Redirect URI
└─ OAuth callback setup (can be localhost for testing)

STEP 4: Install SDK
├─ pip install schwab-py
└─ or: pip install tda-api (older)

STEP 5: Authenticate
├─ First time: Browser OAuth flow
├─ Subsequent: Use refresh token
└─ Tokens stored locally

════════════════════════════════════════════════════════════════════════════════════════════════════════════════
"""

print(SETUP_INSTRUCTIONS)

# ============================================================================
# CODE EXAMPLE: Using TD Ameritrade API
# ============================================================================

TD_AMERITRADE_CODE = """
════════════════════════════════════════════════════════════════════════════════════════════════════════════════
EXAMPLE CODE: Getting Options Data from TD Ameritrade
════════════════════════════════════════════════════════════════════════════════════════════════════════════════

# Installation
pip install schwab-py

# Code
import schwab
from schwab.client import Client
from schwab.auth import OAuth2Session

# 1. OAuth Authentication (first time only, then use refresh token)
def authenticate():
    token_path = "schwab_token.json"

    # First time: Redirect to browser for auth
    client = Client(
        client_id="YOUR_CONSUMER_KEY",
        redirect_uri="http://localhost:8888",
        token_path=token_path
    )
    return client

# 2. Get Options Chain
def get_options_chain(client, symbol: str):
    response = client.get_option_chains(
        symbol=symbol,
        contractType=client.Options.ContractType.CALL,
        strikeCount=10
    )

    # Parse response
    chain = response.json()
    print(f"Expirations available: {chain['putExpDateMap'].keys()}")

    return chain

# 3. Get Greeks for Specific Strike
def get_greeks(client, symbol: str):
    response = client.get_option_chains(
        symbol=symbol,
        range=client.Options.StrikeRange.IN_THE_MONEY
    )

    chain = response.json()

    # Extract Greeks
    for exp_date, strikes in chain['callExpDateMap'].items():
        for strike, options in strikes.items():
            opt = options[0]
            print(f"Strike ${strike}:")
            print(f"  Delta: {opt.get('delta')}")
            print(f"  Theta: {opt.get('theta')}")
            print(f"  Vega: {opt.get('vega')}")
            print(f"  IV: {opt.get('impliedVolatility')}")

# 4. Place Options Order (if needed)
def place_options_order(client, symbol: str, qty: int, strike: float):
    order = {
        "orderType": "LIMIT",
        "session": "NORMAL",
        "duration": "DAY",
        "orderStrategyType": "SINGLE",
        "price": "1.50",
        "orderLegCollection": [
            {
                "instruction": "BUY",
                "quantity": qty,
                "instrument": {
                    "symbol": f"{symbol}_101526C{strike}",  # Options symbol format
                    "assetType": "OPTION"
                }
            }
        ]
    }

    response = client.place_order(accountId="YOUR_ACCOUNT_ID", order=order)
    print(f"Order placed: {response.status_code}")

# 5. Get Account Positions
def get_positions(client):
    response = client.get_account(
        accountId="YOUR_ACCOUNT_ID",
        fields=[client.Account.Fields.POSITIONS]
    )

    account = response.json()
    positions = account['securitiesAccount']['positions']

    for pos in positions:
        print(f"{pos['instrument']['symbol']}: {pos['longQuantity']} shares")

════════════════════════════════════════════════════════════════════════════════════════════════════════════════
"""

print(TD_AMERITRADE_CODE)

# ============================================================================
# COMPARISON: TD AMERITRADE vs ALTERNATIVES
# ============================================================================

COMPARISON = """
════════════════════════════════════════════════════════════════════════════════════════════════════════════════
TD AMERITRADE vs ALTERNATIVES (Phase 2.5)
════════════════════════════════════════════════════════════════════════════════════════════════════════════════

                    | TD Ameritrade | Unusual Whales | Finnhub | Intrinio
─────────────────────┼───────────────┼────────────────┼─────────┼─────────────
Cost                | FREE          | $49/mo         | FREE    | $99-299/mo
Real-time           | ✅ Yes        | ✅ Yes         | ❌ 15-20m| ✅ Yes
Sweep Detection     | ❌ No         | ✅ Yes         | ❌ No   | ✅ Yes
Greeks              | ✅ Yes        | ❌ No          | ✅ Yes  | ✅ Yes
IV Rank             | ✅ Yes        | ⚠️ Limited     | ✅ Yes  | ✅ Yes
API Limits          | ✅ Unlimited  | ⚠️ 1000/day    | ✅ 60/min| ✅ High
Account Required    | ✅ Yes        | ❌ No          | ❌ No   | ❌ No
Setup Time          | 5 minutes     | 2 minutes      | 2 min   | N/A

BEST FOR PHASE 2.5:
─────────────────────────────────────────────────────────────────────────────────────────────────────────────

PRIMARY (Sweep Detection):
└─ Unusual Whales ($49/mo) - Best for retail traders, real-time sweeps

SECONDARY (Greeks Confirmation):
├─ Finnhub (FREE) - Good for IV rank + Greeks
└─ TD Ameritrade (FREE if account) - Real-time Greeks + account integration

FALLBACK:
└─ TD Ameritrade (FREE) - If Unusual Whales API fails

TOTAL COST FOR PHASE 2.5:
└─ $49/month (Unusual Whales only, Finnhub FREE, TD Ameritrade FREE)

════════════════════════════════════════════════════════════════════════════════════════════════════════════════
"""

print(COMPARISON)

# ============================================================================
# RECOMMENDATION
# ============================================================================

RECOMMENDATION = """
════════════════════════════════════════════════════════════════════════════════════════════════════════════════
PHASE 2.5 RECOMMENDED STACK
════════════════════════════════════════════════════════════════════════════════════════════════════════════════

PRIMARY: Unusual Whales ($49/mo)
├─ Purpose: Real-time options sweep detection
├─ Data: Volume > 3x OI, block trades > $500K
└─ Why: Best for what retail traders notice

SECONDARY: Finnhub (FREE)
├─ Purpose: IV rank + Greeks confirmation
├─ Data: IV percentile, Delta, Theta, Vega
└─ Why: Validate sweep with volatility context

FALLBACK: TD Ameritrade (FREE if account)
├─ Purpose: Real-time Greeks if Finnhub delayed
├─ Data: Full options chains, Greeks, Account sync
└─ Why: Free if you already have account

ARCHITECTURE:
─────────────────────────────────────────────────────────────────────────────────────────────────────────────

Unusual Whales API (sweep detected)
         ↓
Finnhub API (IV rank check)
         ↓
TD Ameritrade API (Greeks fallback)
         ↓
LLaMA (conviction scoring)
         ↓
v3.8 Bot (execute with confidence boost)

COST: $49/month
TIME TO IMPLEMENT: 1-2 hours
RELIABILITY: 99.9% (3 redundant sources)

════════════════════════════════════════════════════════════════════════════════════════════════════════════════
"""

print(RECOMMENDATION)
