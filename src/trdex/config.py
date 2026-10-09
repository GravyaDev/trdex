"""Application configuration via environment variables."""

from __future__ import annotations

import asyncio
import platform
import sys
from enum import StrEnum

from pydantic import AliasChoices, Field
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

    # Database — accepts DATABASE_URL (no prefix) or TRDEX_DATABASE_URL
    database_url: str = Field(
        default="postgresql+asyncpg://trdex:trdex@localhost:5432/trdex",
        validation_alias=AliasChoices("TRDEX_DATABASE_URL", "DATABASE_URL"),
    )

    @property
    def _uses_default_db_creds(self) -> bool:
        """True if the DB URL still has the dev-only default password."""
        return "trdex:trdex@" in self.database_url

    # Redis — accepts REDIS_URL or TRDEX_REDIS_URL
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("TRDEX_REDIS_URL", "REDIS_URL"),
    )

    # FastAPI
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_key: str = ""  # Set to enable auth; empty = dev mode (no auth)
    cors_origins: str = ""  # Comma-separated origins; empty = no CORS

    # Credentials encryption master key (Fernet, 44-char urlsafe base64).
    # When set, runtime_config.credentials rows are encrypted at rest.
    # When empty, the service runs in passthrough mode with a WARNING
    # log at startup. Generate a new key with:
    #   python -m trdex.services.credentials_crypto
    # Never commit a key. Set only in Coolify / deployment secrets.
    config_encryption_key: str = Field(
        default="",
        validation_alias=AliasChoices("TRDEX_CONFIG_ENCRYPTION_KEY"),
    )

    # Exchange keys (optional — only needed when connecting)
    # Accept both BINANCE_API_KEY (no prefix) and TRDEX_BINANCE_API_KEY (with prefix)
    binance_api_key: str = Field(default="", validation_alias=AliasChoices("TRDEX_BINANCE_API_KEY", "BINANCE_API_KEY"))
    binance_api_secret: str = Field(default="", validation_alias=AliasChoices("TRDEX_BINANCE_API_SECRET", "BINANCE_API_SECRET"))
    binance_api_secret_file: str = Field(default="", validation_alias=AliasChoices("TRDEX_BINANCE_API_SECRET_FILE", "BINANCE_API_SECRET_FILE"))
    binance_testnet: bool = Field(default=True, description="Use Binance testnet (true) or production (false)")

    @property
    def binance_effective_secret(self) -> str:
        """Return the effective Binance secret: PEM file content if configured, else raw secret."""
        if self.binance_api_secret_file:
            from pathlib import Path
            p = Path(self.binance_api_secret_file).expanduser()
            if p.exists():
                return p.read_text().strip()
        return self.binance_api_secret

    # Aggregator keys
    coingecko_api_key: str = ""
    forex_api_key: str = ""          # https://exchangerate-api.com — free tier
    cryptocompare_api_key: str = ""  # https://cryptocompare.com — free tier
    alphavantage_api_key: str = ""   # https://alphavantage.co — free tier
    freecryptoapi_key: str = ""      # https://freecryptoapi.com — free tier (optional)

    # News sources
    stockdata_api_key: str = ""      # https://stockdata.org — free tier
    ingestion_interval: int = 300    # seconds between news fetch cycles
    ingestion_symbols: str = ""      # comma-separated symbols to track, e.g. "BTC/USDT,ETH/USDT"

    @property
    def agent_scheduler_symbols_list(self) -> list[str]:
        if not self.agent_scheduler_symbols:
            return []
        return [s.strip() for s in self.agent_scheduler_symbols.split(",") if s.strip()]

    @property
    def ingestion_symbols_list(self) -> list[str]:
        """Parse ingestion_symbols CSV into a list."""
        if not self.ingestion_symbols:
            return []
        return [s.strip() for s in self.ingestion_symbols.split(",") if s.strip()]

    # AI / Vector DB
    jina_api_key: str = ""          # https://jina.ai — free tier, 100 req/min
    perplexity_api_key: str = ""    # https://perplexity.ai — sonar search API
    qdrant_url: str = "http://localhost:6333"

    # LLM provider API keys (Task 1 — llm-agents branch)
    anthropic_api_key: str = ""     # sk-ant-... — required for Claude models
    openai_api_key: str = ""        # sk-... — required for GPT models
    google_api_key: str = ""        # AIza... — required for Gemini models
    groq_api_key: str = ""          # gsk_... — required for Groq (Llama/Mixtral)
    together_api_key: str = ""      # required for Together.ai
    deepseek_api_key: str = ""      # required for DeepSeek
    xai_api_key: str = ""           # required for xAI (Grok)
    mistral_api_key: str = ""       # required for Mistral

    # LLM cost guardrails
    llm_daily_budget: float = Field(default=20.0, description="Hard cap $/day for LLM calls")
    llm_monthly_budget: float = Field(default=500.0, description="Hard cap $/month for LLM calls")

    # LLM prompt assembly
    llm_max_prompt_tokens: int = Field(
        default=4096,
        description="Max input tokens for prompt assembly — memory tiers truncated LIFO if exceeded",
    )

    # Telegram signal following (my.telegram.org)
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_phone: str = ""
    telegram_channels: str = ""     # comma-separated, e.g. "@ch1,@ch2"

    @property
    def telegram_channels_list(self) -> list[str]:
        """Parse telegram_channels CSV into a list, stripping whitespace."""
        if not self.telegram_channels:
            return []
        return [ch.strip() for ch in self.telegram_channels.split(",") if ch.strip()]
    telegram_signal_budget: float = 100.0  # fixed budget per signal (quote currency)

    # Simulation gate criteria (Phase 5)
    gate_min_days: int = Field(default=20, description="Minimum simulation days before live")
    gate_min_sharpe: float = Field(default=1.0, description="Minimum Sharpe ratio")
    gate_max_drawdown: float = Field(default=0.20, description="Maximum drawdown (0-1)")
    gate_min_win_rate: float = Field(default=0.40, description="Minimum win rate (0-1)")

    # Risk defaults
    max_position_pct: float = Field(default=0.05, description="Max % of portfolio per trade")
    risk_per_trade_pct: float = Field(
        default=0.001,
        description="Equity fraction lost if the stop is hit (risk-based sizing, capped by max_position_pct)",
    )

    # Stop-loss monitor (external, independent of AI agents)
    sl_check_interval: float = Field(default=30.0, description="Seconds between stop-loss checks")
    sl_position_pct: float = Field(default=0.02, description="Per-position stop-loss (2% = close at -2%)")
    sl_take_profit_pct: float = Field(default=0.04, description="Per-position take-profit (4%)")
    sl_trailing_stop_pct: float = Field(default=0.015, description="Trailing stop: close if price retraces 1.5% from peak")
    sl_daily_drawdown_pct: float = Field(default=0.10, description="Equity loss since 00:00 UTC (realised + unrealised) → kill switch")
    sl_open_positions_loss_pct: float = Field(default=0.10, description="Unrealised loss as fraction of open-positions cost → kill switch")

    # Agent scheduler
    agent_scheduler_enabled: bool = Field(default=False, description="Auto-run agent cycle on interval")
    agent_scheduler_interval: int = Field(default=300, description="Seconds between agent cycles")
    agent_scheduler_symbols: str = Field(default="", description="Comma-separated symbols for auto agent runs")
    agent_scheduler_active_hours: str = Field(default="", description="Active hours window 'HH:MM-HH:MM' UTC (empty = H24)")


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
