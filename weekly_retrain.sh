#!/bin/bash
# Sunday 20:00 UTC: Retrain FinRL and auto-deploy if Sharpe >= 1.8

LOG_FILE="logs/finrl_weekly_$(date +%Y%m%d_%H%M%S).log"
mkdir -p logs

echo "=== FinRL Weekly Retraining ===" | tee -a "$LOG_FILE"
echo "Start: $(date)" | tee -a "$LOG_FILE"

# Train new model
python3 finrl_working_trainer.py 2>&1 | tee -a "$LOG_FILE"

# Check Sharpe ratio from metrics
SHARPE=$(python3 -c "import json; m=json.load(open('finrl_metrics.json')); print(m.get('sharpe', 0))" 2>/dev/null)

echo "Sharpe Ratio: $SHARPE" | tee -a "$LOG_FILE"

if (( $(echo "$SHARPE >= 1.8" | bc -l) )); then
    echo "✅ Sharpe $SHARPE >= 1.8 → Deploying new model" | tee -a "$LOG_FILE"
    
    # Deploy: commit and push
    git add finrl_agent* finrl_metrics.json
    git commit -m "Auto: FinRL weekly retrain (Sharpe=$SHARPE)" 2>&1 | tee -a "$LOG_FILE"
    git push origin main 2>&1 | tee -a "$LOG_FILE"
    
    echo "✅ Deployed. Bot will restart to load new model." | tee -a "$LOG_FILE"
else
    echo "⚠️  Sharpe $SHARPE < 1.8 → Keeping previous model" | tee -a "$LOG_FILE"
    echo "   (New model underperforming, skipping deployment)" | tee -a "$LOG_FILE"
fi

echo "End: $(date)" | tee -a "$LOG_FILE"
