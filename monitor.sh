#!/bin/bash
# Trading Bot Live Monitor Dashboard
# Usage: ./monitor.sh

clear

while true; do
  clear

  echo "╔════════════════════════════════════════════════════════════════╗"
  echo "║            TRADING BOT LIVE MONITOR - $(date '+%Y-%m-%d %H:%M:%S')            ║"
  echo "╚════════════════════════════════════════════════════════════════╝"
  echo ""

  # Current time
  CDT_TIME=$(TZ=America/Chicago date '+%H:%M:%S')
  echo "🕐 Current Time (CDT): $CDT_TIME"
  echo ""

  # Market status
  HOUR=$(TZ=America/Chicago date +%H)
  if [ "$HOUR" -ge 09 ] && [ "$HOUR" -lt 16 ]; then
    echo "📊 Market Status: 🟢 OPEN (9:30 AM - 4:00 PM CDT)"
  else
    echo "📊 Market Status: 🔴 CLOSED"
  fi
  echo ""

  # Recent cycles
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "📈 RECENT CYCLES (Last 5):"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  grep "CYCLE" ~/trading_bot/bot_production.log | tail -5 | sed 's/^/  /'
  echo ""

  # Latest signals
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "📊 LATEST SIGNALS (Last 5):"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  if grep "SIGNAL:" ~/trading_bot/bot_production.log >/dev/null 2>&1; then
    grep "SIGNAL:" ~/trading_bot/bot_production.log | tail -5 | sed 's/^/  /'
  else
    echo "  (No signals yet)"
  fi
  echo ""

  # File size and last update
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "📋 LOG STATUS:"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  LOG_FILE="~/trading_bot/bot_production.log"
  if [ -f ~/trading_bot/bot_production.log ]; then
    LOG_SIZE=$(du -h ~/trading_bot/bot_production.log | cut -f1)
    LOG_TIME=$(stat -f "%Sm" ~/trading_bot/bot_production.log)
    echo "  Log File: bot_production.log"
    echo "  Size: $LOG_SIZE"
    echo "  Last Update: $LOG_TIME"
  fi
  echo ""

  # Running processes
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "⚙️  RUNNING PROCESSES:"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  if pgrep -f "robinhood_mcp_local.py" >/dev/null 2>&1; then
    echo "  ✅ MCP Server: Running"
  else
    echo "  ⏸️  MCP Server: Not running"
  fi

  if pgrep -f "bot_production_final.py" >/dev/null 2>&1; then
    echo "  ✅ Bot: Running"
  else
    echo "  ⏸️  Bot: Not running (waiting for cron)"
  fi
  echo ""

  # Statistics
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "📊 TODAY'S STATISTICS:"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  SIGNAL_COUNT=$(grep -c "SIGNAL:" ~/trading_bot/bot_production.log 2>/dev/null || echo "0")
  CYCLE_COUNT=$(grep -c "CYCLE" ~/trading_bot/bot_production.log 2>/dev/null || echo "0")
  ERROR_COUNT=$(grep -c "❌" ~/trading_bot/bot_production.log 2>/dev/null || echo "0")

  echo "  Total Cycles: $CYCLE_COUNT"
  echo "  Total Signals: $SIGNAL_COUNT"
  echo "  Errors: $ERROR_COUNT"
  echo ""

  # Footer
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "Refreshing every 5 seconds... (Press Ctrl+C to exit)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  sleep 5
done
