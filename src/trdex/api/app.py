"""FastAPI application factory."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader

from trdex import __version__
from trdex.config import settings

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Security(API_KEY_HEADER)) -> str:
    """Verify API key for authenticated endpoints.

    If TRDEX_API_KEY is not set, authentication is disabled (dev mode).
    """
    if not settings.api_key:
        return "dev-mode"
    if not api_key or not secrets.compare_digest(api_key, settings.api_key):
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return api_key


def create_app() -> FastAPI:
    app = FastAPI(
        title="trdex",
        version=__version__,
        description="Trading automation platform — AI-driven crypto, FX, multi-asset",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origins] if settings.cors_origins else [],
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key"],
    )

    # --- Public endpoints (no auth) ---

    @app.get("/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    # --- Authenticated endpoints ---

    @app.get("/v1/status")
    async def status(_key: str = Depends(verify_api_key)) -> dict[str, object]:
        return {
            "mode": settings.mode.value,
            "version": __version__,
            "timestamp": datetime.now(UTC).isoformat(),
            "feeds": {},
            "strategies": {},
        }

    return app
