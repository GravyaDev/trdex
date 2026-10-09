"""LLM budget accounting.

Regression: ``with_structured_output(schema)`` returns the bare Pydantic
model, so token usage was never available and every call cost $0 — the
daily budget could never be reached. The chain now uses
``include_raw=True`` and the caller reads ``usage_metadata``; when usage is
missing it charges a conservative estimate instead of zero.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import trdex.agents.llm_caller as lc
from trdex.agents.structured_output import AnalystOutput

HAIKU = "claude-haiku-4-5-20251001"  # $0.80 / $4.00 per 1M tokens


def _cfg(max_tokens: int = 1000):
    return SimpleNamespace(
        llm_enabled=True, provider="anthropic", model_id=HAIKU,
        temperature=0.3, max_tokens=max_tokens, top_p=1.0, base_url="",
    )


def _parsed():
    return AnalystOutput(signal="BUY", confidence=0.7, reasoning="x")


class _Chain:
    def __init__(self, result):
        self._result = result

    async def ainvoke(self, messages):
        return self._result


def _raw_result(input_tokens=1000, output_tokens=200, parsed=None, error=None):
    raw = AIMessage(content="", usage_metadata={
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    })
    return {"raw": raw, "parsed": parsed if parsed is not None or error else _parsed(),
            "parsing_error": error}


MSGS = [SystemMessage(content="s" * 400), HumanMessage(content="h" * 3600)]


@pytest.fixture
def caller(monkeypatch):
    def make(result, budget=20.0, max_tokens=1000):
        monkeypatch.setattr(lc, "get_structured_chain", lambda **kw: _Chain(result))
        return lc.LLMCaller(configs={"analyst": _cfg(max_tokens)}, run_id="r", daily_budget=budget)
    return make


@pytest.mark.asyncio
async def test_cost_comes_from_usage_metadata(caller):
    c = caller(_raw_result(input_tokens=1000, output_tokens=200))
    out = await c.invoke("analyst", MSGS, AnalystOutput)
    assert isinstance(out, AnalystOutput)
    assert c.daily_spend == pytest.approx((1000 * 0.80 + 200 * 4.00) / 1e6)
    rec = c.usage_records[-1]
    assert (rec.input_tokens, rec.output_tokens) == (1000, 200)


@pytest.mark.asyncio
async def test_budget_is_actually_enforced(caller):
    c = caller(_raw_result(input_tokens=100_000, output_tokens=10_000), budget=0.5)
    results = [await c.invoke("analyst", MSGS, AnalystOutput) for _ in range(10)]
    allowed = sum(r is not None for r in results)
    # $0.12 per call; the check runs before each call, so the 5th call
    # (spend $0.48) still runs and crosses the limit, then everything blocks.
    assert allowed == 5
    assert results[-1] is None
    assert c.usage_records[-1].error == "budget_exhausted"


@pytest.mark.asyncio
async def test_missing_usage_is_charged_conservatively_not_as_zero(caller):
    c = caller(_parsed(), max_tokens=1000)   # provider gave no usage at all
    await c.invoke("analyst", MSGS, AnalystOutput)
    # input ~ 4000 chars / 4 = 1000 tokens; output charged at max_tokens.
    assert c.daily_spend == pytest.approx((1000 * 0.80 + 1000 * 4.00) / 1e6)
    assert c.daily_spend > 0


@pytest.mark.asyncio
async def test_parse_error_falls_back_but_still_charges_the_tokens(caller):
    c = caller(_raw_result(parsed=None, error=ValueError("bad json")))
    out = await c.invoke("analyst", MSGS, AnalystOutput)
    assert out is None
    assert c.daily_spend > 0
    rec = c.usage_records[-1]
    assert rec.fallback_used is True
    assert "parse" in (rec.error or "")


@pytest.mark.asyncio
async def test_daily_spend_resets_on_a_new_utc_day(caller, monkeypatch):
    c = caller(_raw_result(input_tokens=100_000, output_tokens=10_000), budget=0.1)
    monkeypatch.setattr(lc, "_utc_day", lambda: "2026-10-07")
    assert await c.invoke("analyst", MSGS, AnalystOutput) is not None
    assert await c.invoke("analyst", MSGS, AnalystOutput) is None      # over budget
    monkeypatch.setattr(lc, "_utc_day", lambda: "2026-10-08")
    assert await c.invoke("analyst", MSGS, AnalystOutput) is not None  # new day


def test_for_run_isolates_records_but_shares_spend(caller):
    parent = caller(_raw_result())
    a, b = parent.for_run("run-a"), parent.for_run("run-b")
    a.usage_records.append("x")  # type: ignore[arg-type]
    assert b.usage_records == [] and parent.usage_records == []
    assert (a.run_id, b.run_id) == ("run-a", "run-b")
    a._spend.add(1.0)
    assert b.daily_spend == parent.daily_spend == 1.0


def test_structured_chain_requests_raw_output(monkeypatch):
    import trdex.agents.llm_provider as lp

    llm = MagicMock()
    monkeypatch.setattr(lp, "get_chat_model", lambda *a, **kw: llm)
    lp.get_structured_chain("anthropic", HAIKU, AnalystOutput)
    llm.with_structured_output.assert_called_once_with(AnalystOutput, include_raw=True)


@pytest.mark.asyncio
async def test_usage_persistence_failure_rolls_back_the_session():
    """A failed usage insert must not leave the shared session unusable for
    the fill that is persisted with it."""
    from trdex.agents.runner import AgentRunner

    session = MagicMock()
    session.commit = AsyncMock(side_effect=RuntimeError("insert failed"))
    session.rollback = AsyncMock()
    runner = AgentRunner.__new__(AgentRunner)
    runner._session = session
    state = SimpleNamespace(run_id="00000000-0000-0000-0000-000000000001", llm_caller=SimpleNamespace(
        usage_records=[lc.LLMUsageRecord(run_id="ignored", agent_name="analyst",
                                         provider="anthropic", model_id=HAIKU)],
    ))

    await runner._persist_llm_usage(state)

    session.rollback.assert_awaited_once()
    row = session.add.call_args.args[0]
    assert row.run_id == state.run_id   # rows carry the cycle's real run_id
