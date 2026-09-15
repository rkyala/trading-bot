#!/bin/bash
# Setup Paper Trading Environment (Zero Cost)

set -e

echo "=========================================="
echo "  PAPER TRADING SETUP"
echo "=========================================="
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Python version: $PYTHON_VERSION"

# Create virtual environment (optional but recommended)
if [ ! -d "venv_paper" ]; then
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv venv_paper
    source venv_paper/bin/activate
    echo "✓ Virtual environment created"
fi

# Activate virtual environment
source venv_paper/bin/activate

# Install dependencies
echo ""
echo "Installing dependencies (this may take 5-10 min)..."
pip install -q -r paper_trading_requirements.txt
echo "✓ Dependencies installed"

# Create directories
mkdir -p paper_trading_reports
mkdir -p finrl_logs

# Download data (one-time)
echo ""
echo "Ready to train agent!"
echo ""
echo "NEXT STEPS:"
echo "=========="
echo ""
echo "1. Train the FinRL agent (runs 1-2 hours on your Mac):"
echo "   python3 finrl_trainer.py"
echo ""
echo "2. Run paper trading for 30 days:"
echo "   python3 paper_trading.py"
echo ""
echo "3. Check results in:"
echo "   - paper_trading_reports/ (daily JSON reports)"
echo "   - paper_trading_log.csv (all trades)"
echo "   - training_metrics.json (model metrics)"
echo ""
echo "=========================================="
echo ""
