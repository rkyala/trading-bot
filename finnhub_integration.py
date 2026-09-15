#!/usr/bin/env python3
"""
Finnhub Integration Guide
Free options data + Greeks for Phase 2.5

Sign up: https://finnhub.io (FREE)
Get API key: https://finnhub.io/dashboard
"""

import requests
import json
from typing import Dict, List, Optional

# ============================================================================
# WHAT IS FINNHUB?
# ============================================================================
"""
Finnhub = Free financial data API

FREE TIER:
✅ 60 API calls per minute
✅ Real-time options chains
✅ Greeks (Delta, Gamma, Vega, Theta)
✅ IV (Implied Volatility) Rank/Percentile
✅ No credit card required (truly free)

PAID TIERS:
• $9/month: 500 calls/min
• $99/month: 5000 calls/min
• $399/month: Unlimited

DATA QUALITY:
⚠️ Delayed 15-20 minutes (not real-time)
⚠️ Not ideal for sweep detection (need Unusual Whales for that)
✅ PERFECT for confirming IV/Greeks
"""

# ============================================================================
# SETUP
# ============================================================================

FINNHUB_API_KEY = "YOUR_FINNHUB_API_KEY"  # Get from https://finnhub.io/dashboard
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"

# ============================================================================
# EXAMPLE 1: Get Options Chain (Free)
# ============================================================================

