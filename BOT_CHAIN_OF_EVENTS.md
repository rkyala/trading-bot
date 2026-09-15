# 🤖 Complete Bot Chain of Events

## Data Flow: Input → Analysis → Decision → Action

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        BOT CYCLE STARTS (Every 30 min)                      │
└─────────────────────────────────────────────────────────────────────────────┘

                              ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 0: FETCH MARKET DATA                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Input: Symbol (e.g., "INTC")                                               │
│                                                                              │
│  Data Fetched (via yfinance):                                               │
│    • Current price: $92.80                                                  │
│    • Price change today: +2.3%                                              │
│    • Volume: 45.2M shares                                                   │
│    • High/Low: $93.50 / $90.20                                              │
│                                                                              │
│  Calculate Anomaly:                                                         │
│    Anomaly Score = |Price Change %| × 15 = |2.3| × 15 = 34.5 / 100         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

                              ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 1: TECHNICAL ANALYSIS                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Calculate 14-period RSI:                                                   │
│    RSI = 65  →  Signal: OVERBOUGHT                                          │
│                                                                              │
│  Calculate VWAP (Volume-Weighted Avg Price):                                │
│    VWAP = $90.50  →  Price $92.80 > VWAP  →  Signal: BULLISH              │
│                                                                              │
│  Calculate Bollinger Bands (20-period):                                     │
│    Upper Band: $93.20                                                       │
│    Middle (SMA20): $91.00                                                   │
│    Lower Band: $88.80                                                       │
│    Price at Upper Band  →  Signal: OVERBOUGHT BUT in uptrend               │
│                                                                              │
│  Calculate MACD:                                                            │
│    MACD Line: 0.45                                                          │
│    Signal Line: 0.35                                                        │
│    Histogram: +0.10  →  Signal: BULLISH MOMENTUM                           │
│                                                                              │
│  Determine Trend:                                                           │
│    SMA20 ($91.00) > SMA50 ($89.50) > SMA200 ($87.80)                       │
│    →  Signal: UPTREND                                                       │
│                                                                              │
│  Technical Context Output:                                                  │
│    {                                                                        │
│      "rsi": 65, "rsi_signal": "OVERBOUGHT",                                │
│      "vwap": 90.50, "vwap_signal": "BULLISH",                              │
│      "trend": "UPTREND",                                                   │
│      "macd": 0.45, "macd_signal": "BULLISH"                                │
│    }                                                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

                              ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 2: FIBONACCI RETRACEMENT LEVELS (v3 Enhancement)                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Look back 52 weeks of data:                                                │
│    Recent High: $96.00                                                      │
│    Recent Low: $78.00                                                       │
│    Range: $18.00                                                            │
│                                                                              │
│  Calculate Fibonacci Levels:                                                │
│    23.6% Level:  $78.00 + ($18.00 × 0.236) = $82.25                       │
│    38.2% Level:  $78.00 + ($18.00 × 0.382) = $84.87                       │
│    50.0% Level:  $78.00 + ($18.00 × 0.500) = $87.00                       │
│    61.8% Level:  $78.00 + ($18.00 × 0.618) = $89.11  ← KEY LEVEL          │
│    78.6% Level:  $78.00 + ($18.00 × 0.786) = $92.14                       │
│    100% Level:   $96.00                                                     │
│                                                                              │
│  Current Price: $92.80                                                      │
│  Nearest Fib Level: 78.6% at $92.14  (distance: $0.66)                     │
│                                                                              │
│  Fibonacci Boost Score:                                                     │
│    618% level (most significant): +10 boost points                         │
│    Current nearest is 786%: +8 boost points                                │
│    → Use +8 boost                                                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

                              ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 3: RAG MEMORY RETRIEVAL                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Query: "Find similar past winning trades"                                  │
│  Criteria: RSI ~65, Uptrend, Price at resistance                           │
│                                                                              │
│  Search Trade Memory:                                                       │
│    Past Trade 1 (Jun 15): INTC RSI 62, Uptrend, +$5.50 WIN ✅             │
│    Past Trade 2 (Jul 02): AMD RSI 68, Uptrend, +$4.25 WIN ✅              │
│    Past Trade 3 (Jul 18): NVDA RSI 71, Uptrend, +$6.00 WIN ✅             │
│                                                                              │
│  RAG Context Output:                                                        │
│    "Similar patterns: 3 wins in uptrend with high RSI.                     │
│     Avg profit: +$5.25. Confidence boost: +10%"                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

                              ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 4: LLAMA LLM ANALYSIS                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Build Prompt with ALL Context:                                            │
