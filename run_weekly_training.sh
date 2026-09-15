#!/bin/bash
# Weekly FinRL Retraining Script (Scheduled Sunday 20:00 UTC)
# Runs on Mac, uses local GPU, takes ~4-6 hours

LOG_FILE="/Users/ramayalala/trading_bot_uw/logs/finrl_training_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$(dirname "$LOG_FILE")"

echo "========================================" >> "$LOG_FILE"
echo "FinRL Weekly Retraining Started" >> "$LOG_FILE"
echo "Time: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

cd "/Users/ramayalala/trading_bot_uw"

# Activate venv and run trainer
source venv_paper/bin/activate >> "$LOG_FILE" 2>&1

echo "Running trainer..." >> "$LOG_FILE"
python3 finrl_working_trainer.py >> "$LOG_FILE" 2>&1

RESULT=$?

echo "" >> "$LOG_FILE"
if [ $RESULT -eq 0 ]; then
    echo "✅ Training completed successfully" >> "$LOG_FILE"
    echo "New model saved to: finrl_agent" >> "$LOG_FILE"
    echo "Metrics: $(cat finrl_metrics.json 2>/dev/null)" >> "$LOG_FILE"
else
    echo "❌ Training failed with exit code $RESULT" >> "$LOG_FILE"
fi
echo "Time: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"
