#!/bin/bash
# Trading Bot Cycle Wrapper - macOS compatible with timeout

cd /Users/ramayalala/trading_bot

# Use explicit Python path to ensure correct environment with pandas
PYTHON=/usr/bin/python3

# Start MCP server in background
$PYTHON robinhood_mcp_local.py > mcp_server.log 2>&1 &
MCP_PID=$!
sleep 3

# Run bot with 300-second timeout using sleep & kill approach
$PYTHON bot_production_final.py >> bot_production.log 2>&1 &
BOT_PID=$!

# Wait for bot to complete or timeout after 300 seconds
COUNTER=0
MAX_WAIT=300
while kill -0 $BOT_PID 2>/dev/null && [ $COUNTER -lt $MAX_WAIT ]; do
  sleep 1
  COUNTER=$((COUNTER + 1))
done

# If bot is still running after timeout, kill it
if kill -0 $BOT_PID 2>/dev/null; then
  echo "WARNING: Bot exceeded 300s timeout, killing process" >> bot_production.log 2>&1
  kill -9 $BOT_PID 2>/dev/null
fi

# Cleanup MCP server
kill $MCP_PID 2>/dev/null || true
wait $MCP_PID 2>/dev/null || true

exit 0