def get_finnhub_options_chain(symbol: str, api_key: str) -> Dict:
    """
    Fetch complete options chain for a symbol

    Returns:
    {
        "call": [
            {
                "bid": 1.50,
                "ask": 1.65,
                "lastPrice": 1.58,
                "volume": 450,
                "openInterest": 1200,
                "strike": 130.0,
                "expiration": 1728345600,
                "impliedVolatility": 0.28
            },
            ...
        ],
        "put": [...]
    }
    """
    try:
        url = f"{FINNHUB_BASE_URL}/stock/option-chain"
        params = {
            "symbol": symbol,
            "token": api_key
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        print(f"\n✅ Finnhub Options Chain for {symbol}")
        print(f"   CALL options: {len(data.get('call', []))}")
        print(f"   PUT options: {len(data.get('put', []))}")

        return data

    except Exception as e:
        print(f"❌ Finnhub error: {e}")
        return {}


# ============================================================================
# EXAMPLE 2: Get Options Greeks (Premium)
# ============================================================================

def get_finnhub_options_greeks(symbol: str, expiration: int, api_key: str) -> List[Dict]:
    """
    Fetch Greeks (Delta, Gamma, Vega, Theta) for all strikes

    Returns:
    [
        {
            "bid": 1.50,
            "ask": 1.65,
            "strike": 130.0,
            "delta": 0.65,
            "gamma": 0.03,
            "theta": -0.04,
            "vega": 0.12,
            "impliedVolatility": 0.28
        },
        ...
    ]
    """
    try:
        url = f"{FINNHUB_BASE_URL}/stock/option-greeks"
        params = {
            "symbol": symbol,
            "exp": expiration,  # Unix timestamp
            "token": api_key
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        greeks = response.json()

        print(f"\n✅ Finnhub Greeks for {symbol}")
        if greeks:
            print(f"   First strike: ${greeks[0].get('strike')}")
            print(f"   Delta: {greeks[0].get('delta'):.2f}")
            print(f"   Theta: {greeks[0].get('theta'):.2f}")
            print(f"   IV: {greeks[0].get('impliedVolatility'):.2f}")

        return greeks

    except Exception as e:
        print(f"❌ Finnhub Greeks error: {e}")
        return []


# ============================================================================
# EXAMPLE 3: Get IV Rank (Most Useful for Phase 2.5)
# ============================================================================

def get_finnhub_iv_rank(symbol: str, api_key: str) -> Dict:
    """
    Fetch IV Rank and IV Percentile

    IV Rank: Where current IV sits in 52-week range (0-100)
    - 0 = lowest IV in past year
    - 100 = highest IV in past year
    - 75+ = High volatility environment

    Returns:
    {
        "ivRank": 65,          # Current IV rank (0-100)
        "ivPercentile": 62     # IV percentile
    }
    """
    try:
        url = f"{FINNHUB_BASE_URL}/stock/option-iv"
        params = {
            "symbol": symbol,
            "token": api_key
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        iv_rank = data.get("ivRank", 0)
        iv_percentile = data.get("ivPercentile", 0)

        print(f"\n✅ Finnhub IV Rank for {symbol}")
        print(f"   IV Rank: {iv_rank}/100")
        print(f"   IV Percentile: {iv_percentile}%")

        # Interpretation
        if iv_rank > 75:
            print(f"   Status: 🔴 HIGH volatility (good for premium selling)")
        elif iv_rank > 50:
            print(f"   Status: 🟡 MEDIUM volatility")
        else:
            print(f"   Status: 🟢 LOW volatility (good for spread buying)")

        return data

    except Exception as e:
        print(f"❌ Finnhub IV error: {e}")
        return {}


# ============================================================================
# HOW TO USE IN PHASE 2.5
# ============================================================================

def phase2_5_finnhub_integration(symbol: str, api_key: str):
    """
    Example: Use Finnhub as a CONFIRMATION layer

    Unusual Whales → Detects sweep
    ↓
    Finnhub → Confirms with IV rank & Greeks
    ↓
    LLaMA → Scores conviction
    ↓
    v3.8 Bot → Executes with confidence boost
    """

    print("\n" + "="*100)
    print(f"PHASE 2.5: Finnhub Confirmation Layer for {symbol}")
    print("="*100)

    # Step 1: Get IV Rank (quick check)
    print("\n[STEP 1] Check IV Environment")
    iv_data = get_finnhub_iv_rank(symbol, api_key)

    if iv_data.get("ivRank", 0) > 75:
        print("✅ High volatility environment → Good for breakouts")
        iv_boost = 1.10
    else:
        print("⚠️  Normal/Low volatility → Be cautious")
        iv_boost = 0.95

    # Step 2: Get options chain
    print("\n[STEP 2] Analyze Options Chain")
    chain = get_finnhub_options_chain(symbol, api_key)

    if chain.get("call"):
        # Find implied volatility levels
        call_ivs = [c.get("impliedVolatility", 0) for c in chain.get("call", [])]
        avg_iv = sum(call_ivs) / len(call_ivs) if call_ivs else 0
        print(f"   Average Call IV: {avg_iv:.2f}")

    # Step 3: Get Greeks for confirmation
    print("\n[STEP 3] Check Greeks (if available)")
    if chain.get("call"):
        first_call = chain["call"][0]
        print(f"   Strike: ${first_call.get('strike')}")
        print(f"   Implied Vol: {first_call.get('impliedVolatility', 0):.2f}")

    # Step 4: Generate confidence adjustment
    print("\n[STEP 4] Confidence Adjustment")
    base_confidence = 85  # From Unusual Whales sweep

    # Adjust based on IV environment
    adjusted_confidence = base_confidence * iv_boost

    print(f"   Unusual Whales confidence: {base_confidence}")
    print(f"   IV environment multiplier: {iv_boost}x")
    print(f"   Final confidence: {adjusted_confidence:.0f}/100")

    return {
        "symbol": symbol,
        "base_confidence": base_confidence,
        "iv_rank": iv_data.get("ivRank", 0),
        "adjusted_confidence": adjusted_confidence,
        "recommendation": "BOOST" if adjusted_confidence > 85 else "HOLD" if adjusted_confidence > 75 else "REDUCE"
    }


# ============================================================================
# SETUP INSTRUCTIONS
# ============================================================================

SETUP = """
════════════════════════════════════════════════════════════════════════════════════════════════════════════════
FINNHUB SETUP (2 minutes)
════════════════════════════════════════════════════════════════════════════════════════════════════════════════

1. Go to: https://finnhub.io
2. Click "Free Plan" → Sign up with email
3. Confirm email
4. Dashboard → Copy API Key
5. Set environment: export FINNHUB_API_KEY=<your-key>

TEST:
python3 -c "
import requests
api_key = 'your-key'
r = requests.get('https://finnhub.io/api/v1/stock/option-chain',
    params={'symbol': 'NVDA', 'token': api_key})
print(r.json())
"

FINNHUB LIMITS (Free Tier):
✅ 60 calls/minute
✅ Options chains
✅ Greeks calculation
✅ IV Rank
❌ No real-time (15-20 min delay)
❌ No sweep detection

BEST USE IN PHASE 2.5:
• Use Unusual Whales ($49/mo) for sweep detection
• Use Finnhub (FREE) for IV confirmation
• Combined = Complete picture for $49/month
════════════════════════════════════════════════════════════════════════════════════════════════════════════════
"""

if __name__ == "__main__":
    print(SETUP)

    # Test with demo key (won't work, but shows structure)
    print("\n\nDemo (would work with real API key):")
    result = phase2_5_finnhub_integration("NVDA", FINNHUB_API_KEY)
    print(f"\nFinal Result: {json.dumps(result, indent=2)}")
