"""Notification event types and their default routing.

Each event is routed independently (Runtime Config
``notifications.route_<event>``) to ``telegram``, ``email``, ``both`` or
``none``. Defaults push everything that needs a human to both channels;
routine confirmations go to Telegram only.
"""

from __future__ import annotations

from enum import StrEnum


class Event(StrEnum):
    KILL_SWITCH = "kill_switch"
    READINESS_CHANGED = "readiness_changed"
    REGIME_REFRESHED = "regime_refreshed"
    REGIME_VALIDATION_FAILED = "regime_validation_failed"
    REGIME_REFRESH_ERROR = "regime_refresh_error"
    REGIME_EXPIRING = "regime_expiring"


ROUTES = ("telegram", "email", "both", "none")

DEFAULT_ROUTES: dict[Event, str] = {
    Event.KILL_SWITCH: "both",
    Event.READINESS_CHANGED: "both",
    Event.REGIME_REFRESHED: "telegram",
    Event.REGIME_VALIDATION_FAILED: "both",
    Event.REGIME_REFRESH_ERROR: "both",
    Event.REGIME_EXPIRING: "both",
}

LABELS: dict[Event, str] = {
    Event.KILL_SWITCH: "Kill switch activated",
    Event.READINESS_CHANGED: "Live readiness changed",
    Event.REGIME_REFRESHED: "Regime bounds refreshed",
    Event.REGIME_VALIDATION_FAILED: "Regime revalidation failed (bounds kept)",
    Event.REGIME_REFRESH_ERROR: "Regime refresh job error",
    Event.REGIME_EXPIRING: "Regime bounds expiring / expired",
}


def route_key(event: Event) -> str:
    return f"route_{event.value}"
