# Options Data Alternatives to Intrinio

## Free/Cheap Options for Unusual Activity

### 1. **Unusual Whales** ⭐ BEST FREE ALTERNATIVE
**Cost**: $49/month (or free tier with limited data)  
**Data**: Real-time options sweeps, unusual volume, flow  
**Setup**: API key at unusualwhales.com  

```python
import requests

def get_unusual_whales_sweeps(api_key: str):
    """Fetch real options sweeps from Unusual Whales API"""
    url = "https://api.unusualwhales.com/v1/options/sweeps"
    headers = {"Authorization": f"Bearer {api_key}"}
    
    response = requests.get(url, headers=headers)
    return response.json()  # Real sweep data
```

**Pros**:
- ✅ Cheaper than Intrinio ($49 vs $299/mo)
- ✅ Better for retail traders (sweeps = what retail notices)
- ✅ Web scraping fallback if API slow
- ✅ Reddit/Twitter integration for sentiment

**Cons**:
- ⚠️ API limits (1000 calls/day on free tier)
- ⚠️ Slightly delayed (1-2 min behind market)

**Free Tier**: Yes, limited data (~50 sweeps/day)

---

### 2. **Finnhub** 💰 FREE TIER AVAILABLE
**Cost**: FREE (with limits) or $9-399/month  
**Data**: Options Greeks, chains, IV rank/percentile  
**Setup**: Sign up at finnhub.io  

```python
import requests

def get_finnhub_options(symbol: str, api_key: str):
    """Fetch options data from Finnhub"""
    url = f"https://finnhub.io/api/v1/stock/option-chain"
    params = {"symbol": symbol, "token": api_key}
    
    response = requests.get(url, params=params)
    return response.json()  # Options chain data
```

**Pros**:
- ✅ FREE tier (60 calls/min)
- ✅ Good for options Greeks/IV analysis
- ✅ No sweep data, but useful for confirmation

**Cons**:
- ❌ No unusual volume/sweep detection
- ❌ Delayed data (15-20 min)
- ⚠️ Not ideal for real-time trading

**Free Tier**: Yes, 60 API calls/minute

---

### 3. **TD Ameritrade / Schwab API** 💰 FREE IF YOU HAVE ACCOUNT
**Cost**: FREE with active brokerage account  
**Data**: Real-time options chains, greeks, account access  
**Setup**: Get API key from your Schwab account  

```python
import requests

def get_td_options_data(symbol: str, access_token: str):
    """Fetch real-time options from TD Ameritrade API"""
    url = f"https://api.schwabapi.com/marketdata/v1/chains"
    params = {"symbol": symbol, "strikeCount": 10}
    headers = {"Authorization": f"Bearer {access_token}"}
    
    response = requests.get(url, params=params, headers=headers)
    return response.json()
```

**Pros**:
- ✅ Completely FREE if you have Schwab account
- ✅ Real-time options chains
- ✅ Can integrate with your trading account

**Cons**:
- ❌ No sweep detection (need to build it)
- ❌ Slightly delayed
- ⚠️ Requires active Schwab account ($0 minimum)

**Free Tier**: Yes, free if you have $0 account

---

### 4. **OpenBB Terminal** 🎉 OPEN SOURCE & FREE
**Cost**: FREE (open source)  
**Data**: Options chains, Greeks, unusual volume  
**Setup**: `pip install openbb`  

```python
from openbb_terminal.sdk import openbb

# Get options data
options = openbb.stocks.options.chains("NVDA")
print(options)

# Get unusual volume
unusual = openbb.stocks.options.unusual("NVDA")
print(unusual)
```

**Pros**:
- ✅ 100% FREE
- ✅ Open source (modify as needed)
- ✅ Multiple data sources (Yahoo, IG, CMC)
- ✅ Built-in unusual volume detection

**Cons**:
- ⚠️ Delayed data (15-20 min)
- ⚠️ Limited real-time capabilities
- ⚠️ Requires local installation

**Free Tier**: Yes, unlimited

---

