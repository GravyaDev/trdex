"""Unit tests for MemoryContextLoader (Phase 3 aggregator)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from trdex.memory.context import MemoryContext, MemoryContextLoader
from trdex.memory.kb_loader import KBLoader
from trdex.memory.predicates import PRED_LAST_SIGNAL, PRED_VOLATILITY_REGIME
from trdex.memory.trade_narratives import TradeNarrativeHit, TradeNarrativeService
from trdex.storage.agent_memory_models import AgentMemoryRecord
from trdex.storage.agent_run_models import AgentRunRecord
from trdex.storage.entity_graph_models import EntityGraphRecord


# ---------- helpers ---------------------------------------------------------


def _kb(tmp_path: Path) -> KBLoader:
    (tmp_path / "analyst.md").write_text(
        """---
agent: analyst
---

### `HARD-X-1` — One
**Tags**: `mindset`

```yaml
v: 1
```

### `PARAM-X-1` — Two

```yaml
v: 2
```
""",
        encoding="utf-8",
    )
    return KBLoader.from_directory(tmp_path)


def _fake_session_factory(execute_results: list[MagicMock]):
    """Return a session_factory that yields a session whose execute() pops
    one MagicMock per call. The MemoryContextLoader does 3 separate
    `async with factory()` blocks (Tier 2, Tier 5, Tier 6), each running
    one execute() call, so we just queue them in order.
    """
    queue = list(execute_results)

    @asynccontextmanager
    async def _factory():
        session = AsyncMock()

        async def _execute(*_args, **_kwargs):
            return queue.pop(0)

        session.execute.side_effect = _execute
        yield session

    return _factory


def _agent_memory_row(kind: str = "k", key: str = "BTC/USDT") -> AgentMemoryRecord:
    r = AgentMemoryRecord()
    r.id = 1
    r.agent = "analyst"
    r.kind = kind
    r.key = key
    r.value = {"v": 1}
    r.confidence = 1.0
    r.source = "agent"
    r.note = ""
    return r


def _entity_fact(predicate: str, value: dict) -> EntityGraphRecord:
    r = EntityGraphRecord()
    r.id = 1
    r.subject_type = "symbol"
    r.subject_id = "BTC/USDT"
    r.predicate = predicate
    r.object_value = value
    r.object_id = None
    r.confidence = 1.0
    r.source = "agent"
    r.note = ""
    return r


def _run() -> AgentRunRecord:
    r = AgentRunRecord()
    r.id = 1
    r.run_id = "00000000-0000-0000-0000-000000000000"
    r.symbol = "BTC/USDT"
    from datetime import datetime

    r.ran_at = datetime(2026, 4, 7, 9, 0, 0)
    r.signal = "BUY"
    r.confidence = 0.6
    r.risk_approved = True
    r.order_status = "filled"
    r.reasoning = ""
    r.indicators = {}
    r.risk_reason = ""
    r.position_size = 0
    r.stop_loss_pct = 0
    r.take_profit_pct = 0
    r.filled_price = None
    r.filled_qty = None
    r.order_message = ""
    r.error = None
    return r


def _scalars_result(rows: list) -> MagicMock:
    m = MagicMock()
    m.scalars.return_value.all.return_value = rows
    return m


# ---------- MemoryContext.is_empty / to_prompt_text -------------------------


def test_memory_context_is_empty_by_default() -> None:
    ctx = MemoryContext(agent="analyst", symbol="BTC/USDT")
    assert ctx.is_empty()
    text = ctx.to_prompt_text()
    assert "BTC/USDT" in text
    # No section headers when empty
    assert "Knowledge base" not in text


def test_to_prompt_text_renders_each_section(tmp_path: Path) -> None:
    from trdex.memory.kb_loader import KBBlock
    from trdex.storage.agent_run_repo import RunNarrative

    ctx = MemoryContext(
        agent="analyst",
        symbol="BTC/USDT",
        kb_blocks=[
            KBBlock(
                id="HARD-X-1",
                type="HARD",
                title="One",
                tags=("mindset",),
                body="",
                body_format="",
                agent="analyst",
                source_file="",
            )
        ],
        operational={"k": [{"key": "BTC/USDT", "value": {"v": 1}, "updated_at": None}]},
        entity_facts={PRED_VOLATILITY_REGIME: {"regime": "high"}},
        narrative=RunNarrative(
            symbol="BTC/USDT",
            count=1,
            text="Recent 1 runs for BTC/USDT — signals: BUY:1",
            last_ran_at=None,
            signals={"BUY": 1},
            approval_rate=1.0,
            fill_rate=1.0,
        ),
    )
    text = ctx.to_prompt_text()
    assert "Knowledge base" in text
    assert "HARD-X-1" in text
    assert "Operational memory" in text
    assert "Entity facts" in text
    assert PRED_VOLATILITY_REGIME in text
    assert "Recent runs" in text


def test_to_prompt_text_truncates_kb_blocks() -> None:
    from trdex.memory.kb_loader import KBBlock

    blocks = [
        KBBlock(
            id=f"HARD-X-{i}",
            type="HARD",
            title=f"t{i}",
            tags=(),
            body="",
            body_format="",
            agent="analyst",
            source_file="",
        )
        for i in range(12)
    ]
    ctx = MemoryContext(agent="analyst", symbol="BTC/USDT", kb_blocks=blocks)
    text = ctx.to_prompt_text(max_kb_blocks=5)
    # Only 5 ids should appear; the remainder is summarised.
    assert "HARD-X-4" in text
    assert "HARD-X-5" not in text
    assert "(+7 more blocks)" in text


# ---------- MemoryContextLoader.build --------------------------------------


async def test_build_with_no_session_factory_returns_only_kb(tmp_path: Path) -> None:
    loader = MemoryContextLoader(_kb(tmp_path), None)
    ctx = await loader.build("analyst", "BTC/USDT")

    assert ctx.agent == "analyst"
    assert ctx.symbol == "BTC/USDT"
    assert {b.id for b in ctx.kb_blocks} == {"HARD-X-1", "PARAM-X-1"}
    assert ctx.operational == {}
    assert ctx.entity_facts == {}
    assert ctx.narrative is None


async def test_build_with_no_kb_returns_only_db_tiers() -> None:
    factory = _fake_session_factory(
        [
            _scalars_result([_agent_memory_row(kind="indicator_observation")]),  # tier 2
            _scalars_result([_entity_fact(PRED_LAST_SIGNAL, {"value": "BUY"})]),  # tier 5
            _scalars_result([_run()]),  # tier 6
        ]
    )
    loader = MemoryContextLoader(None, factory)
    ctx = await loader.build("analyst", "BTC/USDT")

    assert ctx.kb_blocks == []
    assert "indicator_observation" in ctx.operational
    assert ctx.entity_facts == {PRED_LAST_SIGNAL: {"value": "BUY"}}
    assert ctx.narrative is not None
    assert ctx.narrative.count == 1


async def test_build_full_stack_aggregates_all_tiers(tmp_path: Path) -> None:
    factory = _fake_session_factory(
        [
            _scalars_result([_agent_memory_row(kind="rejection_stat")]),
            _scalars_result(
                [
                    _entity_fact(PRED_VOLATILITY_REGIME, {"regime": "high", "cv": 0.05}),
                    _entity_fact(PRED_LAST_SIGNAL, {"value": "BUY"}),
                ]
            ),
            _scalars_result([_run(), _run()]),
        ]
    )
    loader = MemoryContextLoader(_kb(tmp_path), factory)
    ctx = await loader.build("analyst", "BTC/USDT")

    assert len(ctx.kb_blocks) == 2
    assert "rejection_stat" in ctx.operational
    assert ctx.entity_facts[PRED_VOLATILITY_REGIME] == {"regime": "high", "cv": 0.05}
    assert ctx.narrative.count == 2
    text = ctx.to_prompt_text()
    assert "HARD-X-1" in text
    assert PRED_VOLATILITY_REGIME in text


async def test_build_filters_operational_by_kinds() -> None:
    factory = _fake_session_factory(
        [
            _scalars_result([_agent_memory_row(kind="indicator_observation")]),
            _scalars_result([]),  # tier 5 empty
            _scalars_result([]),  # tier 6 empty
        ]
    )
    loader = MemoryContextLoader(None, factory)
    ctx = await loader.build(
        "analyst", "BTC/USDT", operational_kinds=["indicator_observation"]
    )
    assert "indicator_observation" in ctx.operational


async def test_build_includes_tier4_when_service_provided(tmp_path: Path) -> None:
    factory = _fake_session_factory(
        [
            _scalars_result([]),  # tier 2 empty
            _scalars_result(
                [_entity_fact(PRED_VOLATILITY_REGIME, {"regime": "high"})]
            ),  # tier 5
            _scalars_result([]),  # tier 6 empty
        ]
    )
    narrative_svc = AsyncMock(spec=TradeNarrativeService)
    narrative_svc.search.return_value = [
        TradeNarrativeHit(
            doc_id="x",
            score=0.91,
            text="BTC/USDT BUY WIN +2.4%",
            symbol="BTC/USDT",
            signal="BUY",
            outcome="WIN",
            pnl_pct=2.4,
            payload={},
        )
    ]
    loader = MemoryContextLoader(
        _kb(tmp_path), factory, trade_narrative_service=narrative_svc
    )
    ctx = await loader.build("analyst", "BTC/USDT")

    assert len(ctx.similar_trades) == 1
    assert ctx.similar_trades[0].doc_id == "x"
    # Default similarity query should include the symbol and the entity fact
    narrative_svc.search.assert_awaited_once()
    args, kwargs = narrative_svc.search.call_args
    assert "BTC/USDT" in args[0]
    assert kwargs["symbol"] == "BTC/USDT"
    text = ctx.to_prompt_text()
    assert "Similar past trades" in text


async def test_build_respects_explicit_similarity_query() -> None:
    factory = _fake_session_factory(
        [_scalars_result([]), _scalars_result([]), _scalars_result([])]
    )
    narrative_svc = AsyncMock(spec=TradeNarrativeService)
    narrative_svc.search.return_value = []
    loader = MemoryContextLoader(None, factory, trade_narrative_service=narrative_svc)
    await loader.build(
        "analyst",
        "BTC/USDT",
        similarity_query="custom oversold bounce",
        similar_trades_limit=3,
    )
    args, kwargs = narrative_svc.search.call_args
    assert args[0] == "custom oversold bounce"
    assert kwargs["limit"] == 3


async def test_build_survives_tier4_failure(tmp_path: Path) -> None:
    factory = _fake_session_factory(
        [_scalars_result([]), _scalars_result([]), _scalars_result([])]
    )
    narrative_svc = AsyncMock(spec=TradeNarrativeService)
    narrative_svc.search.side_effect = RuntimeError("qdrant unreachable")
    loader = MemoryContextLoader(
        _kb(tmp_path), factory, trade_narrative_service=narrative_svc
    )
    ctx = await loader.build("analyst", "BTC/USDT")
    # Other tiers must remain populated
    assert len(ctx.kb_blocks) == 2
    assert ctx.similar_trades == []


async def test_build_survives_tier_failure(tmp_path: Path) -> None:
    """If one tier raises, the others must still populate."""

    @asynccontextmanager
    async def boom_factory():
        session = AsyncMock()
        session.execute.side_effect = RuntimeError("db down")
        yield session

    loader = MemoryContextLoader(_kb(tmp_path), boom_factory)
    ctx = await loader.build("analyst", "BTC/USDT")

    # Tier 1 (KB) still populated
    assert len(ctx.kb_blocks) == 2
    # Tiers 2/5/6 silently empty after exception
    assert ctx.operational == {}
    assert ctx.entity_facts == {}
    assert ctx.narrative is None or ctx.narrative.count == 0
