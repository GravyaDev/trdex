"""TelegramMonitor: reads messages from public groups and emits parsed signals."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from trdex.telegram.parser import TelegramSignal, parse_signal

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


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
        session_name: str = "trdex_telegram",
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
        for channel in channels:
            try:
                entity = await self._client.get_entity(channel)
                messages = await self._client.get_messages(entity, limit=limit)
                for msg in messages:
                    if not msg.text:
                        continue
                    sig = parse_signal(msg.text, source=channel)
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

        Registers a Telethon event handler for new messages.
        """
        from telethon import events  # type: ignore[import-untyped]

        queue: list[TelegramSignal] = []

        @self._client.on(events.NewMessage(chats=channels))
        async def _handler(event):
            if not event.message.text:
                return
            sig = parse_signal(event.message.text, source=str(event.chat_id))
            if sig:
                queue.append(sig)
                logger.info(
                    "[TelegramMonitor] new signal %s %s", sig.direction, sig.symbol
                )

        while self._running:
            if queue:
                yield queue.pop(0)
            else:
                import asyncio
                await asyncio.sleep(0.5)
