#!/bin/bash
# Cron Test - Run LLM+FinRL only (NO MCP ORDERS)
# Tests cron mechanism without placing trades

BOT_DIR="/Users/ramayalala/trading_bot_uw"
LOG_DIR="$BOT_DIR/logs"
LOG_FILE="$LOG_DIR/cron_test_$(date +%Y-%m-%d_%H-%M-%S).log"

# Create logs directory
mkdir -p "$LOG_DIR"

echo "========================================" >> "$LOG_FILE"
echo "CRON TEST: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# Verify Ollama is running
echo "[$(date)] Checking Ollama..." >> "$LOG_FILE"
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "[$(date)] ❌ Ollama not running at localhost:11434" >> "$LOG_FILE"
    echo "FAILED" >> "$LOG_FILE"
    exit 1
fi
echo "[$(date)] ✅ Ollama running" >> "$LOG_FILE"

# Run LLM+FinRL test (no MCP)
cd "$BOT_DIR"
echo "[$(date)] Starting LLM+FinRL test..." >> "$LOG_FILE"

python3 test_llm_finrl.py >> "$LOG_FILE" 2>&1

RESULT=$?

if [ $RESULT -eq 0 ]; then
    echo "[$(date)] ✅ Cron test completed successfully" >> "$LOG_FILE"
    echo "SUCCESS" >> "$LOG_FILE"
else
    echo "[$(date)] ❌ Cron test failed with exit code $RESULT" >> "$LOG_FILE"
    echo "FAILED" >> "$LOG_FILE"
fi

# Display results
echo ""
echo "========================================"
echo "CRON TEST RESULTS"
echo "========================================"
echo ""
cat "$LOG_FILE"
echo ""
echo "Log saved to: $LOG_FILE"
echo ""

exit $RESULT
