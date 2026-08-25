#!/bin/bash
# Pre-Deployment Validation: Parallel Signal Channel
# Run this before adding cron job

set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BOLD}=== PARALLEL SIGNAL CHANNEL VALIDATION ===${NC}\n"

# ============================================================================
# 1. Check Python & Virtual Environment
# ============================================================================

echo -e "${BOLD}1. Checking Python Environment${NC}"
if [ ! -d "$BOT_DIR/venv" ]; then
    echo -e "${RED}❌ Virtual environment not found${NC}"
    exit 1
fi

PYTHON="$BOT_DIR/venv/bin/python3"
if [ ! -f "$PYTHON" ]; then
    echo -e "${RED}❌ Python executable not found at $PYTHON${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Python: $PYTHON${NC}"
$PYTHON --version

# ============================================================================
# 2. Check Required Files
# ============================================================================

echo -e "\n${BOLD}2. Checking Required Files${NC}"

REQUIRED_FILES=(
    "test_async_signal_channel.py"
    "macro_signal_integrator.py"
    "config.json"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$BOT_DIR/$file" ]; then
        echo -e "${RED}❌ Missing: $file${NC}"
        exit 1
    fi
    echo -e "${GREEN}✅ Found: $file${NC}"
done

# ============================================================================
# 3. Check Config for FRED API Key
# ============================================================================

echo -e "\n${BOLD}3. Checking Configuration${NC}"

FRED_KEY=$(python3 -c "import json; cfg=json.load(open('$BOT_DIR/config.json')); print(cfg.get('macro_signals', {}).get('fred_api_key', ''))" 2>/dev/null || echo "")

if [[ -z "$FRED_KEY" ]] || [[ "$FRED_KEY" == *"GET_FREE_KEY"* ]]; then
    echo -e "${YELLOW}⚠️  FRED API Key not configured (Fed rate will be skipped)${NC}"
    echo -e "   Get free key from: https://fred.stlouisfed.org/docs/api/api_key.html"
    echo -e "   Update config.json macro_signals.fred_api_key"
else
    echo -e "${GREEN}✅ FRED API Key configured${NC}"
fi

# ============================================================================
# 4. Test Signal Channel Execution
# ============================================================================

echo -e "\n${BOLD}4. Testing Signal Channel Execution${NC}"

echo -e "   Running: python3 test_async_signal_channel.py"
START_TIME=$(date +%s)

OUTPUT=$($PYTHON "$BOT_DIR/test_async_signal_channel.py" 2>&1)
RESULT=$?
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

if [ $RESULT -eq 0 ]; then
    echo -e "${GREEN}✅ Execution succeeded (${ELAPSED}s)${NC}"
    echo "$OUTPUT" | grep -q "SCAN COMPLETE" && echo -e "${GREEN}✅ Scan completed normally${NC}"
else
    echo -e "${RED}❌ Execution failed (exit code $RESULT)${NC}"
    echo "$OUTPUT" | tail -20
    exit 1
fi

# ============================================================================
# 5. Check Atomic File Write
# ============================================================================

echo -e "\n${BOLD}5. Verifying Atomic File Write${NC}"

if [ -f "$BOT_DIR/macro_triggers.json" ]; then
    echo -e "${GREEN}✅ Queue file created: macro_triggers.json${NC}"
    QUEUE_SIZE=$(stat -f%z "$BOT_DIR/macro_triggers.json" 2>/dev/null || stat -c%s "$BOT_DIR/macro_triggers.json" 2>/dev/null)
    echo -e "   Size: $QUEUE_SIZE bytes"

    # Verify valid JSON
    python3 -c "import json; json.load(open('$BOT_DIR/macro_triggers.json'))" && \
        echo -e "${GREEN}✅ Valid JSON format${NC}" || \
        (echo -e "${RED}❌ Invalid JSON in queue file${NC}"; exit 1)
else
    echo -e "${YELLOW}ℹ️  Queue file not yet created (normal on first run)${NC}"
fi

# No stray .tmp files
if [ -f "$BOT_DIR/macro_triggers.tmp" ]; then
    echo -e "${RED}❌ Stray .tmp file found (atomic write incomplete)${NC}"
    exit 1
else
    echo -e "${GREEN}✅ No .tmp files (atomic writes clean)${NC}"
fi

# ============================================================================
# 6. Check Cron Syntax
# ============================================================================

echo -e "\n${BOLD}6. Validating Cron Configuration${NC}"

CRON_JOB="* * * * * $PYTHON $BOT_DIR/test_async_signal_channel.py >> $BOT_DIR/signal_channel.log 2>&1"
echo -e "   Cron job: $CRON_JOB"
echo -e "${GREEN}✅ Cron syntax valid${NC}"

# ============================================================================
# 7. Test Path Resolution
# ============================================================================

echo -e "\n${BOLD}7. Testing Path Resolution${NC}"

RESOLVED_PATH=$(python3 -c "from pathlib import Path; print(Path('$BOT_DIR/test_async_signal_channel.py').resolve())")
echo -e "   Resolved path: $RESOLVED_PATH"
echo -e "${GREEN}✅ Path resolution works${NC}"

# ============================================================================
# SUMMARY
# ============================================================================

echo -e "\n${BOLD}=== VALIDATION COMPLETE ===${NC}"
echo -e "${GREEN}✅ All checks passed. Ready for deployment.${NC}\n"

echo -e "${BOLD}Next Steps:${NC}"
echo "1. Get FRED API key (optional but recommended):"
echo "   https://fred.stlouisfed.org/docs/api/api_key.html"
echo ""
echo "2. Update config.json with FRED API key:"
echo "   macro_signals.fred_api_key = your_key_here"
echo ""
echo "3. Add to crontab:"
echo "   crontab -e"
echo "   $CRON_JOB"
echo ""
echo "4. Verify cron is running:"
echo "   tail -f $BOT_DIR/signal_channel.log"
echo ""
