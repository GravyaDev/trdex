"""Dump the last N messages from all joined channels to a JSON file.

Usage:
    docker exec <app-container> \
        /app/.venv/bin/python scripts/telegram_dump_channels.py

Output: writes `telegram_channel_dump.json` in the working directory
with structure:
    {
        "<chat_id>": {
            "title": "...",
            "username": "@..." or null,
            "messages": [
                {"id": 123, "date": "2026-04-12T10:00:00+00:00", "text": "..."},
                ...
            ]
        },
        ...
    }

Only channels (broadcast=True) are included. DMs, groups, and
supergroups are skipped. Messages without text (images-only,
service messages) are included with text=null so you can see
the ratio of parseable vs non-parseable content.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timezone

from trdex.config import get_settings

MESSAGES_PER_CHANNEL = 30


async def main() -> None:
    from telethon import TelegramClient  # type: ignore[import-untyped]

    s = get_settings()
    client = TelegramClient(
        "trdex_telegram", s.telegram_api_id, s.telegram_api_hash,
    )
    await client.start(phone=s.telegram_phone)
    me = await client.get_me()
    print(f"Logged in as: {me.first_name} (@{me.username})\n")

    dump: dict[str, dict] = {}

    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if not getattr(entity, "broadcast", False):
            continue

        chat_id = str(dialog.id)
        username = getattr(entity, "username", None)
        title = dialog.name or ""

        print(f"Fetching {MESSAGES_PER_CHANNEL} msgs from {title} ({chat_id})...")

        messages_data = []
        try:
            messages = await client.get_messages(entity, limit=MESSAGES_PER_CHANNEL)
            for msg in messages:
                dt = msg.date
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                messages_data.append({
                    "id": msg.id,
                    "date": dt.isoformat() if dt else None,
                    "text": msg.text,
                })
        except Exception as exc:
            print(f"  ERROR: {exc}")
            messages_data = [{"error": str(exc)}]

        dump[chat_id] = {
            "title": title,
            "username": f"@{username}" if username else None,
            "messages": messages_data,
        }

    out_path = "telegram_channel_dump.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=2)

    print(f"\nDone. {len(dump)} channels dumped to {out_path}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
