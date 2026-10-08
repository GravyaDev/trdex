"""Risk node only stamps per-position SL/TP when the Analyst LLM suggested them.

Without a suggestion the decision carries None, so the position gets no
per-position values and the StopLossMonitor applies operator config and
the volatility-adaptive thresholds.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from trdex.agents.intent import Intent
from trdex.agents.risk import risk_node
from trdex.agents.state import AgentState, AnalysisResult, PortfolioContext


def _state(sl: float | None = None, tp: float | None = None) -> AgentState:
    return AgentState(
        symbol="BTC/USDT",
        run_id="r-sltp",
        analysis=AnalysisResult(
            intent=Intent.OPEN_LONG,
            confidence=0.8,
            suggested_stop_loss=sl,
            suggested_take_profit=tp,
        ),
        portfolio=PortfolioContext(equity=10_000.0),
    )


async def _run(state: AgentState) -> AgentState:
    fake_ks = AsyncMock()
    fake_ks.active = False
    with patch("trdex.risk.stop_loss.get_kill_switch", return_value=fake_ks):
        return await risk_node(state)


@pytest.mark.asyncio
async def test_no_llm_suggestion_leaves_sl_tp_unset():
    result = await _run(_state())
    assert result.risk.approved is True
    assert result.risk.stop_loss_pct is None
    assert result.risk.take_profit_pct is None


@pytest.mark.asyncio
async def test_llm_suggestion_is_clipped_into_safe_range():
    result = await _run(_state(sl=0.30, tp=0.005))
    assert result.risk.stop_loss_pct == pytest.approx(0.10)
    assert result.risk.take_profit_pct == pytest.approx(0.02)


@pytest.mark.asyncio
async def test_llm_suggestion_inside_range_passes_through():
    result = await _run(_state(sl=0.04, tp=0.09))
    assert result.risk.stop_loss_pct == pytest.approx(0.04)
    assert result.risk.take_profit_pct == pytest.approx(0.09)
