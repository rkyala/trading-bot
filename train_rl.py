"""
Tabular Q-learning trainer for the trading bot.

Trains a simple Q-learning agent on historical daily data (same indicators
bot.py already computes: RSI, MACD, VWAP, volume ratio) for the symbols in
SYMBOLS. State = discretized (rsi_bucket, macd_sign, price_vs_vwap, vol_bucket,
holding). Actions = BUY, SELL, HOLD. Reward = next-day return on the position
taken (with a small penalty for churning).

Output: rl_q_table.json — a dict mapping "state" -> [q_buy, q_sell, q_hold],
loaded at runtime by rl_policy.py and exposed to the agent as a get_rl_signal tool.

This is intentionally simple (tabular, daily bars, single-symbol episodes) so
it can run locally with `python train_rl.py` in under a minute. It is a
learned *signal*, not an autonomous trader — bot.py still uses Claude to make
the final call, with this as one more input.
"""

import json
import random

import yfinance as yf

SYMBOLS  = ["META", "MU", "TSLA", "NVDA", "SOXL", "SPXL", "NVDL", "ROKU", "ASTS", "RKLB"]
YEARS    = "3y"
ACTIONS  = ["BUY", "SELL", "HOLD"]

ALPHA   = 0.1     # learning rate
GAMMA   = 0.95    # discount factor
EPSILON = 0.2     # exploration rate
EPISODES = 30     # passes over each symbol's history


def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains = losses = 0.0
    for i in range(-period, 0):
        d = prices[i] - prices[i - 1]
        if d > 0: gains += d
        else:     losses += abs(d)
    avg_g = gains / period
    avg_l = losses / period or 1e-9
    return round(100 - 100 / (1 + avg_g / avg_l), 2)


def calc_ema(prices, period):
    if len(prices) < period:
        return prices[-1]
    k   = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def discretize(closes, volumes, holding):
    """Map a window of price/volume history + position state to a state key."""
    rsi  = calc_rsi(closes)
    macd = calc_ema(closes, 12) - calc_ema(closes, 26)
    n       = min(len(closes), len(volumes))
    vwap    = sum(closes[i] * volumes[i] for i in range(n)) / (sum(volumes[:n]) or 1)
    avg_vol = sum(volumes[-10:]) / 10
    vol_ratio = volumes[-1] / avg_vol if avg_vol else 1

    if rsi < 30: rsi_b = "rsi_low"
    elif rsi > 70: rsi_b = "rsi_high"
    else: rsi_b = "rsi_mid"

    macd_b = "macd_pos" if macd > 0 else "macd_neg"
    vwap_b = "above_vwap" if closes[-1] > vwap else "below_vwap"

    if vol_ratio >= 2.0: vol_b = "vol_high"
    elif vol_ratio >= 1.0: vol_b = "vol_mid"
    else: vol_b = "vol_low"

    pos_b = "holding" if holding else "flat"

    return "|".join([rsi_b, macd_b, vwap_b, vol_b, pos_b])


def build_episode_data(symbol):
    hist = yf.Ticker(symbol).history(period=YEARS, interval="1d")
    if hist.empty or len(hist) < 60:
        return None
    closes  = hist["Close"].tolist()
    volumes = hist["Volume"].tolist()
    return closes, volumes


def train():
    q = {}

    def get_q(state):
        if state not in q:
            q[state] = [0.0, 0.0, 0.0]
        return q[state]

    for symbol in SYMBOLS:
        data = build_episode_data(symbol)
        if not data:
            print(f"skip {symbol} (no data)")
            continue
        closes, volumes = data
        print(f"training on {symbol}: {len(closes)} bars")

        for ep in range(EPISODES):
            holding = False
            for t in range(30, len(closes) - 1):
                state = discretize(closes[:t + 1], volumes[:t + 1], holding)
                qvals = get_q(state)

                if random.random() < EPSILON:
                    action_idx = random.randrange(3)
                else:
                    action_idx = max(range(3), key=lambda i: qvals[i])
                action = ACTIONS[action_idx]

                ret = (closes[t + 1] - closes[t]) / closes[t]

                if action == "BUY":
                    reward = ret if not holding else -0.0005   # penalty for redundant buy
                    next_holding = True
                elif action == "SELL":
                    reward = -ret if holding else -0.0005       # penalty for selling nothing
                    next_holding = False
                else:  # HOLD
                    reward = ret if holding else 0.0
                    next_holding = holding

                next_state = discretize(closes[:t + 2], volumes[:t + 2], next_holding)
                next_q = get_q(next_state)

                qvals[action_idx] += ALPHA * (reward + GAMMA * max(next_q) - qvals[action_idx])
                holding = next_holding

    return q


def main():
    random.seed(42)
    q = train()
    with open("rl_q_table.json", "w") as f:
        json.dump(q, f, indent=2)
    print(f"\nWrote {len(q)} states to rl_q_table.json")


if __name__ == "__main__":
    main()
