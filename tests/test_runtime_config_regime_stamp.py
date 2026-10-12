"""RuntimeConfigService stamps thresholds.regime_set_at when a regime bound changes.

The readiness gate uses the stamp to tell whether the simulation it
judges ran with the current bounds, so it must move on every effective
change (from any write path) and stay put when the dashboard re-saves
the same values.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import ClassVar

import pytest

from trdex.services.runtime_config import RuntimeConfigService


class _FakeRepo:
    writes: ClassVar[list[tuple[str, dict[str, str]]]] = []

    def __init__(self, session):
        pass

    async def put(self, category, key, value):
        _FakeRepo.writes.append((category, {key: value}))

    async def put_many(self, category, pairs):
        _FakeRepo.writes.append((category, dict(pairs)))


@pytest.fixture
def svc(monkeypatch):
    _FakeRepo.writes = []
    monkeypatch.setattr("trdex.storage.runtime_config_repo.RuntimeConfigRepository", _FakeRepo)

    @asynccontextmanager
    async def factory():
        yield object()

    s = RuntimeConfigService(factory)
    s._cache = {"thresholds": {"regime_cv_min": "0.002", "regime_cv_max": "0.045"}}
    return s


@pytest.mark.asyncio
async def test_changing_a_bound_stamps_the_change_in_the_same_write(svc):
    await svc.put_category("thresholds", {"regime_cv_max": "0.05", "sl_position_pct": "0.02"})
    category, pairs = _FakeRepo.writes[-1]
    assert category == "thresholds"
    stamp = datetime.fromisoformat(pairs["regime_set_at"])
    assert stamp.tzinfo is not None
    assert svc.get("thresholds", "regime_set_at") == pairs["regime_set_at"]


@pytest.mark.asyncio
async def test_resaving_the_same_values_does_not_move_the_stamp(svc):
    await svc.put_category(
        "thresholds",
        {"regime_cv_min": "0.0020", "regime_cv_max": "0.045", "sl_position_pct": "0.03"},
    )
    assert "regime_set_at" not in _FakeRepo.writes[-1][1]
    assert svc.get("thresholds", "regime_set_at") == ""


@pytest.mark.asyncio
async def test_single_key_put_also_stamps(svc):
    await svc.put("thresholds", "regime_cv_min", "0.001")
    assert "regime_set_at" in _FakeRepo.writes[-1][1]
    assert svc.get("thresholds", "regime_cv_min") == "0.001"


@pytest.mark.asyncio
async def test_first_time_set_stamps_and_other_categories_do_not(svc):
    svc._cache = {}
    await svc.put_category("scheduler", {"regime_cv_min": "0.01"})
    assert "regime_set_at" not in _FakeRepo.writes[-1][1]
    await svc.put_category("thresholds", {"regime_cv_min": "0.002", "regime_cv_max": "0.04"})
    assert "regime_set_at" in _FakeRepo.writes[-1][1]


@pytest.mark.asyncio
async def test_zero_is_unset_like_the_risk_node_reads_it(svc):
    svc._cache = {"thresholds": {}}
    await svc.put_category("thresholds", {"regime_cv_min": "0"})
    assert "regime_set_at" not in _FakeRepo.writes[-1][1]


# ── CLIs load only what readiness needs ───────────────────────────────────


@pytest.mark.asyncio
async def test_load_restricted_to_thresholds_never_touches_credentials(svc, monkeypatch):
    async def get_all(self):
        return {"thresholds": {"regime_cv_min": "0.002"}, "credentials": {"k": "ciphertext"}}

    def boom(_v):
        raise AssertionError("credentials must not be decrypted")

    monkeypatch.setattr(_FakeRepo, "get_all", get_all, raising=False)
    monkeypatch.setattr("trdex.services.credentials_crypto.decrypt", boom)
    await svc.load(categories={"thresholds"})
    assert svc.get_all_categories() == {"thresholds": {"regime_cv_min": "0.002"}}
