"""Symmetric encryption for credentials stored in runtime_config.

Uses Fernet (AES-128-CBC + HMAC-SHA256 + random IV) from the
`cryptography` library — the standard symmetric authenticated
encryption primitive when requirements are plain "encrypt-at-rest
with a shared key". Fernet tokens are URL-safe base64 strings that
always start with the version marker `gAAAAA`, which we use to
distinguish ciphertext from legacy plaintext rows.

Key management
--------------
The master key is read from the `TRDEX_CONFIG_ENCRYPTION_KEY` env var
(44-char url-safe base64). If unset, the module operates in
*passthrough mode*: encrypt() and decrypt() return the input
unchanged, and `is_enabled()` returns False. This lets dev/test
environments run without ceremony while still failing loud (WARNING
log at startup) so a forgotten key in production is visible.

Security notes
--------------
- Never log the key or the decrypted value.
- Never commit a key file to the repo.
- Rotating the key is out of scope for this first iteration — to
  rotate, decrypt with the old key, re-encrypt with the new one,
  and update the env var.
- Only the `credentials` category is encrypted. Thresholds,
  symbols, scheduler etc. stay plaintext so the dashboard and
  logs remain readable for routine debugging.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


# Fernet tokens always begin with this marker — version byte 0x80
# (128) encoded in the base64 alphabet produces "gAAAAA" as the
# prefix of every Fernet ciphertext. See:
# https://cryptography.io/en/latest/fernet/#implementation
FERNET_PREFIX = "gAAAAA"


class _Passthrough:
    """No-op cipher used when the env var is not set.

    Exists so the service layer can unconditionally call encrypt/
    decrypt without branching. Logs a WARNING at construction time
    and nothing else afterwards.
    """

    def encrypt(self, plaintext: str) -> str:
        return plaintext

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext


class _FernetCipher:
    """Fernet-backed cipher used when the env var is set."""

    def __init__(self, key: bytes) -> None:
        from cryptography.fernet import Fernet

        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return plaintext
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ciphertext
        if not is_ciphertext(ciphertext):
            # Plain legacy value — let the caller handle migration.
            return ciphertext
        from cryptography.fernet import InvalidToken

        try:
            plaintext = self._fernet.decrypt(ciphertext.encode("ascii"))
        except InvalidToken:
            logger.error(
                "[credentials_crypto] decrypt failed: token invalid or "
                "signed with a different key. Row left unchanged."
            )
            return ciphertext
        return plaintext.decode("utf-8")


_cipher: _FernetCipher | _Passthrough | None = None
_enabled: bool = False


def init_cipher(env_var: str = "TRDEX_CONFIG_ENCRYPTION_KEY") -> None:
    """Initialise the module-level cipher from an env var.

    Called once at startup from init_config_service(). Safe to call
    more than once — subsequent calls reinitialise. If the env var
    is missing or the key is malformed, falls back to passthrough
    mode with a WARNING log.
    """
    global _cipher, _enabled
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        logger.warning(
            "[credentials_crypto] %s not set — credentials in "
            "runtime_config will remain plaintext. Set this env var "
            "to a 44-char urlsafe base64 key (generate with "
            "`python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'`) to enable "
            "at-rest encryption.",
            env_var,
        )
        _cipher = _Passthrough()
        _enabled = False
        return

    try:
        _cipher = _FernetCipher(raw.encode("ascii"))
        _enabled = True
        logger.info(
            "[credentials_crypto] at-rest encryption enabled (Fernet)"
        )
    except Exception:
        logger.exception(
            "[credentials_crypto] invalid %s — falling back to "
            "passthrough. Credentials will be stored in plaintext.",
            env_var,
        )
        _cipher = _Passthrough()
        _enabled = False


def is_enabled() -> bool:
    """Return True iff a real Fernet key is loaded."""
    return _enabled


def is_ciphertext(value: str) -> bool:
    """Detect a Fernet token by its version-byte prefix."""
    return bool(value) and value.startswith(FERNET_PREFIX)


def encrypt(plaintext: str) -> str:
    """Encrypt a credential value. Returns the input unchanged when
    encryption is disabled (passthrough mode).
    """
    if _cipher is None:
        init_cipher()
    assert _cipher is not None
    return _cipher.encrypt(plaintext)


def decrypt(ciphertext: str) -> str:
    """Decrypt a credential value. Returns the input unchanged when
    the value is plaintext legacy or when encryption is disabled.
    """
    if _cipher is None:
        init_cipher()
    assert _cipher is not None
    return _cipher.decrypt(ciphertext)


def generate_key() -> str:
    """Helper: generate a new 44-char urlsafe base64 key.

    Not called automatically. Provided so `python -m
    trdex.services.credentials_crypto` (or a one-off shell command)
    can produce a key to paste into Coolify.
    """
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("ascii")


if __name__ == "__main__":
    print(generate_key())
