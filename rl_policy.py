"""
Loads rl_q_table.json (produced by train_rl.py) and exposes a lookup that
maps current indicators + position state to a learned BUY/SELL/HOLD signal.

This is a supplementary signal for the agent — not an autonomous trader.
If rl_q_table.json is missing, get_rl_signal degrades gracefully to "unknown".
"""

import json
import os

ACTIONS = ["BUY", "SELL", "HOLD"]

ALPHA = 0.1     # learning rate for online updates
GAMMA = 0.95    # discount factor

# Live, writable copy of the table (persisted volume). Falls back to the
# bundled snapshot from train_rl.py if no live copy exists yet.
_DATA_DIR     = os.environ.get("DATA_DIR", ".")
_LIVE_Q_PATH  = os.path.join(_DATA_DIR, "rl_q_table.json")
_BUNDLED_PATH = os.path.join(os.path.dirname(__file__), "rl_q_table.json")
_q_table = None


def _load():
    global _q_table
    if _q_table is None:
        for path in (_LIVE_Q_PATH, _BUNDLED_PATH):
            try:
                with open(path) as f:
                    _q_table = json.load(f)
                    break
            except Exception:
                continue
        else:
            _q_table = {}
    return _q_table


def _save():
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(_LIVE_Q_PATH, "w") as f:
            json.dump(_q_table, f, indent=2)
    except Exception:
        pass


def update_q(state: str, action: str, reward: float, next_state: str) -> None:
    """Online Q-learning update from a real, closed trade outcome.

    Call this when a position is sold: `state`/`action` describe the
    situation when it was bought (action is normally "BUY"), `reward` is the
    realized return on the trade, and `next_state` is the current market
    state (post-sale, flat). Persists the updated table immediately.
    """
    q = _load()
    if action not in ACTIONS:
        return
    idx = ACTIONS.index(action)
    qvals = q.setdefault(state, [0.0, 0.0, 0.0])
    next_q = q.get(next_state, [0.0, 0.0, 0.0])
    qvals[idx] += ALPHA * (reward + GAMMA * max(next_q) - qvals[idx])
    _save()


def discretize(rsi, macd, price, vwap, volume_ratio, holding):
    if rsi < 30: rsi_b = "rsi_low"
    elif rsi > 70: rsi_b = "rsi_high"
    else: rsi_b = "rsi_mid"

    macd_b = "macd_pos" if macd > 0 else "macd_neg"
    vwap_b = "above_vwap" if price > vwap else "below_vwap"

    if volume_ratio >= 2.0: vol_b = "vol_high"
    elif volume_ratio >= 1.0: vol_b = "vol_mid"
    else: vol_b = "vol_low"

    pos_b = "holding" if holding else "flat"

    return "|".join([rsi_b, macd_b, vwap_b, vol_b, pos_b])


def get_rl_signal(rsi, macd, price, vwap, volume_ratio, holding=False):
    """Return {"action": "BUY"|"SELL"|"HOLD"|"UNKNOWN", "confidence": float, "q_values": {...}}"""
    q = _load()
    if not q:
        return {"action": "UNKNOWN", "confidence": 0.0, "q_values": {}}

    state = discretize(rsi, macd, price, vwap, volume_ratio, holding)
    qvals = q.get(state)
    if qvals is None:
        return {"action": "UNKNOWN", "confidence": 0.0, "q_values": {}, "state": state}

    best_idx = max(range(3), key=lambda i: qvals[i])
    spread = max(qvals) - min(qvals)
    return {
        "action":     ACTIONS[best_idx],
        "confidence": round(spread, 5),
        "q_values":   dict(zip(ACTIONS, [round(v, 5) for v in qvals])),
        "state":      state,
    }
