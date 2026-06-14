"""
Loads rl_q_table.json (produced by train_rl.py) and exposes a lookup that
maps current indicators + position state to a learned BUY/SELL/HOLD signal.

This is a supplementary signal for the agent — not an autonomous trader.
If rl_q_table.json is missing, get_rl_signal degrades gracefully to "unknown".
"""

import json
import os

ACTIONS = ["BUY", "SELL", "HOLD"]

_Q_PATH = os.path.join(os.path.dirname(__file__), "rl_q_table.json")
_q_table = None


def _load():
    global _q_table
    if _q_table is None:
        try:
            with open(_Q_PATH) as f:
                _q_table = json.load(f)
        except Exception:
            _q_table = {}
    return _q_table


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
