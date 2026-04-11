"""Tests for credentials encryption at rest.

Covers the low-level Fernet wrapper and its integration into
RuntimeConfigService. Uses an in-memory fake repo — no DB needed.
"""

from __future__ import annotations

import pytest

from trdex.services import credentials_crypto
from trdex.services.runtime_config import RuntimeConfigService


# ── Helpers ──────────────────────────────────────────────────────────────────


class _FakeRepo:
    """In-memory stand-in for RuntimeConfigRepository."""

    def __init__(self, initial: dict[str, dict[str, str]] | None = None) -> None:
        self.rows: dict[tuple[str, str], str] = {}
        if initial:
            for cat, pairs in initial.items():
                for k, v in pairs.items():
                    self.rows[(cat, k)] = v

    async def get(self, category: str, key: str) -> str | None:
        return self.rows.get((category, key))

    async def get_category(self, category: str) -> dict[str, str]:
        return {k: v for (c, k), v in self.rows.items() if c == category}

    async def get_all(self) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for (c, k), v in self.rows.items():
            out.setdefault(c, {})[k] = v
        return out

    async def put(self, category: str, key: str, value: str) -> None:
        self.rows[(category, key)] = value

    async def put_many(self, category: str, pairs: dict[str, str]) -> None:
        for k, v in pairs.items():
            self.rows[(category, k)] = v


class _FakeSession:
    """Async context manager yielding nothing — the service wraps the
    session in `async with`, then instantiates a repo inside.
    """

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


def _install_fake_repo(monkeypatch, repo: _FakeRepo):
    """Replace RuntimeConfigRepository on its source module so every
    `from trdex.storage.runtime_config_repo import RuntimeConfigRepository`
    inside the service resolves to a stub that delegates to `repo`.
    Returns a session_factory that yields dummy sessions (ignored).
    """

    class _StubRepo:
        def __init__(self, _session) -> None:
            pass

        async def get(self, category, key):
            return await repo.get(category, key)

        async def get_category(self, category):
            return await repo.get_category(category)

        async def get_all(self):
            return await repo.get_all()

        async def put(self, category, key, value):
            return await repo.put(category, key, value)

        async def put_many(self, category, pairs):
            return await repo.put_many(category, pairs)

    import trdex.storage.runtime_config_repo as repo_mod

    monkeypatch.setattr(
        repo_mod, "RuntimeConfigRepository", _StubRepo, raising=True,
    )

    def factory():
        return _FakeSession()

    return factory


@pytest.fixture(autouse=True)
def _reset_cipher_state(monkeypatch):
    """Ensure each test starts with a clean cipher state."""
    # Clear any previously initialised cipher
    credentials_crypto._cipher = None  # type: ignore[attr-defined]
    credentials_crypto._enabled = False  # type: ignore[attr-defined]
    monkeypatch.delenv("TRDEX_CONFIG_ENCRYPTION_KEY", raising=False)
    yield
    credentials_crypto._cipher = None  # type: ignore[attr-defined]
    credentials_crypto._enabled = False  # type: ignore[attr-defined]


# ── Low-level cipher ─────────────────────────────────────────────────────────


def test_passthrough_when_key_missing() -> None:
    credentials_crypto.init_cipher()
    assert credentials_crypto.is_enabled() is False
    assert credentials_crypto.encrypt("secret-123") == "secret-123"
    assert credentials_crypto.decrypt("secret-123") == "secret-123"


def test_fernet_roundtrip_when_key_present(monkeypatch) -> None:
    key = credentials_crypto.generate_key()
    monkeypatch.setenv("TRDEX_CONFIG_ENCRYPTION_KEY", key)
    credentials_crypto.init_cipher()
    assert credentials_crypto.is_enabled() is True

    plaintext = "sk-live-ABCDEF1234567890"
    ciphertext = credentials_crypto.encrypt(plaintext)

    assert ciphertext != plaintext
    assert ciphertext.startswith(credentials_crypto.FERNET_PREFIX)
    assert credentials_crypto.is_ciphertext(ciphertext)
    assert credentials_crypto.decrypt(ciphertext) == plaintext


