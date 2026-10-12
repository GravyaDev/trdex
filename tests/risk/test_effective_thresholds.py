"""Priority rules for per-position SL/TP in the StopLossMonitor.

Operator config wins over everything; an agent-position SL can only
widen the volatility floor, never tighten it; a Telegram position keeps
the signal's own stop (bounded upstream by the stop-distance gate).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from trdex.risk.stop_loss import effective_thresholds

BASE = dict(base_sl=0.02, base_tp=0.04, base_trail=0.015)


def _pos(source: str = "agent", sl: float | None = None, tp: float | None = None):
    return SimpleNamespace(source=source, stop_loss_pct=sl, take_profit_pct=tp)


def _override(sl=None, tp=None, trail=None):
    return SimpleNamespace(sl_pct=sl, tp_pct=tp, trailing_pct=trail)


def test_no_position_values_uses_adaptive_floor():
    sl, tp, trail = effective_thresholds(_pos(), None, cv=0.10, **BASE)
    assert sl == pytest.approx(0.25)  # 2.5 x CV
    assert tp == pytest.approx(0.50)  # 5 x CV
    assert trail == pytest.approx(0.15)


def test_agent_sl_cannot_tighten_below_volatility_floor():
    # High-vol coin: floor 2.5 x 0.13 = 32.5%; a 3% stop would whipsaw.
    sl, _, _ = effective_thresholds(_pos(sl=0.03), None, cv=0.13, **BASE)
    assert sl == pytest.approx(0.325)


def test_agent_sl_can_widen_above_floor():
    sl, _, _ = effective_thresholds(_pos(sl=0.08), None, cv=0.004, **BASE)
    assert sl == pytest.approx(0.08)


def test_agent_sl_cannot_go_below_operator_base():
    sl, _, _ = effective_thresholds(_pos(sl=0.01), None, cv=0.0, **BASE)
    assert sl == pytest.approx(0.02)


def test_symbol_override_beats_position_values():
    sl, tp, trail = effective_thresholds(
        _pos(sl=0.08, tp=0.15),
        _override(sl=0.04, tp=0.06, trail=0.02),
        cv=0.05,
        **BASE,
    )
    assert (sl, tp, trail) == (0.04, 0.06, 0.02)


def test_position_tp_used_when_no_override():
    _, tp, _ = effective_thresholds(_pos(tp=0.12), None, cv=0.0, **BASE)
    assert tp == pytest.approx(0.12)


def test_telegram_position_keeps_signal_stop_even_below_floor():
    # The signal's own stop is the strategy being followed; widening it
    # would make live results diverge from the observe-only scoring.
    sl, _, _ = effective_thresholds(_pos(source="telegram", sl=0.03), None, cv=0.13, **BASE)
    assert sl == pytest.approx(0.03)


def test_telegram_position_without_stop_falls_back_to_floor():
    sl, _, _ = effective_thresholds(_pos(source="telegram"), None, cv=0.13, **BASE)
    assert sl == pytest.approx(0.325)
