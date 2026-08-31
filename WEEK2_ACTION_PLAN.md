# Week 2 Action Plan (Sept 8-14)
## Gymnasium Model Training & Validation

---

## 📅 Schedule

| Day | Task | Duration | Status |
|-----|------|----------|--------|
| **Mon 9/8** | Fix data sources, train PPO | 3-4 hrs | 🔄 IN PROGRESS |
| **Tue 9/9** | Train SAC, run evaluations | 3-4 hrs | ⏳ PENDING |
| **Wed 9/10** | Backtest baseline (HybridStrategy) | 1-2 hrs | ⏳ PENDING |
| **Thu 9/11** | Backtest PPO/SAC models | 2-3 hrs | ⏳ PENDING |
| **Fri 9/12** | Analysis & comparison | 2 hrs | ⏳ PENDING |
| **Sat-Sun 9/13-14** | Decision: Deploy or optimize | N/A | ⏳ PENDING |

---

## 🚀 Step 1: Fix Data Sources

### Problem
- yfinance only returns ~500 days (1 year)
- Trainer requires 730+ days (2 years)

### Solution Options

**Option A: Use cached CSV files (RECOMMENDED)**
```bash
# Save historical data to CSV once
python -c "
import yfinance as yf
import pandas as pd
for symbol in ['AAPL', 'NVDA', 'TSLA', 'MSFT', 'SPY']:
    df = yf.download(symbol, period='5y', progress=False)
    df.to_csv(f'{symbol}_5y.csv')
    print(f'✅ {symbol} saved')
"
```

**Option B: Use Railway's data cache**
```bash
# Access cached historical data from Railway deployment
# Already available in /trading_bot/market_*_cache.json
```

**Option C: Reduce lookback window**
```python
# In gymnasium_trainer.py line 88:
# Change: lookback_years=2 → lookback_years=1
# Accepts ~500 days instead of ~730
trainer = MultiAssetTrainer(lookback_years=1)
```

---

## 🎯 Step 2: Train Models

### Training PPO (Policy Gradient)

```bash
cd /Users/ramayalala/Documents/Documents\ -\ Rama\'s\ MacBook\ Pro/trading_bot

# Train on AAPL, NVDA, TSLA, MSFT (80% data)
# Evaluate on SPY (20% data, held-out)
python3.9 gymnasium_trainer.py \
  --model ppo \
  --timesteps 500000 \
  --symbols AAPL NVDA TSLA MSFT SPY

# Expected output:
# - gymnasium_models/gymnasium_ppo.zip (trained model)
# - TensorBoard logs in gymnasium_models/tb_logs/
# - Evaluation results on SPY
```

**Expected training time: 2-3 hours**

### Training SAC (Soft Actor-Critic)

```bash
# Same as PPO but with different hyperparameters
python3.9 gymnasium_trainer.py \
  --model sac \
  --timesteps 500000 \
  --symbols AAPL NVDA TSLA MSFT SPY
```

**Expected training time: 3-4 hours**

### Monitor Training Progress

```bash
# View TensorBoard logs in real-time
tensorboard --logdir gymnasium_models/tb_logs/

# Then open http://localhost:6006 in browser
```

---

## 📊 Step 3: Backtest Baseline (HybridStrategy)

### Baseline Test: Current Production Strategy

```bash
python3.9 backtest_hybrid_strategy_complete.py AAPL NVDA TSLA MSFT SPY

# Expected metrics:
#   Return:        +20-30% (6 months)
#   Sharpe:        0.4-0.7 (moderate risk)
#   Win Rate:      48-52% (slightly below 50%)
#   Max Drawdown:  -15-25% (normal range)
#   Trades:        40-60 (~10/month)
```

**CSV output:** `backtest_hybrid_results_YYYYMMDD_HHMMSS.csv`

---

## 🧠 Step 4: Backtest RL Models

### Test Trained PPO Model

```bash
python3.9 gymnasium_backtest.py \
  --symbols AAPL NVDA TSLA MSFT SPY \
  --models ppo buy-hold rules-based \
  --output gymnasium_backtest_ppo.csv

# Expected: PPO should beat buy-hold by 50-100%
#   PPO Return:      +45-65%
#   Buy-Hold Return: +25-35%
#   PPO Sharpe:      0.8-1.2 (better than HybridStrategy)
```

### Test Trained SAC Model

```bash
python3.9 gymnasium_backtest.py \
  --symbols AAPL NVDA TSLA MSFT SPY \
  --models sac buy-hold rules-based \
  --output gymnasium_backtest_sac.csv

# Expected: SAC slightly better than PPO
#   SAC Return:  +50-70%
#   SAC Sharpe:  1.0-1.4
```

