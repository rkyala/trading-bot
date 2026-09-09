#!/usr/bin/env python3
"""
Tests for the UW options confirmation layer.

The critical property is NEGATIVE: in shadow mode this module must not be able
to change which trades execute, and no failure inside it may propagate into the
production bot. Every other test is secondary to those two.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uw_confirmation import (OptionsConfirmation, Confirmation, analyse_ab,
                             CONFIRM_AT, CONTRADICT_AT, MAX_CONF_ADJ,
                             MIN_GROSS_CONTRACTS, MIN_VOL_OI)

TRADES = [
    {"symbol": "AAA", "confidence": 80, "action": "BUY", "capital_deployed": 500},
    {"symbol": "BBB", "confidence": 60, "action": "BUY", "capital_deployed": 400},
    {"symbol": "CCC", "confidence": 95, "action": "BUY", "capital_deployed": 600},
]


def _oc(**kw):
    o = OptionsConfirmation(api_key="test-key", **kw)
    return o


class ShadowSafety(unittest.TestCase):
    """The layer must be incapable of altering production behaviour."""

    def test_shadow_preserves_trades_exactly(self):
        o = _oc(shadow=True)
        with patch.object(o, "_get", return_value=None):
            with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
                pass
            with patch("uw_confirmation.AB_LOG", f.name):
                out = o.annotate(TRADES)
        self.assertEqual(len(out), len(TRADES))
        for a, b in zip(out, TRADES):
            self.assertEqual(a["symbol"], b["symbol"])
            self.assertEqual(a["confidence"], b["confidence"])
            self.assertEqual(a["capital_deployed"], b["capital_deployed"])
        os.unlink(f.name)

    def test_annotate_never_raises_on_bad_data(self):
        o = _oc(shadow=True)
        for bad in ([{}], [{"symbol": None}], [{"symbol": ""}], [], None):
            with patch.object(o, "_get", side_effect=RuntimeError("boom")):
                try:
                    o.annotate(bad)
                except Exception as e:
                    self.fail(f"annotate raised on {bad!r}: {e}")

    def test_confirm_never_raises(self):
        o = _oc()
        with patch.object(o, "_get", side_effect=Exception("network gone")):
            c = o.confirm("XYZ", "BUY", 70)
        self.assertFalse(c.available)
        self.assertEqual(c.adjusted_confidence, 70)

    def test_missing_api_key_fails_open(self):
        o = OptionsConfirmation(api_key=None)
        c = o.confirm("AAPL", "BUY", 70)
        self.assertFalse(c.available)
        self.assertEqual(c.score, 0.0)
        self.assertEqual(c.adjusted_confidence, 70)

    def test_unavailable_leaves_confidence_untouched(self):
        o = _oc()
        with patch.object(o, "_get", return_value=None):
            c = o.confirm("AAPL", "BUY", 63.5)
        self.assertEqual(c.adjusted_confidence, 63.5)
        self.assertEqual(c.verdict, "UNAVAILABLE")


class Scoring(unittest.TestCase):

    def test_confidence_adjustment_is_capped(self):
        o = _oc()
        for score in (-100, -50, 0, 50, 100):
            with patch.object(o, "_tape_bias", return_value=score), \
                 patch.object(o, "_opening_bias", return_value=score), \
                 patch.object(o, "_iv_context", return_value=score), \
                 patch.object(o, "_gamma_regime", return_value=1.0):
                c = o.confirm("X", "BUY", 70)
            self.assertLessEqual(abs(c.adjusted_confidence - 70), MAX_CONF_ADJ + 1e-6,
                                 f"score {score} moved confidence too far")

    def test_score_clamped_to_range(self):
        o = _oc()
        with patch.object(o, "_tape_bias", return_value=99999), \
             patch.object(o, "_opening_bias", return_value=99999), \
             patch.object(o, "_iv_context", return_value=99999), \
             patch.object(o, "_gamma_regime", return_value=1.0):
            c = o.confirm("X", "BUY", 70)
        self.assertLessEqual(c.score, 100.0)
        self.assertGreaterEqual(c.score, -100.0)

    def test_sell_direction_inverts_score(self):
        o = _oc()
        kw = dict(return_value=60)
        with patch.object(o, "_tape_bias", **kw), \
             patch.object(o, "_opening_bias", **kw), \
             patch.object(o, "_iv_context", **kw), \
             patch.object(o, "_gamma_regime", return_value=1.0):
            buy = o.confirm("X", "BUY", 70)
            sell = o.confirm("X", "SELL", 70)
        self.assertAlmostEqual(buy.score, -sell.score, places=6)

    def test_verdict_thresholds(self):
        o = _oc()
        for val, want in ((80, "CONFIRM"), (0, "NEUTRAL"), (-80, "CONTRADICT")):
            with patch.object(o, "_tape_bias", return_value=val), \
                 patch.object(o, "_opening_bias", return_value=val), \
                 patch.object(o, "_iv_context", return_value=val), \
                 patch.object(o, "_gamma_regime", return_value=1.0):
                c = o.confirm("X", "BUY", 70)
            self.assertEqual(c.verdict, want, f"{val} -> {c.verdict}")

    def test_disagreeing_components_are_damped(self):
        """A verdict whose own inputs conflict must score lower than a unanimous one."""
        o = _oc()
        with patch.object(o, "_tape_bias", return_value=80), \
             patch.object(o, "_opening_bias", return_value=80), \
             patch.object(o, "_iv_context", return_value=80), \
             patch.object(o, "_gamma_regime", return_value=1.0):
            agree = o.confirm("X", "BUY", 70).score
        with patch.object(o, "_tape_bias", return_value=80), \
             patch.object(o, "_opening_bias", return_value=-80), \
             patch.object(o, "_iv_context", return_value=80), \
             patch.object(o, "_gamma_regime", return_value=1.0):
            conflict = o.confirm("X", "BUY", 70).score
        self.assertLess(abs(conflict), abs(agree))

    def test_missing_component_renormalises(self):
        """One dead component must not silently halve every score."""
        o = _oc()
        with patch.object(o, "_tape_bias", return_value=100), \
             patch.object(o, "_opening_bias", return_value=None), \
             patch.object(o, "_iv_context", return_value=None), \
             patch.object(o, "_gamma_regime", return_value=None):
            c = o.confirm("X", "BUY", 70)
        self.assertAlmostEqual(c.score, 100.0, places=6)


class Components(unittest.TestCase):

    def test_tape_is_measured_relative_to_market(self):
        """
        Absolute tape readings measure beta. A stock matching SPY exactly must
        score 0, not strongly negative.
        """
        o = _oc()
        with patch.object(o, "_raw_tape_ratio", return_value=-0.012):
            self.assertAlmostEqual(o._tape_bias("AAPL"), 0.0, places=6)

    def test_tape_thin_volume_returns_none(self):
        o = _oc()
        rows = [{"net_delta": "1000", "call_volume": 10, "put_volume": 5}]
        with patch.object(o, "_get", return_value=rows):
            self.assertIsNone(o._raw_tape_ratio("X"))

    def test_opening_excludes_multileg_and_closing_flow(self):
        o = _oc()
        rows = [
            # spread — must be ignored
            {"has_singleleg": True, "has_multileg": True, "volume_oi_ratio": 5,
             "type": "call", "total_ask_side_prem": "9999999", "total_bid_side_prem": "0"},
            # closing flow (vol < OI) — must be ignored
            {"has_singleleg": True, "has_multileg": False, "volume_oi_ratio": 0.1,
             "type": "call", "total_ask_side_prem": "9999999", "total_bid_side_prem": "0"},
        ]
        with patch.object(o, "_get", return_value=rows):
            self.assertIsNone(o._opening_bias("X"))

    def test_sold_call_is_bearish(self):
        """Direction comes from aggressor side, never from call/put alone."""
        o = _oc()
        rows = [{"has_singleleg": True, "has_multileg": False, "volume_oi_ratio": 5,
                 "type": "call", "total_ask_side_prem": "0",
                 "total_bid_side_prem": "1000000"} for _ in range(6)]
        with patch.object(o, "_get", return_value=rows):
            self.assertLess(o._opening_bias("X"), 0)

    def test_sold_put_is_bullish(self):
        o = _oc()
        rows = [{"has_singleleg": True, "has_multileg": False, "volume_oi_ratio": 5,
                 "type": "put", "total_ask_side_prem": "0",
                 "total_bid_side_prem": "1000000"} for _ in range(6)]
        with patch.object(o, "_get", return_value=rows):
            self.assertGreater(o._opening_bias("X"), 0)

    def test_gamma_is_magnitude_only_not_direction(self):
        """Gamma must never move the directional score — it is a move-size forecast."""
        o = _oc()
        base = dict(_tape_bias=50, _opening_bias=50, _iv_context=50)
        scores = []
        for g in (0.65, 1.07):
            with patch.object(o, "_tape_bias", return_value=base["_tape_bias"]), \
                 patch.object(o, "_opening_bias", return_value=base["_opening_bias"]), \
                 patch.object(o, "_iv_context", return_value=base["_iv_context"]), \
                 patch.object(o, "_gamma_regime", return_value=g):
                c = o.confirm("X", "BUY", 70)
                scores.append(c.score)
                self.assertAlmostEqual(c.expected_move_mult, g, places=3)
        self.assertAlmostEqual(scores[0], scores[1], places=6)

    def test_gamma_percentile_direction(self):
        """Most positive gamma => smallest expected move."""
        o = _oc()
        rising = [{"call_gamma": str(i), "put_gamma": "0"} for i in range(100)]
        with patch.object(o, "_get", return_value=rising):
            high = o._gamma_regime("X")          # current = highest gamma
        falling = [{"call_gamma": str(100 - i), "put_gamma": "0"} for i in range(100)]
        with patch.object(o, "_get", return_value=falling):
            low = o._gamma_regime("X")           # current = lowest gamma
        self.assertLess(high, low)


class ABLog(unittest.TestCase):

    def test_log_and_analyse_roundtrip(self):
        o = _oc(shadow=True)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ab.jsonl")
            c = Confirmation(symbol="AAA", direction="BUY", available=True,
                             score=50, verdict="CONFIRM", base_confidence=70,
                             adjusted_confidence=75)
            o.log_ab(c, {"symbol": "AAA", "confidence": 70}, path=p)
            rows = [json.loads(l) for l in open(p)]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["verdict"], "CONFIRM")
            self.assertIn("needs >=100", analyse_ab(p))

    def test_analyse_handles_missing_file(self):
        self.assertIn("no A/B log", analyse_ab("/nonexistent/path.jsonl"))

    def test_log_failure_is_swallowed(self):
        o = _oc()
        c = Confirmation(symbol="A", direction="BUY")
        o.log_ab(c, {}, path="/nonexistent/dir/x.jsonl")   # must not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
