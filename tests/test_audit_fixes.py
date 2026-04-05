"""Tests verifying all P0 and P1 audit fixes.

Covers:
  P0 -- Auth enforcement on risk/agent/context endpoints
  P0 -- Portfolio session management (no leak)
  P1 -- KillSwitch asyncio.Lock safety
  P1 -- TelegramMonitor asyncio.Queue stream
  P1 -- ORM timestamp defaults
  P1 -- Unified DeclarativeBase
  P1 -- datetime.utcnow() replaced
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

import trdex.api.app as _app_module
from trdex.api.app import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# P0: Auth enforcement
# ---------------------------------------------------------------------------

class TestAuthEnforcement:
    """All new endpoints must return 403 when an API key is configured but absent."""

    PROTECTED_ROUTES = [
        ("GET",    "/v1/risk/status"),
        ("GET",    "/v1/risk/events"),
        ("POST",   "/v1/risk/check"),
        ("POST",   "/v1/risk/kill-switch/activate"),
        ("POST",   "/v1/risk/kill-switch/reset"),
        ("POST",   "/v1/agent/run"),
        ("GET",    "/v1/agent/history"),
        ("GET",    "/v1/context/status"),
        ("POST",   "/v1/context/run"),
        ("POST",   "/v1/context/symbols"),
        ("DELETE", "/v1/context/symbols/BTC%2FUSDT"),
    ]

    @pytest.fixture(autouse=True)
    def restore_api_key(self):
        """Restore original api_key after each test."""
        original = _app_module.settings.api_key
        yield
        _app_module.settings.api_key = original  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
    async def test_returns_403_with_wrong_key(self, method: str, path: str) -> None:
        """When TRDEX_API_KEY is set, wrong key must be rejected with 403."""
        _app_module.settings.api_key = "secret-key"  # type: ignore[attr-defined]
        app = create_app()
        async with make_client(app) as client:
            req = getattr(client, method.lower())
            response = await req(path, headers={"X-API-Key": "wrong-key"})
        assert response.status_code == 403, (
            f"{method} {path} should return 403 with wrong key, got {response.status_code}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
    async def test_no_key_header_returns_403(self, method: str, path: str) -> None:
        """When TRDEX_API_KEY is set, missing key header must be rejected with 403."""
        _app_module.settings.api_key = "secret-key"  # type: ignore[attr-defined]
        app = create_app()
        async with make_client(app) as client:
            req = getattr(client, method.lower())
            response = await req(path)
        assert response.status_code == 403, (
            f"{method} {path} should return 403 with no key, got {response.status_code}"
        )

    @pytest.mark.asyncio
    async def test_dev_mode_no_key_allows_access(self) -> None:
        """When TRDEX_API_KEY is empty, all endpoints are open (dev mode)."""
        _app_module.settings.api_key = ""  # type: ignore[attr-defined]
        app = create_app()
        async with make_client(app) as client:
            response = await client.get("/v1/risk/status")
        # 200 or 503 (monitor not initialised) -- not 403
        assert response.status_code != 403

    @pytest.mark.asyncio
    async def test_correct_key_allows_access(self) -> None:
        """Correct API key must be accepted (not 403)."""
        _app_module.settings.api_key = "my-secret"  # type: ignore[attr-defined]
        app = create_app()
        async with make_client(app) as client:
            response = await client.get("/v1/risk/status", headers={"X-API-Key": "my-secret"})
        assert response.status_code != 403

    @pytest.mark.asyncio
    async def test_kill_switch_activate_requires_auth(self) -> None:
        """Kill-switch activate must be blocked without correct key."""
        _app_module.settings.api_key = "secure"  # type: ignore[attr-defined]
        app = create_app()
        async with make_client(app) as client:
            response = await client.post("/v1/risk/kill-switch/activate")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_kill_switch_reset_requires_auth(self) -> None:
        """Kill-switch reset must be blocked without correct key."""
        _app_module.settings.api_key = "secure"  # type: ignore[attr-defined]
        app = create_app()
        async with make_client(app) as client:
            response = await client.post("/v1/risk/kill-switch/reset")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_agent_run_requires_auth(self) -> None:
        _app_module.settings.api_key = "secure"  # type: ignore[attr-defined]
        app = create_app()
        async with make_client(app) as client:
            response = await client.post("/v1/agent/run")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_agent_history_requires_auth(self) -> None:
        _app_module.settings.api_key = "secure"  # type: ignore[attr-defined]
        app = create_app()
        async with make_client(app) as client:
            response = await client.get("/v1/agent/history")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_context_status_requires_auth(self) -> None:
        _app_module.settings.api_key = "secure"  # type: ignore[attr-defined]
        app = create_app()
        async with make_client(app) as client:
            response = await client.get("/v1/context/status")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_risk_status_requires_auth(self) -> None:
        _app_module.settings.api_key = "secure"  # type: ignore[attr-defined]
        app = create_app()
        async with make_client(app) as client:
            response = await client.get("/v1/risk/status")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_risk_events_requires_auth(self) -> None:
        _app_module.settings.api_key = "secure"  # type: ignore[attr-defined]
        app = create_app()
        async with make_client(app) as client:
            response = await client.get("/v1/risk/events")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_health_remains_public(self) -> None:
        """/v1/health must always be accessible without auth."""
        _app_module.settings.api_key = "secure"  # type: ignore[attr-defined]
        app = create_app()
        async with make_client(app) as client:
            response = await client.get("/v1/health")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# P0: Portfolio session management
# ---------------------------------------------------------------------------

class TestPortfolioSessionManagement:
    """Portfolio service context manager must properly close sessions."""

    @pytest.mark.asyncio
    async def test_service_context_manager_closes_session(self) -> None:
        from trdex.api.routes import portfolio as portfolio_routes

        closed = []
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(side_effect=lambda *a: closed.append(True))
        mock_factory = MagicMock(return_value=mock_ctx)

        portfolio_routes.set_service_factory(mock_factory, MagicMock())

        try:
            async with portfolio_routes._service():
                pass
        except Exception:
            pass

        assert len(closed) >= 1, "Session __aexit__ must be called (session not closed)"

        portfolio_routes._session_factory = None
        portfolio_routes._feed_manager = None

    @pytest.mark.asyncio
    async def test_service_closes_session_on_exception(self) -> None:
        from trdex.api.routes import portfolio as portfolio_routes

        closed = []
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_ctx.__aexit__ = AsyncMock(side_effect=lambda *a: closed.append(True))
        mock_factory = MagicMock(return_value=mock_ctx)

        portfolio_routes.set_service_factory(mock_factory, MagicMock())

        try:
            async with portfolio_routes._service():
                raise ValueError("boom")
        except (ValueError, Exception):
            pass

        assert len(closed) >= 1

        portfolio_routes._session_factory = None
        portfolio_routes._feed_manager = None

    @pytest.mark.asyncio
    async def test_get_service_raises_503_when_not_initialised(self) -> None:
        from trdex.api.routes import portfolio as portfolio_routes
        from fastapi import HTTPException

        orig_factory = portfolio_routes._session_factory
        orig_feed = portfolio_routes._feed_manager
        portfolio_routes._session_factory = None
        portfolio_routes._feed_manager = None

        with pytest.raises(HTTPException) as exc_info:
            async with portfolio_routes._service():
                pass

        assert exc_info.value.status_code == 503

        portfolio_routes._session_factory = orig_factory
        portfolio_routes._feed_manager = orig_feed

    def test_portfolio_routes_use_context_manager(self) -> None:
        """Source check: portfolio routes must use async with _service()."""
        import inspect
        from trdex.api.routes import portfolio as portfolio_routes
        source = inspect.getsource(portfolio_routes)
        assert "async with _service()" in source, (
            "Portfolio routes must use 'async with _service()' context manager"
        )
        assert "session = _session_factory()" not in source, (
            "Old pattern 'session = _session_factory()' must not exist"
        )


# ---------------------------------------------------------------------------
# P1: KillSwitch asyncio.Lock
# ---------------------------------------------------------------------------

class TestKillSwitchLock:
    """KillSwitch async methods must be safe under concurrent access."""

    @pytest.mark.asyncio
    async def test_activate_async_sets_active(self) -> None:
        from trdex.risk.stop_loss import KillSwitch
        ks = KillSwitch()
        await ks.activate_async("test reason")
        assert ks.active is True
        assert ks.status["reason"] == "test reason"
        assert ks.status["activated_at"] is not None

    @pytest.mark.asyncio
    async def test_reset_async_clears_state(self) -> None:
        from trdex.risk.stop_loss import KillSwitch
        ks = KillSwitch()
        await ks.activate_async("test")
        await ks.reset_async()
        assert ks.active is False
        assert ks.status["reason"] == ""
        assert ks.status["activated_at"] is None

    @pytest.mark.asyncio
    async def test_concurrent_activations_are_idempotent(self) -> None:
        """Multiple concurrent activate_async calls must not corrupt state."""
        from trdex.risk.stop_loss import KillSwitch
        ks = KillSwitch()

        await asyncio.gather(*[ks.activate_async(f"reason-{i}") for i in range(10)])

        assert ks.active is True
        assert ks.status["reason"].startswith("reason-")

    @pytest.mark.asyncio
    async def test_sync_activate_still_works(self) -> None:
        from trdex.risk.stop_loss import KillSwitch
        ks = KillSwitch()
        ks.activate("sync reason")
        assert ks.active is True

    @pytest.mark.asyncio
    async def test_activate_async_only_activates_once(self) -> None:
        """Second activate_async call must not overwrite reason."""
        from trdex.risk.stop_loss import KillSwitch
        ks = KillSwitch()
        await ks.activate_async("first")
        await ks.activate_async("second")
        assert ks.status["reason"] == "first"

    @pytest.mark.asyncio
    async def test_lock_attribute_present(self) -> None:
        from trdex.risk.stop_loss import KillSwitch
        ks = KillSwitch()
        assert hasattr(ks, "_lock")
        assert isinstance(ks._lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_get_kill_switch_singleton_is_shared(self) -> None:
        from trdex.risk.stop_loss import get_kill_switch
        ks1 = get_kill_switch()
        ks2 = get_kill_switch()
        assert ks1 is ks2

    @pytest.mark.asyncio
    async def test_reset_allows_reactivation(self) -> None:
        from trdex.risk.stop_loss import KillSwitch
        ks = KillSwitch()
        await ks.activate_async("first activation")
        await ks.reset_async()
        await ks.activate_async("second activation")
        assert ks.active is True
        assert ks.status["reason"] == "second activation"


# ---------------------------------------------------------------------------
# P1: TelegramMonitor asyncio.Queue
# ---------------------------------------------------------------------------

class TestTelegramMonitorQueue:
    """stream() must use asyncio.Queue, not list polling."""

    def test_stream_uses_asyncio_queue(self) -> None:
        import inspect
        from trdex.telegram.monitor import TelegramMonitor
        source = inspect.getsource(TelegramMonitor.stream)
        assert "asyncio.Queue" in source, "stream() must use asyncio.Queue"
        assert "queue.pop" not in source, "stream() must not use list.pop() polling"
        assert "asyncio.sleep(0.5)" not in source, "stream() must not sleep-poll"

    def test_stream_uses_wait_for(self) -> None:
        import inspect
        from trdex.telegram.monitor import TelegramMonitor
        source = inspect.getsource(TelegramMonitor.stream)
        assert "wait_for" in source, "stream() must use asyncio.wait_for for timeout"

    def test_handler_has_exception_logging(self) -> None:
        import inspect
        from trdex.telegram.monitor import TelegramMonitor
        source = inspect.getsource(TelegramMonitor.stream)
        assert "logger.exception" in source, "_handler must log exceptions"

    def test_stream_handles_timeout_without_crash(self) -> None:
        import inspect
        from trdex.telegram.monitor import TelegramMonitor
        source = inspect.getsource(TelegramMonitor.stream)
        assert "TimeoutError" in source, "stream() must catch asyncio.TimeoutError"

    @pytest.mark.asyncio
    async def test_queue_put_and_get(self) -> None:
        q: asyncio.Queue[str] = asyncio.Queue()
        await q.put("signal")
        item = await asyncio.wait_for(q.get(), timeout=1.0)
        assert item == "signal"

    @pytest.mark.asyncio
    async def test_queue_timeout_raises_timeout_error(self) -> None:
        q: asyncio.Queue[str] = asyncio.Queue()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(q.get(), timeout=0.01)


# ---------------------------------------------------------------------------
# P1: ORM timestamp defaults
# ---------------------------------------------------------------------------

class TestOrmTimestampDefaults:
    """ORM models must have defaults for required timestamp columns."""

    def test_agent_run_record_ran_at_has_default(self) -> None:
        from trdex.storage.agent_run_models import AgentRunRecord
        col = AgentRunRecord.__table__.c["ran_at"]
        assert col.default is not None, "ran_at must have a column default"

    def test_position_record_opened_at_has_default(self) -> None:
        from trdex.storage.portfolio_models import PositionRecord
        col = PositionRecord.__table__.c["opened_at"]
        assert col.default is not None, "opened_at must have a column default"

    def _invoke_default(self, col):
        """Invoke a SQLAlchemy CallableColumnDefault correctly.

        SQLAlchemy wraps the callable and may pass a context arg; we call the
        underlying function directly from the module to avoid that wrapping.
        """
        # col.default.arg is the wrapped callable. Get the real function by
        # looking it up on the module that owns the column's table.
        return col.default.arg.__wrapped__() if hasattr(col.default.arg, "__wrapped__") else col.default.arg(None)

    def test_agent_run_record_default_produces_naive_datetime(self) -> None:
        """Default must produce a naive UTC datetime (asyncpg requirement)."""
        from trdex.storage.agent_run_models import _utcnow_naive
        value = _utcnow_naive()
        assert isinstance(value, datetime)
        assert value.tzinfo is None, "ran_at default must be naive (asyncpg requires naive UTC)"

    def test_position_record_default_produces_naive_datetime(self) -> None:
        from trdex.storage.portfolio_models import _utcnow_naive
        value = _utcnow_naive()
        assert isinstance(value, datetime)
        assert value.tzinfo is None, "opened_at default must be naive (asyncpg requires naive UTC)"

    def test_agent_run_record_default_is_recent(self) -> None:
        """Default must produce a timestamp close to now."""
        from trdex.storage.agent_run_models import _utcnow_naive
        before = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        value = _utcnow_naive()
        after = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        assert before <= value <= after

    def test_position_record_default_is_recent(self) -> None:
        from trdex.storage.portfolio_models import _utcnow_naive
        before = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        value = _utcnow_naive()
        after = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        assert before <= value <= after


# ---------------------------------------------------------------------------
# P1: Unified DeclarativeBase
# ---------------------------------------------------------------------------

class TestUnifiedDeclarativeBase:
    """AgentRunRecord must use the same Base as OHLCVRecord and PositionRecord."""

    def test_agent_run_record_uses_shared_base(self) -> None:
        from trdex.storage.db import Base
        from trdex.storage.agent_run_models import AgentRunRecord
        assert issubclass(AgentRunRecord, Base), (
            "AgentRunRecord must inherit from trdex.storage.db.Base, not its own _Base"
        )

    def test_all_models_share_metadata(self) -> None:
        from trdex.storage.db import Base
        from trdex.storage.models import OHLCVRecord
        from trdex.storage.portfolio_models import PositionRecord
        from trdex.storage.agent_run_models import AgentRunRecord

        meta = Base.metadata
        assert OHLCVRecord.__table__.metadata is meta
        assert PositionRecord.__table__.metadata is meta
        assert AgentRunRecord.__table__.metadata is meta

    def test_agent_runs_table_in_shared_metadata(self) -> None:
        from trdex.storage.db import Base
        assert "agent_runs" in Base.metadata.tables, (
            "agent_runs table must appear in the shared metadata"
        )

    def test_no_private_base_in_agent_run_models(self) -> None:
        import trdex.storage.agent_run_models as mod
        assert not hasattr(mod, "_Base"), (
            "agent_run_models.py must not define its own _Base -- use trdex.storage.db.Base"
        )


# ---------------------------------------------------------------------------
# P1: datetime.utcnow() replaced
# ---------------------------------------------------------------------------

class TestDatetimeUtcnow:
    """No deprecated datetime.utcnow() calls in state.py."""

    def test_market_snapshot_timestamp_default_is_timezone_aware(self) -> None:
        from trdex.agents.state import MarketSnapshot
        snapshot = MarketSnapshot(symbol="BTC/USDT", price=50000.0)
        assert snapshot.timestamp.tzinfo is not None, (
            "MarketSnapshot.timestamp default must be timezone-aware"
        )

    def test_market_snapshot_timestamp_is_utc(self) -> None:
        from trdex.agents.state import MarketSnapshot
        snapshot = MarketSnapshot(symbol="BTC/USDT", price=50000.0)
        utc_offset = snapshot.timestamp.utcoffset()
        assert utc_offset is not None
        assert utc_offset.total_seconds() == 0.0

    def test_state_py_does_not_use_utcnow(self) -> None:
        import inspect
        from trdex.agents import state
        source = inspect.getsource(state)
        assert "datetime.utcnow" not in source, (
            "agents/state.py must not use deprecated datetime.utcnow()"
        )

    def test_state_py_uses_timezone(self) -> None:
        import inspect
        from trdex.agents import state
        source = inspect.getsource(state)
        assert "timezone" in source, "agents/state.py should use timezone.utc"


# ---------------------------------------------------------------------------
# P1: docker-compose healthcheck
# ---------------------------------------------------------------------------

class TestDockerComposeHealthcheck:
    """docker-compose.yaml must have a healthcheck for the app service."""

    @pytest.fixture
    def compose(self):
        import yaml
        path = "c:/Users/Daniele/Antigravity/trdex/docker-compose.yaml"
        with open(path) as f:
            return yaml.safe_load(f)

    def test_app_service_has_healthcheck(self, compose) -> None:
        assert "healthcheck" in compose["services"]["app"], (
            "app service must have a healthcheck"
        )

    def test_app_healthcheck_tests_health_endpoint(self, compose) -> None:
        hc = compose["services"]["app"]["healthcheck"]
        test_cmd = " ".join(hc["test"]) if isinstance(hc["test"], list) else hc["test"]
        assert "/v1/health" in test_cmd, "healthcheck must target /v1/health"

    def test_app_healthcheck_has_start_period(self, compose) -> None:
        hc = compose["services"]["app"]["healthcheck"]
        assert "start_period" in hc, "app healthcheck should have start_period for startup grace"

    def test_all_services_have_healthchecks(self, compose) -> None:
        for svc_name in ("db", "redis", "qdrant", "app"):
            assert "healthcheck" in compose["services"][svc_name], (
                f"Service '{svc_name}' must have a healthcheck"
            )


# ---------------------------------------------------------------------------
# P0: .env.example completeness
# ---------------------------------------------------------------------------

class TestEnvExample:
    """All required env vars must be documented in .env.example."""

    REQUIRED_VARS = [
        "TRDEX_AGENT_SCHEDULER_ENABLED",
        "TRDEX_AGENT_SCHEDULER_INTERVAL",
        "TRDEX_AGENT_SCHEDULER_SYMBOLS",
        "TRDEX_ALPHAVANTAGE_API_KEY",
        "TRDEX_CRYPTOCOMPARE_API_KEY",
        "TRDEX_FREECRYPTOAPI_KEY",
        "TRDEX_GATE_MIN_DAYS",
        "TRDEX_GATE_MIN_SHARPE",
        "TRDEX_GATE_MAX_DRAWDOWN",
        "TRDEX_GATE_MIN_WIN_RATE",
        "TRDEX_INGESTION_INTERVAL",
        "TRDEX_INGESTION_SYMBOLS",
        "TRDEX_MAX_POSITION_PCT",
        "TRDEX_SL_CHECK_INTERVAL",
        "TRDEX_SL_POSITION_PCT",
        "TRDEX_SL_TAKE_PROFIT_PCT",
        "TRDEX_SL_DAILY_DRAWDOWN_PCT",
        "TRDEX_STOCKDATA_API_KEY",
        "DATABASE_URL",
        "REDIS_URL",
    ]

    @pytest.fixture
    def env_content(self):
        with open("c:/Users/Daniele/Antigravity/trdex/.env.example") as f:
            return f.read()

    @pytest.mark.parametrize("var", REQUIRED_VARS)
    def test_var_documented_in_env_example(self, var: str, env_content: str) -> None:
        assert var in env_content, f"{var} must be documented in .env.example"

    def test_db_url_uses_docker_service_name(self, env_content: str) -> None:
        for line in env_content.splitlines():
            if line.startswith("DATABASE_URL="):
                assert "db:5432" in line, (
                    f"DATABASE_URL should use db:5432 for Docker networking, got: {line}"
                )
                return
        pytest.fail("DATABASE_URL not found in .env.example")

    def test_redis_url_uses_docker_service_name(self, env_content: str) -> None:
        for line in env_content.splitlines():
            if line.startswith("REDIS_URL="):
                assert "redis:" in line, (
                    f"REDIS_URL should use redis: service name for Docker, got: {line}"
                )
                return
        pytest.fail("REDIS_URL not found in .env.example")

    def test_env_example_documents_agent_scheduler(self, env_content: str) -> None:
        assert "TRDEX_AGENT_SCHEDULER_ENABLED=false" in env_content

    def test_env_example_documents_sl_thresholds(self, env_content: str) -> None:
        assert "TRDEX_SL_POSITION_PCT" in env_content
        assert "TRDEX_SL_DAILY_DRAWDOWN_PCT" in env_content
