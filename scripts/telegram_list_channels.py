"""List every Telegram chat your user account is joined to.

Use this after running `telegram_login.py` to discover the numeric
chat_id of private channels (where `@username` lookups do not work
and forward-to-@userinfobot is blocked by channel settings).

Run from the project root:

    .venv/Scripts/python.exe scripts/telegram_list_channels.py

Or from a running production container:

    docker exec <app-container> \
        /app/.venv/bin/python scripts/telegram_list_channels.py

For each dialog it prints:

    <chat_id>  <kind>  [<@username>]  <title>

Copy the chat_id column into the `telegram_channels` Runtime Config
entry as a comma-separated list. Private channels will be negative
numbers (typically starting with `-100`); public channels/groups
you can reference either by id or by @username.
"""

from __future__ import annotations

import asyncio

from trdex.config import get_settings


async def main() -> None:
    from telethon import TelegramClient  # type: ignore[import-untyped]

    s = get_settings()
    client = TelegramClient(
        "trdex_telegram", s.telegram_api_id, s.telegram_api_hash,
    )
    await client.start(phone=s.telegram_phone)
    me = await client.get_me()
    print(f"Logged in as: {me.first_name} (@{me.username})\n")

    rows: list[tuple[int, str, str, str]] = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if getattr(entity, "broadcast", False):
            kind = "channel"
        elif getattr(entity, "megagroup", False):
            kind = "supergroup"
        elif getattr(entity, "gigagroup", False):
            kind = "broadcast_group"
        elif dialog.is_group:
            kind = "group"
        elif dialog.is_user:
            kind = "dm"
        else:
            kind = "chat"

        username = getattr(entity, "username", None)
        uname_col = f"@{username}" if username else ""
        rows.append((dialog.id, kind, uname_col, dialog.name or ""))

    rows.sort(key=lambda r: (r[1], r[3].lower()))

    id_w = max(len(str(r[0])) for r in rows) if rows else 10
    kind_w = max(len(r[1]) for r in rows) if rows else 10
    uname_w = max(len(r[2]) for r in rows) if rows else 10

    print(
        f"{'chat_id':>{id_w}}  {'kind':<{kind_w}}  "
        f"{'username':<{uname_w}}  title"
    )
    print("-" * (id_w + kind_w + uname_w + 20))
    for chat_id, kind, uname, title in rows:
        print(
            f"{chat_id:>{id_w}}  {kind:<{kind_w}}  "
            f"{uname:<{uname_w}}  {title}"
        )

    print(f"\nTotal: {len(rows)} dialogs")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
