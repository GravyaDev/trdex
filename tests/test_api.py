"""Tests for FastAPI endpoints."""

from httpx import ASGITransport, AsyncClient

from trdex.api.app import create_app


async def test_health_endpoint() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


async def test_status_endpoint_no_auth() -> None:
    """Status endpoint accessible without auth in dev mode (empty API key)."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/status")

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "simulation"
    assert "timestamp" in data
    assert data["feed_health"] == []  # no feed manager without the lifespan
    assert data["kill_switch"]["active"] in (True, False)
    assert "calendar" in data["macro_gate"] and "blocking_now" in data["macro_gate"]


async def test_status_shows_a_broken_macro_config_as_blocking(monkeypatch) -> None:
    """The gates fail closed on bad settings; the status bar must not say "open"."""

    class BadCfg:
        def get(self, category, key, default=""):
            return "inf" if key == "macro_gate_before_min" else default

    monkeypatch.setattr("trdex.services.runtime_config.get_config_service", lambda: BadCfg())
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        data = (await client.get("/v1/status")).json()
    assert data["macro_gate"]["blocking_now"].startswith("macro gate error (fail-closed)")
