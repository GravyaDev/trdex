"""Unit tests for the Tier 3 nominations writer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from trdex.memory.nominations import (
    PENDING_HEADER,
    list_pending,
    nominate,
)


def _path(tmp_path: Path) -> Path:
    return tmp_path / "knowledge-nominations.md"


def test_creates_file_when_missing_and_writes_block(tmp_path: Path) -> None:
    target = _path(tmp_path)
    nom = nominate(
        agent="analyst",
        kind="heuristic_revision",
        summary="RSI threshold 30 too aggressive on high-vol regimes",
        evidence="12 of last 20 oversold signals lost money",
        proposed_rule="raise buy threshold to 25 when cv>0.04",
        path=target,
        now=datetime(2026, 4, 7, 9, 30, tzinfo=timezone.utc),
    )

    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert PENDING_HEADER in text
    assert nom.id.startswith("NOM-2026-04-07-")
    assert nom.id in text
    assert "RSI threshold 30" in text
    assert "raise buy threshold to 25" in text


def test_dedup_by_content_hash(tmp_path: Path) -> None:
    target = _path(tmp_path)
    base = dict(
        agent="risk",
        kind="gate_tuning",
        summary="drawdown gate triggers too late on flash crashes",
        path=target,
    )
    first = nominate(**base)
    second = nominate(**base)

    assert first.id == second.id  # same hash
    text = target.read_text(encoding="utf-8")
    assert text.count(first.id) == 1  # written exactly once


def test_distinct_summaries_produce_distinct_entries(tmp_path: Path) -> None:
    target = _path(tmp_path)
    a = nominate(agent="analyst", kind="k", summary="A", path=target)
    b = nominate(agent="analyst", kind="k", summary="B", path=target)
    assert a.id != b.id

    pending = list_pending(target)
    assert a.id in pending
    assert b.id in pending


def test_extra_dict_renders_as_yaml_block(tmp_path: Path) -> None:
    target = _path(tmp_path)
    nominate(
        agent="executor",
        kind="slippage_observation",
        summary="BTC/USDT slippage > 5bps on 1h ATR > 200",
        extra={"sample_size": 30, "avg_bps": 6.4},
        path=target,
    )
    text = target.read_text(encoding="utf-8")
    assert "```yaml" in text
    assert "extra:" in text
    assert "sample_size: 30" in text
    assert "avg_bps: 6.4" in text


def test_appends_pending_header_if_missing(tmp_path: Path) -> None:
    target = _path(tmp_path)
    target.write_text("# Knowledge Nominations\n\nFreeform notes.\n", encoding="utf-8")
    nominate(agent="scout", kind="source_quality", summary="x", path=target)
    text = target.read_text(encoding="utf-8")
    assert PENDING_HEADER in text


def test_validation_raises_on_empty_fields(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        nominate(agent="", kind="k", summary="s", path=_path(tmp_path))
    with pytest.raises(ValueError):
        nominate(agent="a", kind="", summary="s", path=_path(tmp_path))
    with pytest.raises(ValueError):
        nominate(agent="a", kind="k", summary="", path=_path(tmp_path))


def test_list_pending_on_missing_file(tmp_path: Path) -> None:
    assert list_pending(_path(tmp_path)) == []
