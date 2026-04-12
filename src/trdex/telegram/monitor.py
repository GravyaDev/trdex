"""TelegramMonitor: reads messages from Telegram channels.

Provides two streaming modes:
- stream(): yields TelegramSignal (parsed signals only, backward compat)
- stream_raw(): yields TelegramMessage (ALL text messages, for the
  background task to classify as signal vs news)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from trdex.telegram.parser import TelegramSignal, parse_signal

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class TelegramMessage:
    """A raw message from a Telegram channel, before parsing."""

    chat_id: str
    text: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


class TelegramMonitor:
    """Monitors Telegram public groups/channels for trading signals.

    Uses Telethon (user account, not bot) to read messages from public channels.
    Requires TELEGRAM_API_ID and TELEGRAM_API_HASH from my.telegram.org.

    Usage:
        monitor = TelegramMonitor(api_id=..., api_hash=..., phone=...)
        await monitor.start()
        async for signal in monitor.stream(["@channel1", "@channel2"]):
            print(signal)
        await monitor.stop()
    """

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        phone: str,
        session_name: str = "session/trdex_telegram",
    ) -> None:
        # Lazy import — telethon is optional, only needed when monitor is used
        from telethon import TelegramClient  # type: ignore[import-untyped]

        self._client = TelegramClient(session_name, api_id, api_hash)
        self._phone = phone
        self._running = False

    async def start(self) -> None:
        """Connect and authenticate."""
        await self._client.start(phone=self._phone)
        self._running = True
        logger.info("[TelegramMonitor] connected")

    async def stop(self) -> None:
        """Disconnect."""
        self._running = False
        await self._client.disconnect()
        logger.info("[TelegramMonitor] disconnected")

    async def __aenter__(self) -> "TelegramMonitor":
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()

    @staticmethod
    def _normalize_channels(channels: list[str]) -> list:
        """Coerce channel identifiers into the types Telethon expects.

        Username strings (`@foo` or bare `foo`) stay strings. Numeric
        chat ids (typically `-100...` for channels/supergroups) must
        be passed as Python int — Telethon's NewMessage filter treats
        any str as a username and fails to resolve negative numbers.
        """
        out: list = []
        for ch in channels:
            s = ch.strip()
            if not s:
                continue
            # Accept plain int ("-1001234567890") or signed-int-like
            if s.lstrip("-").isdigit():
                out.append(int(s))
            else:
                out.append(s)
        return out

    async def fetch_recent(
        self,
        channels: list[str],
        limit: int = 20,
    ) -> list[TelegramSignal]:
        """Fetch the last N messages from each channel and parse signals.

        Args:
            channels: List of channel usernames, e.g. ["@cryptosignals", "@btcalerts"]
            limit: Max messages to fetch per channel.

        Returns:
            List of parsed TelegramSignal (only messages that contain valid signals).
        """
        signals: list[TelegramSignal] = []
        for channel in self._normalize_channels(channels):
            try:
                entity = await self._client.get_entity(channel)
                messages = await self._client.get_messages(entity, limit=limit)
                for msg in messages:
                    if not msg.text:
                        continue
                    sig = parse_signal(msg.text, source=str(channel))
                    if sig:
                        signals.append(sig)
                        logger.info(
                            "[TelegramMonitor] signal %s %s from %s",
                            sig.direction, sig.symbol, channel,
                        )
            except Exception as exc:
                logger.warning("[TelegramMonitor] error reading %s: %s", channel, exc)
        return signals

    async def stream(
        self,
        channels: list[str],
    ) -> AsyncIterator[TelegramSignal]:
        """Real-time stream: yields new signals as messages arrive.

        Registers a Telethon event handler for new messages. Uses asyncio.Queue
        for backpressure-safe, non-blocking signal delivery.
        """
        from telethon import events  # type: ignore[import-untyped]

        queue: asyncio.Queue[TelegramSignal] = asyncio.Queue()
        normalized = self._normalize_channels(channels)

        @self._client.on(events.NewMessage(chats=normalized))
        async def _handler(event) -> None:
            try:
                if not event.message.text:
                    return
                sig = parse_signal(event.message.text, source=str(event.chat_id))
                if sig:
                    await queue.put(sig)
                    logger.info(
                        "[TelegramMonitor] new signal %s %s", sig.direction, sig.symbol
                    )
            except Exception:
                logger.exception("[TelegramMonitor] error in message handler")

        while self._running:
            try:
                sig = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield sig
                queue.task_done()
            except asyncio.TimeoutError:
                continue

    async def stream_raw(
        self,
        channels: list[str],
    ) -> AsyncIterator[TelegramMessage]:
        """Stream ALL text messages from channels as raw TelegramMessage.

        Unlike stream() which pre-filters through parse_signal, this
        yields every text message. The caller decides what to do:
        parse_signal for trading signals, or ingest as news context.
        """
        from telethon import events  # type: ignore[import-untyped]

        queue: asyncio.Queue[TelegramMessage] = asyncio.Queue()
        normalized = self._normalize_channels(channels)

        @self._client.on(events.NewMessage(chats=normalized))
        async def _handler(event) -> None:
            try:
                if not event.message.text:
                    return
                dt = event.message.date
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                msg = TelegramMessage(
                    chat_id=str(event.chat_id),
                    text=event.message.text,
                    timestamp=dt or datetime.now(tz=timezone.utc),
                )
                await queue.put(msg)
            except Exception:
                logger.exception("[TelegramMonitor] error in raw handler")

        while self._running:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield msg
                queue.task_done()
            except asyncio.TimeoutError:
                continue
