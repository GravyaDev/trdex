"""Delivery channels: Telegram bot and SMTP email.

Both raise ``NotificationError`` when a message could not be delivered
after their retries; the Notifier logs it and carries on. Secrets (bot
token, SMTP password) never appear in error messages or logs.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from collections.abc import Awaitable, Callable
from email.message import EmailMessage
from typing import Any, Protocol

import httpx

TELEGRAM_API = "https://api.telegram.org"
TELEGRAM_MAX_LEN = 4096


class NotificationError(RuntimeError):
    """A channel could not deliver a message."""


class Channel(Protocol):
    name: str

    async def send(self, subject: str, body: str) -> None: ...


def _redact(text: str, *secrets: str) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


class TelegramBotChannel:
    """Telegram Bot API ``sendMessage`` with bounded retries.

    Retries network errors and 5xx with exponential backoff, honours
    ``retry_after`` on 429, and fails fast on other 4xx (wrong token or
    chat id will not fix themselves).
    """

    name = "telegram"

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        if not token or not chat_id:
            raise ValueError("telegram bot token and chat id are required")
        self._token = token
        self._chat_id = chat_id
        self._max_attempts = max_attempts
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._client_factory = client_factory
        self._sleep = sleep

    async def send(self, subject: str, body: str) -> None:
        text = f"{subject}\n\n{body}".strip()
        if len(text) > TELEGRAM_MAX_LEN:
            text = text[: TELEGRAM_MAX_LEN - 1] + "…"
        url = f"{TELEGRAM_API}/bot{self._token}/sendMessage"
        payload = {"chat_id": self._chat_id, "text": text, "disable_web_page_preview": True}
        last = "no attempt made"
        for attempt in range(self._max_attempts):
            delay = self._base_delay * (2**attempt)
            try:
                async with self._client_factory(timeout=10.0) as client:
                    resp = await client.post(url, json=payload)
            except httpx.HTTPError as exc:
                last = f"network error: {type(exc).__name__}"
            else:
                data = _json(resp)
                if resp.status_code == 200 and data.get("ok"):
                    return
                desc = str(data.get("description", ""))[:200]
                last = f"HTTP {resp.status_code} {desc}".strip()
                if resp.status_code == 429:
                    retry_after = (data.get("parameters") or {}).get("retry_after")
                    if isinstance(retry_after, (int, float)):
                        delay = float(retry_after)
                elif 400 <= resp.status_code < 500:
                    raise NotificationError(_redact(f"telegram: {last}", self._token))
            if attempt < self._max_attempts - 1:
                await self._sleep(min(delay, self._max_delay))
        raise NotificationError(
            _redact(f"telegram: gave up after {self._max_attempts} attempts ({last})", self._token)
        )


def _json(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


class EmailChannel:
    """SMTP email (STARTTLS, implicit SSL or plain), sent in a worker thread."""

    name = "email"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        recipients: list[str],
        username: str = "",
        password: str = "",
        security: str = "starttls",
        max_attempts: int = 2,
        retry_delay: float = 5.0,
        smtp_factory: Callable[..., Any] | None = None,
        smtp_ssl_factory: Callable[..., Any] | None = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        if not host or not sender or not recipients:
            raise ValueError("smtp host, sender and at least one recipient are required")
        if security not in ("starttls", "ssl", "none"):
            raise ValueError(f"smtp security must be starttls, ssl or none, got {security!r}")
        self._host, self._port = host, port
        self._sender, self._recipients = sender, recipients
        self._username, self._password = username, password
        self._security = security
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay
        self._smtp = smtp_factory or smtplib.SMTP
        self._smtp_ssl = smtp_ssl_factory or smtplib.SMTP_SSL
        self._sleep = sleep

    def _message(self, subject: str, body: str) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = f"[trdex] {subject}"
        msg["From"] = self._sender
        msg["To"] = ", ".join(self._recipients)
        msg.set_content(body)
        return msg

    def _send_sync(self, msg: EmailMessage) -> None:
        ctx = ssl.create_default_context()
        if self._security == "ssl":
            server = self._smtp_ssl(self._host, self._port, timeout=20, context=ctx)
        else:
            server = self._smtp(self._host, self._port, timeout=20)
        with server as s:
            if self._security == "starttls":
                s.starttls(context=ctx)
            if self._username:
                s.login(self._username, self._password)
            s.send_message(msg)

    async def send(self, subject: str, body: str) -> None:
        msg = self._message(subject, body)
        last = ""
        for attempt in range(self._max_attempts):
            try:
                await asyncio.to_thread(self._send_sync, msg)
                return
            except (OSError, smtplib.SMTPException) as exc:
                last = f"{type(exc).__name__}: {exc}"
                if isinstance(exc, smtplib.SMTPAuthenticationError):
                    break  # wrong credentials will not fix themselves
            if attempt < self._max_attempts - 1:
                await self._sleep(self._retry_delay)
        raise NotificationError(_redact(f"email: {last}", self._password))
