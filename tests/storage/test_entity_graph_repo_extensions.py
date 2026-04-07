"""Unit tests for Tier 5 entity graph extensions (bundle/time_window/invalidate)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from trdex.memory.predicates import (
    PRED_LAST_SIGNAL,
    PRED_VOLATILITY_REGIME,
    SUBJECT_SYMBOL,
    is_known_predicate,
    is_known_subject,
)
from trdex.storage.entity_graph_models import EntityGraphRecord
from trdex.storage.entity_graph_repo import EntityGraphRepository


def _make_fact(
    predicate: str,
    *,
    object_value: dict | None = None,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> EntityGraphRecord:
    r = EntityGraphRecord()
    r.id = 1
    r.subject_type = SUBJECT_SYMBOL
    r.subject_id = "BTC/USDT"
    r.predicate = predicate
    r.object_value = object_value or {"value": 1}
    r.object_id = None
    r.confidence = 1.0
    r.source = "agent"
    r.note = ""
    r.valid_from = valid_from or datetime(2026, 4, 7, 9, 0)
    r.valid_until = valid_until
    return r


# ---------- predicates module ------------------------------------------------


def test_predicate_constants_recognized() -> None:
    assert is_known_predicate(PRED_VOLATILITY_REGIME)
    assert is_known_predicate(PRED_LAST_SIGNAL)
    assert not is_known_predicate("unknown_predicate")


def test_subject_constants_recognized() -> None:
    assert is_known_subject(SUBJECT_SYMBOL)
    assert not is_known_subject("alien")


# ---------- bundle() --------------------------------------------------------


async def test_bundle_returns_predicate_to_value_mapping() -> None:
    session = AsyncMock()
    facts = [
        _make_fact(PRED_VOLATILITY_REGIME, object_value={"regime": "high", "cv": 0.05}),
        _make_fact(PRED_LAST_SIGNAL, object_value={"value": "BUY", "confidence": 0.7}),
    ]
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = facts
    session.execute.return_value = result_mock

    repo = EntityGraphRepository(session)
    bundle = await repo.bundle(SUBJECT_SYMBOL, "BTC/USDT")

    assert bundle == {
        PRED_VOLATILITY_REGIME: {"regime": "high", "cv": 0.05},
        PRED_LAST_SIGNAL: {"value": "BUY", "confidence": 0.7},
    }


async def test_bundle_keeps_first_when_predicate_duplicated() -> None:
    session = AsyncMock()
    facts = [
        _make_fact(PRED_VOLATILITY_REGIME, object_value={"regime": "high"}),
        _make_fact(PRED_VOLATILITY_REGIME, object_value={"regime": "low"}),
    ]
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = facts
    session.execute.return_value = result_mock

    repo = EntityGraphRepository(session)
    bundle = await repo.bundle(SUBJECT_SYMBOL, "BTC/USDT")
    # get_active orders newest first; bundle keeps the first occurrence.
    assert bundle[PRED_VOLATILITY_REGIME] == {"regime": "high"}


async def test_bundle_empty_when_no_facts() -> None:
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    session.execute.return_value = result_mock

    repo = EntityGraphRepository(session)
    assert await repo.bundle(SUBJECT_SYMBOL, "ETH/USDT") == {}


# ---------- time_window() ---------------------------------------------------


async def test_time_window_returns_overlapping_facts() -> None:
    session = AsyncMock()
    facts = [
        _make_fact(
            PRED_VOLATILITY_REGIME,
            valid_from=datetime(2026, 4, 1),
            valid_until=datetime(2026, 4, 5),
        ),
        _make_fact(
            PRED_VOLATILITY_REGIME,
            valid_from=datetime(2026, 4, 5),
            valid_until=None,
        ),
    ]
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = facts
    session.execute.return_value = result_mock

    repo = EntityGraphRepository(session)
    out = await repo.time_window(
        SUBJECT_SYMBOL,
        "BTC/USDT",
        PRED_VOLATILITY_REGIME,
        since=datetime(2026, 4, 3),
        until=datetime(2026, 4, 7),
    )
    assert len(out) == 2
    session.execute.assert_called_once()


async def test_time_window_rejects_inverted_range() -> None:
    session = AsyncMock()
    repo = EntityGraphRepository(session)
    with pytest.raises(ValueError):
        await repo.time_window(
            SUBJECT_SYMBOL,
            "BTC/USDT",
            PRED_VOLATILITY_REGIME,
            since=datetime(2026, 4, 7),
            until=datetime(2026, 4, 1),
        )


async def test_time_window_defaults_until_to_now() -> None:
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    session.execute.return_value = result_mock

    repo = EntityGraphRepository(session)
    out = await repo.time_window(
        SUBJECT_SYMBOL,
        "BTC/USDT",
        PRED_VOLATILITY_REGIME,
        since=datetime.now(tz=timezone.utc).replace(tzinfo=None) - timedelta(days=7),
    )
    assert out == []
    session.execute.assert_called_once()


# ---------- invalidate() ----------------------------------------------------


async def test_invalidate_returns_rowcount() -> None:
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.rowcount = 1
    session.execute.return_value = result_mock

    repo = EntityGraphRepository(session)
    out = await repo.invalidate(SUBJECT_SYMBOL, "BTC/USDT", PRED_LAST_SIGNAL)

    assert out == 1
    session.commit.assert_called_once()


async def test_invalidate_returns_zero_when_nothing_active() -> None:
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.rowcount = 0
    session.execute.return_value = result_mock

    repo = EntityGraphRepository(session)
    out = await repo.invalidate(SUBJECT_SYMBOL, "BTC/USDT", PRED_LAST_SIGNAL)
    assert out == 0
