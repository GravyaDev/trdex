"""FastAPI application factory."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI

from trdex import __version__
from trdex.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="trdex",
        version=__version__,
        description="Trading automation platform — crypto, FX, multi-asset",
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/status")
    async def status() -> dict[str, object]:
        return {
            "mode": settings.mode.value,
            "version": __version__,
            "timestamp": datetime.now(UTC).isoformat(),
            "feeds": {},  # Populated when feeds are registered
            "strategies": {},  # Populated when strategies are loaded
        }

    return app
