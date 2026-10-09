"""Notifier: routes an event to the channels configured for it.

Configuration lives in Runtime Config (dashboard → Notifications):

- ``credentials.telegram_bot_token`` (encrypted), ``notifications.telegram_bot_chat_id``
- ``notifications.smtp_host`` / ``smtp_port`` / ``smtp_security`` /
  ``smtp_username`` / ``email_from`` / ``email_to`` (comma-separated),
  ``credentials.smtp_password`` (encrypted)
- ``notifications.route_<event>``: telegram | email | both | none

Notifying never raises: a delivery failure is logged with the event, so
the code path that triggered it (kill switch, refresher) is unaffected.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from trdex.notify.channels import Channel, EmailChannel, NotificationError, TelegramBotChannel
from trdex.notify.events import DEFAULT_ROUTES, ROUTES, Event, route_key

logger = logging.getLogger(__name__)

_background: set[asyncio.Task[Any]] = set()


def _default_cfg() -> Any:
    from trdex.services.runtime_config import get_config_service

    return get_config_service()


def build_channel(cfg: Any, name: str) -> Channel | None:
    """The configured channel ``name``, or None if its settings are incomplete."""
    if cfg is None:
        return None
    if name == "telegram":
        token = cfg.get("credentials", "telegram_bot_token", "")
        chat_id = cfg.get("notifications", "telegram_bot_chat_id", "")
        return TelegramBotChannel(token, chat_id) if token and chat_id else None
    if name == "email":
        host = cfg.get("notifications", "smtp_host", "")
        sender = cfg.get("notifications", "email_from", "")
        recipients = [
            r.strip() for r in cfg.get("notifications", "email_to", "").split(",") if r.strip()
        ]
        if not (host and sender and recipients):
            return None
        security = cfg.get("notifications", "smtp_security", "") or "starttls"
        default_port = {"ssl": 465, "none": 25}.get(security, 587)
        try:
            port = int(cfg.get("notifications", "smtp_port", "") or default_port)
            return EmailChannel(
                host=host,
                port=port,
                sender=sender,
                recipients=recipients,
                username=cfg.get("notifications", "smtp_username", ""),
                password=cfg.get("credentials", "smtp_password", ""),
                security=security,
            )
        except ValueError as exc:
            logger.error("[notify] email settings invalid: %s", exc)
            return None
    raise ValueError(f"unknown channel {name!r}")


def route_for(cfg: Any, event: Event) -> str:
    raw = cfg.get("notifications", route_key(event), "") if cfg is not None else ""
    route = (raw or DEFAULT_ROUTES[event]).strip().lower()
    if route not in ROUTES:
        logger.warning("[notify] invalid route %r for %s, using both", route, event.value)
        return "both"
    return route


def _channel_names(route: str) -> list[str]:
    return {"telegram": ["telegram"], "email": ["email"], "both": ["telegram", "email"]}.get(
        route, []
    )


class Notifier:
    def __init__(self, cfg_provider: Callable[[], Any] = _default_cfg) -> None:
        self._cfg_provider = cfg_provider

    async def notify(self, event: Event, subject: str, body: str) -> dict[str, str]:
        """Send to the event's channels. Returns {channel: outcome} for logging/tests."""
        cfg = self._cfg_provider()
        route = route_for(cfg, event)
        outcome: dict[str, str] = {}
        for name in _channel_names(route):
            outcome[name] = await self.send_via(name, subject, body, cfg=cfg)
        if route != "none" and not any(v == "sent" for v in outcome.values()):
            logger.error(
                "[notify] %s NOT delivered (%s): %s — %s", event.value, outcome, subject, body
            )
        return outcome

    async def send_via(self, name: str, subject: str, body: str, *, cfg: Any = None) -> str:
        cfg = cfg if cfg is not None else self._cfg_provider()
        try:
            channel = build_channel(cfg, name)
        except ValueError as exc:
            return f"error: {exc}"
        if channel is None:
            return "not configured"
        try:
            await channel.send(subject, body)
        except NotificationError as exc:
            logger.error("[notify] %s failed: %s", name, exc)
            return f"error: {exc}"
        except Exception as exc:  # never let a notification break the caller
            logger.exception("[notify] %s crashed", name)
            return f"error: {type(exc).__name__}"
        return "sent"


_notifier = Notifier()


async def notify(event: Event, subject: str, body: str) -> dict[str, str]:
    return await _notifier.notify(event, subject, body)


def notify_background(event: Event, subject: str, body: str) -> None:
    """Fire-and-forget from async code; no-op (logged) without a running loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("[notify] no event loop, %s not sent: %s", event.value, subject)
        return
    task = loop.create_task(notify(event, subject, body))
    _background.add(task)
    task.add_done_callback(_background.discard)
