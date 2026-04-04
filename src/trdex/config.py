"""Application configuration via environment variables."""

from __future__ import annotations

import asyncio
import platform
import sys
from enum import StrEnum

from pydantic import Field
from pydantic_settings import BaseSettings


class TrdexMode(StrEnum):
    SIMULATION = "simulation"
    LIVE = "live"


class Settings(BaseSettings):
    """Global application settings, loaded from .env file."""

    model_config = {"env_prefix": "TRDEX_", "env_file": ".env", "extra": "ignore"}

    # App mode
    mode: TrdexMode = TrdexMode.SIMULATION
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://trdex:trdex@localhost:5432/trdex"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # FastAPI
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_key: str = ""  # Set to enable auth; empty = dev mode (no auth)
    cors_origins: str = ""  # Comma-separated origins; empty = no CORS

    # Exchange keys (optional — only needed when connecting)
    binance_api_key: str = ""
    binance_api_secret: str = ""

    # Aggregator keys
    coingecko_api_key: str = ""

    # AI / Vector DB
    jina_api_key: str = ""          # https://jina.ai — free tier, 100 req/min
    qdrant_url: str = "http://localhost:6333"

    # Simulation gate criteria (Phase 5)
    gate_min_days: int = Field(default=30, description="Minimum simulation days before live")
    gate_min_sharpe: float = Field(default=1.0, description="Minimum Sharpe ratio")
    gate_max_drawdown: float = Field(default=0.20, description="Maximum drawdown (0-1)")
    gate_min_win_rate: float = Field(default=0.40, description="Minimum win rate (0-1)")

    # Risk defaults
    max_position_pct: float = Field(default=0.02, description="Max % of portfolio per trade")


def pin_event_loop_policy() -> None:
    """Pin asyncio event loop policy for Windows compatibility.

    Windows defaults to ProactorEventLoop which doesn't support
    add_reader/add_writer used by some async libraries.
    """
    if platform.system() == "Windows" and sys.version_info >= (3, 8):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]


settings = Settings()


def get_settings() -> Settings:
    return settings