def test_ciphertext_detection() -> None:
    assert credentials_crypto.is_ciphertext("") is False
    assert credentials_crypto.is_ciphertext("plain-value") is False
    assert credentials_crypto.is_ciphertext("gAAAAA-anything") is True


def test_empty_values_pass_through_even_when_enabled(monkeypatch) -> None:
    key = credentials_crypto.generate_key()
    monkeypatch.setenv("TRDEX_CONFIG_ENCRYPTION_KEY", key)
    credentials_crypto.init_cipher()
    assert credentials_crypto.encrypt("") == ""
    assert credentials_crypto.decrypt("") == ""


def test_malformed_key_falls_back_to_passthrough(monkeypatch) -> None:
    monkeypatch.setenv("TRDEX_CONFIG_ENCRYPTION_KEY", "not-a-valid-fernet-key")
    credentials_crypto.init_cipher()
    assert credentials_crypto.is_enabled() is False
    # Encryption becomes a no-op when the key is invalid
    assert credentials_crypto.encrypt("x") == "x"


def test_decrypt_with_wrong_key_returns_ciphertext(monkeypatch) -> None:
    key_a = credentials_crypto.generate_key()
    monkeypatch.setenv("TRDEX_CONFIG_ENCRYPTION_KEY", key_a)
    credentials_crypto.init_cipher()
    ct = credentials_crypto.encrypt("shared-secret")

    # Rotate to a different key — decrypt with the wrong key must
    # NOT return a bogus plaintext; it returns the ciphertext so
    # the caller can detect the failure and leave the row intact.
    key_b = credentials_crypto.generate_key()
    monkeypatch.setenv("TRDEX_CONFIG_ENCRYPTION_KEY", key_b)
    credentials_crypto.init_cipher()
    assert credentials_crypto.decrypt(ct) == ct


# ── Service integration ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_service_encrypts_credentials_on_put(monkeypatch) -> None:
    key = credentials_crypto.generate_key()
    monkeypatch.setenv("TRDEX_CONFIG_ENCRYPTION_KEY", key)
    credentials_crypto.init_cipher()

    repo = _FakeRepo()
    sf = _install_fake_repo(monkeypatch, repo)
    svc = RuntimeConfigService(sf)
    await svc.load()

    await svc.put("credentials", "telegram_api_hash", "hunter2-secret")

    # DB sees ciphertext
    stored = repo.rows[("credentials", "telegram_api_hash")]
    assert stored != "hunter2-secret"
    assert stored.startswith(credentials_crypto.FERNET_PREFIX)

    # Cache sees plaintext (service reads return plaintext)
    assert svc.get("credentials", "telegram_api_hash") == "hunter2-secret"


@pytest.mark.asyncio
async def test_service_does_not_encrypt_non_credential_categories(monkeypatch) -> None:
    key = credentials_crypto.generate_key()
    monkeypatch.setenv("TRDEX_CONFIG_ENCRYPTION_KEY", key)
    credentials_crypto.init_cipher()

    repo = _FakeRepo()
    sf = _install_fake_repo(monkeypatch, repo)
    svc = RuntimeConfigService(sf)
    await svc.load()

    await svc.put("thresholds", "sl_position_pct", "0.05")

    assert repo.rows[("thresholds", "sl_position_pct")] == "0.05"
    assert svc.get("thresholds", "sl_position_pct") == "0.05"


