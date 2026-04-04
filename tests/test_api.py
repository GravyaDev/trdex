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