---

## 📈 Step 5: Analysis & Comparison

### Create Comparison Table

| Model | Return | Sharpe | Max DD | Win Rate | Status |
|-------|--------|--------|--------|----------|--------|
| **HybridStrategy** (baseline) | +20-30% | 0.4-0.7 | -15-25% | 48-52% | ✅ LIVE |
| **PPO** | +45-65% | 0.8-1.2 | -15-20% | 55-65% | 🔄 Training |
| **SAC** | +50-70% | 1.0-1.4 | -12-18% | 58-68% | 🔄 Training |
| **Buy-Hold** | +25-35% | 0.5-0.8 | -20-30% | 52-55% | 📊 Baseline |

### Success Criteria

✅ **DEPLOY PPO/SAC if:**
- Sharpe > 1.0 (vs 0.4-0.7 for HybridStrategy)
- Max Drawdown < -20% (manageable risk)
- Win Rate > 55% (better than 50/50)
- Return > 2x HybridStrategy return

❌ **KEEP HybridStrategy if:**
- Sharpe < 1.0 (RL not beating rules-based)
- Model overfit to training symbols
- Drawdown > -25% (too risky)

---

## 🔧 Step 6: Decision

### If PPO/SAC Wins (Most Likely)

**Week 3 Plan:**
```
1. Hyperparameter tuning
   - Try different learning rates
   - Adjust n_steps, batch_size
   - Compare results

2. Multi-asset testing
   - Train on different symbol sets
   - Validate generalization
   
3. Integration planning
   - How to deploy model to bot
   - Feature extraction pipeline
   - Real-time prediction interface

4. Paper trading
   - Run on Railway for 1 week
   - Compare live vs backtest
   - Monitor for drift

5. Go-live decision
   - Risk assessment
   - Rollback plan
   - Monitoring strategy
```

### If HybridStrategy Wins

**Week 3 Plan:**
```
1. Optimize HybridStrategy
   - Adjust BB periods
   - Fine-tune entry thresholds
   - Better position sizing

2. Analyze why RL didn't work
   - Insufficient data?
   - Wrong reward function?
   - Poor feature engineering?

3. Alternative RL approaches
   - Try different algorithms (DQN, A3C)
   - Longer training period
   - Different feature set (17D → 25D?)
```

---

## 📝 Deliverables

By end of Week 2:

✅ Trained PPO model (`gymnasium_ppo.zip`)
✅ Trained SAC model (`gymnasium_sac.zip`)
✅ HybridStrategy backtest CSV
✅ PPO backtest CSV
✅ SAC backtest CSV
✅ Comparison analysis
✅ Decision memo (deploy or optimize)

---

## 🎮 Commands Quick Reference

```bash
# Data preparation
python3.9 -c "import yfinance as yf; df = yf.download('AAPL', period='5y'); df.to_csv('AAPL_5y.csv')"

# Train PPO
python3.9 gymnasium_trainer.py --model ppo --timesteps 500000 --symbols AAPL NVDA TSLA MSFT SPY

# Train SAC
python3.9 gymnasium_trainer.py --model sac --timesteps 500000 --symbols AAPL NVDA TSLA MSFT SPY

# Backtest HybridStrategy
python3.9 backtest_hybrid_strategy_complete.py AAPL NVDA TSLA MSFT SPY

# Backtest PPO
python3.9 gymnasium_backtest.py --symbols AAPL NVDA TSLA MSFT SPY --models ppo buy-hold

# Monitor training
tensorboard --logdir gymnasium_models/tb_logs/

# View results
cat backtest_hybrid_results_*.csv
cat gymnasium_backtest_*.csv
```

---

## 📞 Success Metrics

- ✅ Both models train successfully
- ✅ PPO Sharpe > 1.0
- ✅ SAC Sharpe > 1.0
- ✅ Both beat HybridStrategy baseline
- ✅ Clear deployment decision by Friday 9/12

---

## ⚠️ Known Issues & Workarounds

### Issue 1: Insufficient Data
**Problem:** yfinance returns <730 days
**Fix:** Use `lookback_years=1` or save CSV files

### Issue 2: NumPy 2.0 Compatibility
**Problem:** Torch/PyTorch compatibility warnings
**Fix:** Harmless warnings, can ignore (or `pip install numpy<2`)

### Issue 3: Memory Usage
**Problem:** 500K timesteps training uses 4-8GB RAM
**Fix:** Reduce `n_steps` or use smaller `batch_size`

---

**Week 2 = Foundation for Week 3 Deployment Decision**

Start Monday morning! 🚀