@pytest.mark.asyncio
async def test_put_category_encrypts_credentials_only(monkeypatch) -> None:
    key = credentials_crypto.generate_key()
    monkeypatch.setenv("TRDEX_CONFIG_ENCRYPTION_KEY", key)
    credentials_crypto.init_cipher()

    repo = _FakeRepo()
    sf = _install_fake_repo(monkeypatch, repo)
    svc = RuntimeConfigService(sf)
    await svc.load()

    await svc.put_category("credentials", {
        "binance_api_key": "AKIA-fake-key",
        "binance_api_secret": "very-secret-value",
    })

    assert repo.rows[("credentials", "binance_api_key")].startswith("gAAAAA")
    assert repo.rows[("credentials", "binance_api_secret")].startswith("gAAAAA")
    # Decryption via the service still works
    assert svc.get("credentials", "binance_api_key") == "AKIA-fake-key"
    assert svc.get("credentials", "binance_api_secret") == "very-secret-value"


@pytest.mark.asyncio
async def test_load_decrypts_existing_ciphertext(monkeypatch) -> None:
    key = credentials_crypto.generate_key()
    monkeypatch.setenv("TRDEX_CONFIG_ENCRYPTION_KEY", key)
    credentials_crypto.init_cipher()

    # Pre-populate the fake DB with already-encrypted rows
    ct = credentials_crypto.encrypt("pre-existing-token")
    repo = _FakeRepo({"credentials": {"perplexity_api_key": ct}})
    sf = _install_fake_repo(monkeypatch, repo)
    svc = RuntimeConfigService(sf)
    await svc.load()

    assert svc.get("credentials", "perplexity_api_key") == "pre-existing-token"


@pytest.mark.asyncio
async def test_migration_upgrades_plaintext_rows(monkeypatch) -> None:
    key = credentials_crypto.generate_key()
    monkeypatch.setenv("TRDEX_CONFIG_ENCRYPTION_KEY", key)
    credentials_crypto.init_cipher()

    # Legacy state: credentials in plaintext
    repo = _FakeRepo({"credentials": {
        "telegram_api_hash": "legacy-plaintext-1",
        "stockdata_api_key": "legacy-plaintext-2",
    }})
    sf = _install_fake_repo(monkeypatch, repo)
    svc = RuntimeConfigService(sf)
    await svc.load()

    upgraded = await svc.migrate_plaintext_credentials()
    assert upgraded == 2

    # DB rows are now ciphertext
    for k in ("telegram_api_hash", "stockdata_api_key"):
        stored = repo.rows[("credentials", k)]
        assert stored.startswith(credentials_crypto.FERNET_PREFIX)

    # Second pass is a no-op
    upgraded_again = await svc.migrate_plaintext_credentials()
    assert upgraded_again == 0


@pytest.mark.asyncio
async def test_migration_noop_when_encryption_disabled(monkeypatch) -> None:
    monkeypatch.delenv("TRDEX_CONFIG_ENCRYPTION_KEY", raising=False)
    credentials_crypto.init_cipher()
    assert credentials_crypto.is_enabled() is False

    repo = _FakeRepo({"credentials": {"telegram_api_hash": "plaintext"}})
    sf = _install_fake_repo(monkeypatch, repo)
    svc = RuntimeConfigService(sf)
    await svc.load()

    upgraded = await svc.migrate_plaintext_credentials()
    assert upgraded == 0
    # Row untouched — no pointless write
    assert repo.rows[("credentials", "telegram_api_hash")] == "plaintext"


@pytest.mark.asyncio
async def test_service_in_passthrough_mode_still_works(monkeypatch) -> None:
    """Without a key, credentials round-trip through plaintext — the
    service must keep working for dev/local environments.
    """
    monkeypatch.delenv("TRDEX_CONFIG_ENCRYPTION_KEY", raising=False)
    credentials_crypto.init_cipher()

    repo = _FakeRepo()
    sf = _install_fake_repo(monkeypatch, repo)
    svc = RuntimeConfigService(sf)
    await svc.load()

    await svc.put("credentials", "telegram_api_hash", "plain-dev-secret")
    assert repo.rows[("credentials", "telegram_api_hash")] == "plain-dev-secret"
    assert svc.get("credentials", "telegram_api_hash") == "plain-dev-secret"