│    "You are a professional trader analyzing INTC.                          │
│     Price: $92.80 (+2.3%)                                                  │
│     Anomaly: 34.5/100                                                       │
│                                                                              │
│     TECHNICAL: RSI 65 (OVERBOUGHT)                                          │
│     Price above VWAP (BULLISH)                                              │
│     Uptrend (SMA20 > SMA50 > SMA200)                                       │
│     MACD bullish                                                            │
│                                                                              │
│     FIBONACCI: Price near 78.6% retracement ($92.14)                       │
│     Key support at 61.8% ($89.11)                                          │
│                                                                              │
│     HISTORY: Similar past trades had 100% win rate with +$5.25 avg        │
│                                                                              │
│     Give confidence 0-100 for BUY RIGHT NOW."                              │
│                                                                              │
│  Llama Reasoning (Local 3.2B Model):                                        │
│    ✓ RSI 65 is overbought BUT in uptrend = mean-reversion setup           │
│    ✓ Price above VWAP = strong trend                                       │
│    ✓ Fibonacci 78.6% level provides support floor                          │
│    ✓ Historical similar trades all won                                     │
│    ✓ Risk/reward favorable                                                 │
│                                                                              │
│  Llama Output:                                                              │
│    "56                                                                      │
│     Overbought in uptrend near Fib support. Similar past trades successful.│
│     Mean-reversion pullback likely with floor at $89.11. Buy signal."      │
│                                                                              │
│  Parsed Llama Confidence: 56%                                              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

                              ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 5: FIBONACCI BOOST APPLICATION                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Base Llama Confidence: 56%                                                │
│  Fibonacci Boost Amount: +8%  (price near 78.6% level)                     │
│                                                                              │
│  Boosted Confidence: 56% + 8% = 64%                                        │
│                                                                              │
│  Why Boost Works:                                                           │
│    Fibonacci identifies support/resistance                                  │
│    When Llama + Fibonacci align = higher probability trade                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

                              ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 6: FINRL RISK METRICS                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  FinRL Model Output:                                                        │
│    Sharpe Ratio: 2.94  (excellent risk-adjusted returns)                   │
│    Market Regime: BULLISH                                                  │
│    Volatility: MODERATE                                                    │
│    Risk Score: LOW                                                         │
│                                                                              │
│  Signal: Model thinks market is favorable for trading                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

                              ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 7: ENSEMBLE VOTING (Llama + FinRL)                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Llama Vote: 64% confidence (with Fibonacci boost)                         │
│  FinRL Vote: BUY signal, Sharpe 2.94                                       │
│                                                                              │
│  Ensemble Combination:                                                      │
│    Final Confidence = (Llama 64% × 0.60) + (FinRL signal × 0.40)          │
│    = (64 × 0.60) + (75 × 0.40)  [FinRL signal normalized to 75]           │
│    = 38.4 + 30 = 68.4%                                                     │
│                                                                              │
│  Ensemble Decision: BUY at 68% confidence                                  │
│  Reasoning: "Llama confident + FinRL favorable = strong signal"            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

                              ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 8: ADAPTIVE THRESHOLD CHECK                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Base Threshold: 52%                                                       │
│                                                                              │
│  Online Learning Adjustment for INTC:                                      │
│    Past 10 INTC trades: 8 wins, 2 losses = 80% win rate                   │
│    High win rate → Lower threshold to capture more                         │
│    Adjusted Threshold: 52% - 5% = 47%                                      │
│                                                                              │
│  Trade Decision:                                                            │
│    Confidence (68%) ≥ Threshold (47%)  ✅ PASS                             │
│    AND Sharpe (2.94) > 0.8  ✅ PASS                                        │
│                                                                              │
│  → TRADE APPROVED                                                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

                              ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 9: TRADE EXECUTION (DRY-RUN - NO REAL ORDERS)                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Log Entry:                                                                 │
│    BUY | INTC @ $92.80 | Llama 64% | Fib Boost +8% | FinRL Sharpe 2.94   │
│                                                                              │
│  Hypothetical Trade Setup:                                                  │
│    Entry Price: $92.80                                                     │
│    Position Size: $600 (fixed allocation)                                  │
│    Shares: 600 / 92.80 = 6.47 shares                                       │
│                                                                              │
│  Calculate 3 Exit Scenarios:                                                │
│                                                                              │
│    BEST CASE (+3% target):                                                 │
│      Exit Price: $92.80 × 1.03 = $95.58                                   │
│      Profit: (95.58 - 92.80) × 6.47 = $18.03                              │
│      ROI: 3.01%                                                            │
│                                                                              │
│    REALISTIC (+1.5% target):                                               │
│      Exit Price: $92.80 × 1.015 = $94.19                                  │
│      Profit: (94.19 - 92.80) × 6.47 = $9.01                               │
│      ROI: 1.50%  ← Most likely outcome                                    │
│                                                                              │
│    CONSERVATIVE (stop loss -1.5%):                                         │
│      Exit Price: $92.80 × 0.985 = $91.42                                  │
│      Loss: (91.42 - 92.80) × 6.47 = -$8.94                                │
│      ROI: -1.49%                                                           │
│                                                                              │
│  Log Hypothetical Outcome (Realistic): +$9.01                              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

                              ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 10: LEARNING & MEMORY                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. RECORD IN RAG MEMORY:                                                   │