### 5. **Web Scraping Yahoo Finance** ⚠️ HACKY BUT FREE
**Cost**: FREE  
**Data**: Options chains, volume, IV  
**Setup**: `pip install yfinance`  

```python
import yfinance as yf

def get_options_volume(symbol: str):
    """Scrape options data from Yahoo Finance"""
    stock = yf.Ticker(symbol)
    
    # Get options chains
    expirations = stock.options
    
    for exp in expirations:
        chain = stock.option_chain(exp)
        calls = chain.calls
        puts = chain.puts
        
        # Manual sweep detection
        unusual_calls = calls[calls['volume'] > calls['openInterest'] * 3]
        return unusual_calls
```

**Pros**:
- ✅ 100% FREE
- ✅ No API key needed
- ✅ Easy to implement

**Cons**:
- ❌ Data is 15-20 min delayed
- ❌ No real sweep detection (manual calc)
- ⚠️ Yahoo can block scraping
- ❌ Not reliable for production

**Free Tier**: Yes, but rate-limited

---

### 6. **OptionChain.net** 💰 PAID BUT ALTERNATIVE
**Cost**: $29-99/month  
**Data**: Options chains, unusual volume, IV  
**Setup**: API integration  

```python
# Similar to Intrinio but cheaper
# $29/month for basic plan
```

**Pros**:
- ✅ Cheaper than Intrinio ($29 vs $99+)
- ✅ Good UI if you want manual analysis
- ✅ Options flow data

**Cons**:
- ⚠️ Still paid ($29/mo)
- ⚠️ Smaller API community

**Free Tier**: No

---

## **Comparison Table**

| Service | Cost | Real-Time Sweeps | Free Tier | Best For |
|---------|------|------------------|-----------|----------|
| **Unusual Whales** | $49/mo | ✅ Yes | Limited | Retail sweep detection |
| **Intrinio** | $99-299/mo | ✅ Yes | No | Professional data |
| **Finnhub** | FREE-$399/mo | ❌ No | ✅ Yes | Options Greeks/IV |
| **TD Ameritrade** | FREE | ⚠️ Limited | ✅ Yes (if account) | Integrated trading |
| **OpenBB** | FREE | ⚠️ Delayed | ✅ Yes | Open-source analysis |
| **Yahoo Finance** | FREE | ❌ No | ✅ Yes | Quick testing |
| **OptionChain** | $29/mo | ✅ Yes | No | Cheap alternative |

---

## **My Recommendation for Phase 2.5**

### **Option A: Hybrid Approach (BEST)**
```python
# Use Unusual Whales for sweep detection ($49/mo)
# + Finnhub for Greeks confirmation (FREE)
# + TD Ameritrade for fallback (FREE if you have account)
# = Complete picture, ~$50/month total
```

### **Option B: Free Only**
```python
# Use OpenBB Terminal (FREE)
# + Yahoo Finance scraping (FREE)
# + Manual sweep detection logic
# = Works, but 15-20 min delayed
```

### **Option C: Professional**
```python
# Intrinio ($99/mo) for production
# Best real-time data quality
```

---

## **Implementation Priority**

**For Oct 15 Phase 2.5 launch, I recommend:**

1. **Start with Unusual Whales** ($49/mo)
   - Real-time sweeps (what you actually need)
   - Better pricing than Intrinio
   - Easier API

2. **Add Finnhub** (FREE tier)
   - Greeks confirmation
   - IV rank for volatility context
   - Zero cost

3. **Keep TD Ameritrade** (FREE if account exists)
   - Fallback data source
   - Already integrated with Robinhood

**Total monthly cost: $49** (vs $99-300 for Intrinio)

---

## **Quick Start: Unusual Whales**

```bash
# 1. Sign up: https://unusualwhales.com/api
# 2. Get free tier access (limited data)
# 3. Install:
pip install requests

# 4. Run:
python3 -c "
import requests
api_key = 'your-key-here'
r = requests.get('https://api.unusualwhales.com/v1/options/sweeps',
                 headers={'Authorization': f'Bearer {api_key}'})
print(r.json())
"
```

**Want me to integrate Unusual Whales into Phase 2.5?**
