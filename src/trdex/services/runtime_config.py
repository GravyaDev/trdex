"""RuntimeConfigService: DB-backed config with in-memory cache and hot-reload.

Env vars seed the DB on first boot. After that the DB is the source of truth
and the dashboard/API can modify config without a deploy or restart.

Credentials (category "credentials") are encrypted at rest using the
Fernet wrapper in `credentials_crypto`. Ciphertext lives in the DB;
the in-memory cache holds decrypted plaintext so reads stay O(1) and
the rest of the service is unchanged. See `credentials_crypto` for
the key-management model.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from trdex.services import credentials_crypto

logger = logging.getLogger(__name__)

# ── Config key registry ──────────────────────────────────────────────────────
# Maps (category, key) → (settings_attr, python_type).
# Used for seeding from env vars and for type coercion on reads.

_KEY_REGISTRY: dict[tuple[str, str], tuple[str, type]] = {
    # Credentials
    ("credentials", "cryptocompare_api_key"): ("cryptocompare_api_key", str),
    ("credentials", "stockdata_api_key"): ("stockdata_api_key", str),
    ("credentials", "perplexity_api_key"): ("perplexity_api_key", str),
    ("credentials", "jina_api_key"): ("jina_api_key", str),
    ("credentials", "binance_api_key"): ("binance_api_key", str),
    ("credentials", "binance_api_secret"): ("binance_api_secret", str),
    ("credentials", "telegram_api_id"): ("telegram_api_id", int),
    ("credentials", "telegram_api_hash"): ("telegram_api_hash", str),
    ("credentials", "telegram_phone"): ("telegram_phone", str),
    ("credentials", "twelve_data_api_key"): (None, str),
    ("credentials", "forex_api_key"): ("forex_api_key", str),
    # Symbols
    ("symbols", "agent_scheduler_symbols"): ("agent_scheduler_symbols", str),
    ("symbols", "ingestion_symbols"): ("ingestion_symbols", str),
    # Thresholds
    ("thresholds", "sl_position_pct"): ("sl_position_pct", float),
    ("thresholds", "sl_take_profit_pct"): ("sl_take_profit_pct", float),
    ("thresholds", "sl_trailing_stop_pct"): ("sl_trailing_stop_pct", float),
    ("thresholds", "sl_daily_drawdown_pct"): ("sl_daily_drawdown_pct", float),
    ("thresholds", "gate_max_drawdown"): ("gate_max_drawdown", float),
    ("thresholds", "gate_min_days"): ("gate_min_days", int),
    ("thresholds", "max_position_pct"): ("max_position_pct", float),
    ("thresholds", "max_drawdown_block"): (None, float),
    # Scheduler
    ("scheduler", "agent_scheduler_enabled"): ("agent_scheduler_enabled", bool),
    ("scheduler", "agent_scheduler_interval"): ("agent_scheduler_interval", int),
    ("scheduler", "agent_scheduler_active_hours"): ("agent_scheduler_active_hours", str),
    ("scheduler", "sl_check_interval"): ("sl_check_interval", float),
    ("scheduler", "ingestion_interval"): ("ingestion_interval", int),
    ("scheduler", "telegram_eval_interval"): (None, int),
    # Telegram
    ("telegram", "telegram_channels"): ("telegram_channels", str),
    ("telegram", "telegram_enabled"): (None, bool),
    ("telegram", "telegram_channel_titles"): (None, str),  # JSON map {chat_id: title}
    # Feeds
    ("feeds", "selected_feeds"): (None, str),  # No env var equivalent
}

CREDENTIAL_KEYS = {k for (cat, k), _ in _KEY_REGISTRY.items() if cat == "credentials"}


def _coerce(value: str, target_type: type) -> Any:
    """Convert a string value to the target Python type."""
    if target_type is bool:
        return value.lower() in ("true", "1", "yes", "on")
    if target_type is int:
        return int(float(value)) if value else 0
    if target_type is float:
        return float(value) if value else 0.0
    return value


def mask_credential(value: str) -> str:
    """Mask a credential for API responses — show only last 4 chars."""
    if not value:
        return ""
    return f"****{value[-4:]}" if len(value) >= 4 else "****"


# ── Service ──────────────────────────────────────────────────────────────────

_service: RuntimeConfigService | None = None


class RuntimeConfigService:
    """In-memory cache backed by the runtime_config DB table.

    Reads are instant (dict lookup). Writes go to DB, update cache,
    and fire registered listeners for hot-reload.
    """

    def __init__(self, session_factory) -> None:
        self._sf = session_factory
        self._cache: dict[str, dict[str, str]] = {}
        self._listeners: dict[str, list[Callable]] = {}

    async def load(self) -> None:
        """Load all config from DB into the in-memory cache.

        Credential values are decrypted here so the rest of the
        service sees plaintext. Non-credential values pass through.
        Legacy plaintext credentials (pre-encryption) are loaded
        as-is and get upgraded on the next write or on the
        explicit `migrate_plaintext_credentials()` pass.
        """
        from trdex.storage.runtime_config_repo import RuntimeConfigRepository
        async with self._sf() as session:
            repo = RuntimeConfigRepository(session)
            raw = await repo.get_all()

        cache: dict[str, dict[str, str]] = {}
        for category, pairs in raw.items():
            if category == "credentials":
                cache[category] = {
                    k: credentials_crypto.decrypt(v) for k, v in pairs.items()
                }
            else:
                cache[category] = dict(pairs)
        self._cache = cache
        total = sum(len(v) for v in self._cache.values())
        logger.info("[RuntimeConfig] loaded %d keys from DB", total)

    async def migrate_plaintext_credentials(self) -> int:
        """One-time migration: re-save any plaintext credential rows
        so they become encrypted at rest.

        Idempotent: rows that are already Fernet ciphertext are
        skipped. Does nothing when encryption is disabled (no key).
        Returns the number of rows rewritten.
        """
        if not credentials_crypto.is_enabled():
            return 0

        from trdex.storage.runtime_config_repo import RuntimeConfigRepository
        upgraded = 0
        async with self._sf() as session:
            repo = RuntimeConfigRepository(session)
            raw = await repo.get_category("credentials")
            for key, stored in raw.items():
                if not stored:
                    continue
                if credentials_crypto.is_ciphertext(stored):
                    continue
                ciphertext = credentials_crypto.encrypt(stored)
                await repo.put("credentials", key, ciphertext)
                upgraded += 1
        if upgraded:
            logger.info(
                "[RuntimeConfig] migrated %d plaintext credential "
                "rows to encrypted storage", upgraded,
            )
        return upgraded

    async def seed_from_settings(self, settings) -> None:
        """Insert env var values for keys that don't exist in DB yet.

        Only runs on first boot (or after a DB wipe). Existing DB values
        are never overwritten — the DB always wins.

        Credential rows are encrypted before hitting the DB; the cache
        keeps the plaintext so the rest of the service is unchanged.
        """
        from trdex.storage.runtime_config_repo import RuntimeConfigRepository
        seeded = 0
        async with self._sf() as session:
            repo = RuntimeConfigRepository(session)
            for (category, key), (settings_attr, _type) in _KEY_REGISTRY.items():
                if settings_attr is None:
                    continue
                # Skip if DB already has this key
                if self._cache.get(category, {}).get(key) is not None:
                    continue
                value = str(getattr(settings, settings_attr, ""))
                if not value and _type in (int, float):
                    value = str(getattr(settings, settings_attr, 0))
                stored = (
                    credentials_crypto.encrypt(value)
                    if category == "credentials" and value
                    else value
                )
                await repo.put(category, key, stored)
                self._cache.setdefault(category, {})[key] = value
                seeded += 1
        if seeded:
            logger.info("[RuntimeConfig] seeded %d keys from env vars", seeded)

    # ── reads (instant, from cache) ──────────────────────────────────────

    def get(self, category: str, key: str, default: str = "") -> str:
        return self._cache.get(category, {}).get(key, default)

    def get_typed(self, category: str, key: str, default: Any = None) -> Any:
        raw = self._cache.get(category, {}).get(key)
        if raw is None:
            return default
        reg = _KEY_REGISTRY.get((category, key))
        if reg is None:
            return raw
        _, target_type = reg
        return _coerce(raw, target_type)

    def get_category(self, category: str) -> dict[str, str]:
        return dict(self._cache.get(category, {}))

    def get_all_categories(self) -> dict[str, dict[str, str]]:
        return {cat: dict(vals) for cat, vals in self._cache.items()}

    # ── writes (DB + cache + listeners) ──────────────────────────────────

    async def put(self, category: str, key: str, value: str) -> None:
        """Persist a single config value and fire listeners.

        Cache holds plaintext. DB holds ciphertext for credentials.
        Listeners receive plaintext (they mirror user-facing values).
        """
        stored = (
            credentials_crypto.encrypt(value)
            if category == "credentials" and value
            else value
        )
        from trdex.storage.runtime_config_repo import RuntimeConfigRepository
        async with self._sf() as session:
            repo = RuntimeConfigRepository(session)
            await repo.put(category, key, stored)
        self._cache.setdefault(category, {})[key] = value
        self._fire_listeners(category, key, value)

    async def put_category(self, category: str, pairs: dict[str, str]) -> None:
        """Bulk upsert. Same encryption rules as `put()`."""
        if category == "credentials":
            stored_pairs = {
                k: (credentials_crypto.encrypt(v) if v else v)
                for k, v in pairs.items()
            }
        else:
            stored_pairs = pairs
        from trdex.storage.runtime_config_repo import RuntimeConfigRepository
        async with self._sf() as session:
            repo = RuntimeConfigRepository(session)
            await repo.put_many(category, stored_pairs)
        for key, value in pairs.items():
            self._cache.setdefault(category, {})[key] = value
            self._fire_listeners(category, key, value)

    # ── hot-reload listeners ─────────────────────────────────────────────

    def register_listener(self, category: str, callback: Callable) -> None:
        """Register a callback fired on put() for a category.

        Callback signature: callback(key: str, value: str) -> None
        """
        self._listeners.setdefault(category, []).append(callback)

    def _fire_listeners(self, category: str, key: str, value: str) -> None:
        for cb in self._listeners.get(category, []):
            try:
                cb(key, value)
            except Exception:
                logger.exception(
                    "[RuntimeConfig] listener error for %s.%s", category, key
                )


async def init_config_service(session_factory, settings) -> RuntimeConfigService:
    """Create, load, seed, and register the global singleton.

    Order matters:
      1. init_cipher() — sets up Fernet if the env var is present.
         Must run before load() so decrypt works on the first read.
      2. load() — pulls raw rows from DB; credentials category is
         decrypted via the cipher. Legacy plaintext rows survive
         and will be reloaded after the migration step rewrites
         them as ciphertext.
      3. migrate_plaintext_credentials() — idempotent one-shot
         upgrade of any plaintext rows left over from earlier
         deployments. No-op when the cipher is disabled.
      4. load() again — refresh the cache so the now-encrypted
         rows are read back as plaintext through decrypt().
      5. seed_from_settings() — env-var seed for keys still
         missing after step 4.
    """
    global _service
    credentials_crypto.init_cipher()
    svc = RuntimeConfigService(session_factory)
    await svc.load()
    upgraded = await svc.migrate_plaintext_credentials()
    if upgraded:
        await svc.load()
    await svc.seed_from_settings(settings)
    _service = svc
    return svc


def get_config_service() -> RuntimeConfigService | None:
    return _service
