"""Regression tests for verify_api_key fail-safe hardening.

Covers the 2026-04-11 security fix:
- Outside SIMULATION mode, unset TRDEX_API_KEY must make verify_api_key
  raise 503 (defense-in-depth — the lifespan guard should already have
  blocked boot, but a runtime fallback to dev-mode "authentication" is
  unacceptable for non-sim deployments).
- In SIMULATION mode, unset key is tolerated and returns "dev-mode".
- Valid key is accepted regardless of mode.
- Invalid key raises 403 regardless of mode.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from trdex.api.app import verify_api_key
from trdex.config import TrdexMode


class TestVerifyApiKeyHardening:
    async def test_empty_key_in_live_mode_raises_503(self) -> None:
        """Live mode with unset TRDEX_API_KEY must reject all requests."""
        with patch("trdex.api.app.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.mode = TrdexMode.LIVE
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(api_key=None)
            assert exc_info.value.status_code == 503
            assert "misconfigured" in exc_info.value.detail.lower()

    async def test_empty_key_in_simulation_mode_returns_dev_mode(self) -> None:
        """Simulation mode with unset key tolerated (dev convenience)."""
        with patch("trdex.api.app.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.mode = TrdexMode.SIMULATION
            result = await verify_api_key(api_key=None)
            assert result == "dev-mode"

    async def test_valid_key_live_mode(self) -> None:
        with patch("trdex.api.app.settings") as mock_settings:
            mock_settings.api_key = "test-key-live-mode"
            mock_settings.mode = TrdexMode.LIVE
            result = await verify_api_key(api_key="test-key-live-mode")
            assert result == "test-key-live-mode"

    async def test_valid_key_simulation_mode(self) -> None:
        with patch("trdex.api.app.settings") as mock_settings:
            mock_settings.api_key = "test-key-sim"
            mock_settings.mode = TrdexMode.SIMULATION
            result = await verify_api_key(api_key="test-key-sim")
            assert result == "test-key-sim"

    async def test_invalid_key_raises_403_live_mode(self) -> None:
        with patch("trdex.api.app.settings") as mock_settings:
            mock_settings.api_key = "correct-key"
            mock_settings.mode = TrdexMode.LIVE
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(api_key="wrong-key")
            assert exc_info.value.status_code == 403

    async def test_missing_key_header_raises_403_when_key_configured(self) -> None:
        with patch("trdex.api.app.settings") as mock_settings:
            mock_settings.api_key = "correct-key"
            mock_settings.mode = TrdexMode.LIVE
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(api_key=None)
            assert exc_info.value.status_code == 403
