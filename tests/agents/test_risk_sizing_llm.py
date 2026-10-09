"""llm-agents: risk-based sizing uses the stop the monitor will apply to the
stored position, i.e. max(adaptive floor, LLM-suggested stop) — PR #9's
``effective_thresholds`` rule — and keeps #9's meaning of
``RiskDecision.stop_loss_pct`` (the LLM suggestion, None when absent)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from trdex.agents.intent import Intent
from trdex.agents.risk import risk_node
from trdex.agents.state import AgentState, AnalysisResult, MarketSnapshot, PortfolioContext
from trdex.risk.sizing import recent_cv
from trdex.risk.stop_loss import effective_thresholds

FLAT = [100.0] * 30  # floor = base 2%
WILD = [100.0, 130.0] * 15  # floor = 2.5 x CV ~ 33%
BASE = {"base_sl": 0.02, "base_tp": 0.04, "base_trail": 0.015}


def _state(closes, sl=None, tp=None) -> AgentState:
    candles = [(i, c, c, c, c, 1.0) for i, c in enumerate(closes)]
    return AgentState(
        symbol="ENJ/USDT",
        run_id="r-llm-sizing",
        market=MarketSnapshot(symbol="ENJ/USDT", price=closes[-1], candles=candles),
        analysis=AnalysisResult(
            intent=Intent.OPEN_LONG,
            confidence=0.8,
            suggested_stop_loss=sl,
            suggested_take_profit=tp,
        ),
        portfolio=PortfolioContext(equity=10_000.0),
    )


async def _run(state):
    ks = AsyncMock()
    ks.active = False
    with (
        patch("trdex.risk.stop_loss.get_kill_switch", return_value=ks),
        patch("trdex.services.runtime_config.get_config_service", return_value=None),
    ):
        return await risk_node(state)


def _monitor_stop(result, closes) -> float:
    """Stop the StopLossMonitor applies to the position this decision opens."""
    pos = SimpleNamespace(
        stop_loss_pct=result.risk.stop_loss_pct,
        take_profit_pct=result.risk.take_profit_pct,
        source="agent",
    )
    return effective_thresholds(pos, None, recent_cv(closes) or 0.0, **BASE)[0]


@pytest.mark.asyncio
async def test_llm_stop_wider_than_the_floor_shrinks_the_position():
    result = await _run(_state(FLAT, sl=0.08))
    assert result.risk.stop_loss_pct == pytest.approx(0.08)  # #9: stored as suggested
    assert result.risk.position_size == pytest.approx(0.001 / 0.08)


@pytest.mark.asyncio
async def test_llm_stop_inside_the_floor_is_sized_on_the_floor():
    result = await _run(_state(WILD, sl=0.03))
    floor = 2.5 * recent_cv(WILD)
    assert result.risk.stop_loss_pct == pytest.approx(0.03)  # #9: the monitor floors it
    assert result.risk.position_size == pytest.approx(0.001 / floor)


@pytest.mark.asyncio
async def test_without_llm_stop_sizing_matches_main():
    result = await _run(_state(WILD))
    assert result.risk.stop_loss_pct is None
    assert result.risk.position_size == pytest.approx(0.001 / (2.5 * recent_cv(WILD)))


@pytest.mark.asyncio
async def test_clipped_llm_stop_is_the_one_used_for_sizing():
    result = await _run(_state(FLAT, sl=0.30))  # clipped to the 10% max
    assert result.risk.stop_loss_pct == pytest.approx(0.10)
    assert result.risk.position_size == pytest.approx(0.001 / 0.10)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "closes,sl", [(FLAT, None), (FLAT, 0.05), (WILD, None), (WILD, 0.03), (WILD, 0.10)]
)
async def test_risk_at_the_monitor_stop_is_always_the_configured_risk(closes, sl):
    result = await _run(_state(closes, sl=sl))
    stop = _monitor_stop(result, closes)
    assert result.risk.position_size == pytest.approx(min(0.05, 0.001 / stop))
    assert result.risk.position_size * stop <= 0.001 + 1e-12
