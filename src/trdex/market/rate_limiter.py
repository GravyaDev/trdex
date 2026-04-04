"""Adaptive rate limiter with convex throttle and circuit breaker."""

from __future__ import annotations

import asyncio
import logging
import time
from enum import StrEnum

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class RateLimiter:
    """Per-exchange adaptive rate limiter.

    Uses real API headers when available, falls back to conservative
    local timer. Implements convex throttle curve and circuit breaker
    with half-open recovery.
    """

    def __init__(
        self,
        name: str,
        default_rpm: int = 10,
        max_circuit_pause: float = 300.0,
    ) -> None:
        self.name = name
        self.default_rpm = default_rpm
        self.max_circuit_pause = max_circuit_pause

        # State
        self._utilization: float = 0.0
        self._last_request: float = 0.0
        self._consecutive_429s: int = 0

        # Circuit breaker
        self._circuit_state = CircuitState.CLOSED
        self._circuit_open_until: float = 0.0
        self._circuit_pause: float = 60.0

    async def acquire(self) -> None:
        """Wait until it's safe to make a request."""
        # Circuit breaker check
        if self._circuit_state == CircuitState.OPEN:
            now = time.monotonic()
            if now < self._circuit_open_until:
                wait = self._circuit_open_until - now
                logger.warning("%s: circuit OPEN, waiting %.1fs", self.name, wait)
                await asyncio.sleep(wait)
            self._circuit_state = CircuitState.HALF_OPEN
            logger.info("%s: circuit → HALF_OPEN (probe)", self.name)
            return  # Allow one probe request

        # Convex throttle delay based on utilization
        delay = self._compute_delay()
        if delay > 0:
            elapsed = time.monotonic() - self._last_request
            if elapsed < delay:
                await asyncio.sleep(delay - elapsed)

        self._last_request = time.monotonic()

    def report_success(self) -> None:
        """Call after a successful API response."""
        self._consecutive_429s = 0
        if self._circuit_state == CircuitState.HALF_OPEN:
            self._circuit_state = CircuitState.CLOSED
            self._circuit_pause = 60.0
            logger.info("%s: circuit → CLOSED (probe succeeded)", self.name)

    def report_rate_limit(self) -> None:
        """Call after receiving a 429 or rate limit error."""
        self._consecutive_429s += 1
        if self._consecutive_429s >= 3:
            self._trip_circuit()

    def update_utilization(self, used: int, limit: int) -> None:
        """Update utilization from API response headers.

        Args:
            used: Current usage count (e.g. X-MBX-USED-WEIGHT).
            limit: Maximum allowed (e.g. from docs or headers).
        """
        if limit > 0:
            self._utilization = used / limit
        logger.debug(
            "%s: utilization %.1f%% (%d/%d)",
            self.name,
            self._utilization * 100,
            used,
            limit,
        )

    def _compute_delay(self) -> float:
        """Compute delay based on convex throttle curve.

        < 60%: normal (base interval from RPM)
        60-85%: progressive slowdown (exponential)
        85-95%: near-stop (5-10s per request)
        > 95%: full stop (wait for reset)
        """
        base = 60.0 / self.default_rpm  # seconds between requests

        u = self._utilization
        if u < 0.60:
            return base
        if u < 0.85:
            # Exponential ramp: 1x to ~4x base delay
            factor = 1.0 + ((u - 0.60) / 0.25) ** 2 * 3.0
            return base * factor
        if u < 0.95:
            return max(base * 8.0, 5.0)
        # > 95%: full stop
        return 30.0

    def _trip_circuit(self) -> None:
        """Open the circuit breaker."""
        self._circuit_state = CircuitState.OPEN
        self._circuit_open_until = time.monotonic() + self._circuit_pause
        logger.warning(
            "%s: circuit → OPEN (3x 429), pausing %.0fs",
            self.name,
            self._circuit_pause,
        )
        # Exponential backoff on pause, capped
        self._circuit_pause = min(self._circuit_pause * 2, self.max_circuit_pause)

    @property
    def utilization(self) -> float:
        return self._utilization

    @property
    def circuit_state(self) -> CircuitState:
        return self._circuit_state