│     Store: {                                                               │
│       symbol: "INTC",                                                      │
│       entry_price: 92.80,                                                  │
│       exit_price: 94.19 (realistic +1.5%),                                │
│       confidence: 68,                                                      │
│       fib_level: "78.6%",                                                  │
│       technical: {rsi: 65, trend: "uptrend", ...},                        │
│       outcome_pnl: +9.01,                                                  │
│       timestamp: "2026-08-19 15:37:20"                                     │
│     }                                                                       │
│                                                                              │
│  2. UPDATE ONLINE LEARNING:                                                │
│     INTC Trade History:                                                    │
│       Win #9: +$9.01 at 68% confidence                                    │
│       Updated Win Rate: 9/10 = 90%                                        │
│       New Threshold: 52% - 5% = 47% (encourage more trades)               │
│                                                                              │
│  3. UPDATE SYMBOL STATISTICS:                                               │
│     INTC Stats:                                                            │
│       Total Trades: 10                                                     │
│       Total Profit: +$85.20                                                │
│       Win Rate: 90%                                                        │
│       Avg Profit/Trade: +$8.52                                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

                              ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 11: CYCLE SUMMARY                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Cycle #47 (2026-08-19 15:37:20) Summary:                                  │
│                                                                              │
│    Symbols Analyzed: 8 (INTC, AMD, NVDA, MU, AAPL, META, QCOM, TSLA)      │
│    Signals Generated: 1 BUY                                                │
│    Hypothetical Profit: +$9.01                                             │
│                                                                              │
│    Performance:                                                             │
│    • Best Case (+3%): +$27.03                                              │
│    • Realistic (+1.5%): +$9.01 ✅                                          │
│    • Worst Case (-1.5%): -$8.94                                            │
│                                                                              │
│    Daily Running Total: +$45.20 (5 cycles so far)                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

                              ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│                        CYCLE COMPLETE - Wait 30 min                         │
│                        Next cycle at 16:00 UTC                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Decision Points in Chain

| Stage | Input | Processing | Output | Impact |
|-------|-------|-----------|--------|--------|
| 0 | Price | YFinance | $92.80, +2.3% | Baseline |
| 1 | OHLCV | Technical | RSI 65, Trend UP | Context |
| 2 | 52-week range | Fibonacci | 78.6% level $92.14 | Validation |
| 3 | Technical + Fib | RAG search | Similar wins: 100% | Confidence |
| 4 | All context | Llama LLM | 56% base | Reasoning |
| 5 | Llama + Fib | Boost | 56% + 8% = 64% | Enhancement |
| 6 | Market data | FinRL | Sharpe 2.94 | Risk check |
| 7 | Llama + FinRL | Ensemble | 68% final | Combined vote |
| 8 | Confidence | Threshold | 68% > 47% | GO/NO-GO |
| 9 | Approved | Execution | BUY order | Action |
| 10 | Trade result | Learning | Update memory | Adapt |
| 11 | Summary | Logging | Record cycle | Track |

---

## Data Transformation Example

```
INTC Data Pipeline:
  
  Step 0:  $92.80 price
  Step 1:  RSI 65, Uptrend
  Step 2:  Near Fib 78.6%
  Step 3:  Similar past wins
  Step 4:  Llama: 56%
  Step 5:  + Fib boost: 64%
  Step 6:  FinRL: Bullish
  Step 7:  Ensemble: 68%
  Step 8:  Threshold: 47% ✅
  Step 9:  BUY decision
  Step 10: Trade logged, +$9.01
  Step 11: Updated stats
```

---

## Why This Chain Works

1. **Redundancy**: Multiple stages validate the same trade
2. **Gradual Confidence**: Each stage adds conviction
3. **Adaptability**: Learning adjusts future thresholds
4. **Explainability**: Each step shows WHY we trade
5. **Risk Management**: FinRL + Threshold prevent bad trades

---

**This is the complete bot pipeline!** Every trade goes through all 11 stages. 🤖
