"""Join a private Telegram channel from an invite link.

Usage:
    .venv/Scripts/python.exe scripts/telegram_join_channel.py <invite-link-or-hash>

Accepts any of:
    https://t.me/+abcDEF123
    t.me/+abcDEF123
    +abcDEF123
    abcDEF123            (bare hash)

After joining, prints the resolved chat_id so you can paste it
directly into `telegram_channels` in the dashboard Runtime Config.

Requires the Telethon session file to already exist — run
`telegram_login.py` first.
"""

from __future__ import annotations

import asyncio
import sys

from trdex.config import get_settings


def _extract_hash(arg: str) -> str:
    """Pull the invite hash out of any reasonable input form."""
    s = arg.strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    if s.startswith("+"):
        s = s[1:]
    return s


async def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: telegram_join_channel.py <invite-link-or-hash>",
            file=sys.stderr,
        )
        sys.exit(2)

    invite_hash = _extract_hash(sys.argv[1])
    if not invite_hash:
        print("Error: could not parse invite link.", file=sys.stderr)
        sys.exit(2)

    from telethon import TelegramClient  # type: ignore[import-untyped]
    from telethon.tl.functions.messages import (  # type: ignore[import-untyped]
        ImportChatInviteRequest,
        CheckChatInviteRequest,
    )
    from telethon.tl.types import (  # type: ignore[import-untyped]
        ChatInvite,
        ChatInviteAlready,
    )

    s = get_settings()
    client = TelegramClient(
        "trdex_telegram", s.telegram_api_id, s.telegram_api_hash,
    )
    await client.start(phone=s.telegram_phone)

    # First check if the invite is valid / already joined — this
    # gives a clean error message instead of a Telethon exception.
    try:
        check = await client(CheckChatInviteRequest(hash=invite_hash))
    except Exception as exc:
        print(f"Error: invalid invite link: {exc}", file=sys.stderr)
        await client.disconnect()
        sys.exit(1)

    if isinstance(check, ChatInviteAlready):
        chat = check.chat
        print(f"Already a member of: {getattr(chat, 'title', chat.id)}")
        print(f"chat_id: {-1_000_000_000_000 - chat.id if chat.id > 0 else chat.id}")
        await client.disconnect()
        return

    if isinstance(check, ChatInvite):
        print(
            f"About to join: {check.title} "
            f"(participants={check.participants_count}, "
            f"channel={check.channel}, broadcast={check.broadcast})"
        )

    # Actually join
    try:
        updates = await client(ImportChatInviteRequest(hash=invite_hash))
    except Exception as exc:
        print(f"Error: failed to join: {exc}", file=sys.stderr)
        await client.disconnect()
        sys.exit(1)

    # The returned Updates payload contains the new chat entity
    chats = getattr(updates, "chats", []) or []
    if not chats:
        print(
            "Joined but no chat entity returned — run "
            "telegram_list_channels.py to find the id.",
        )
        await client.disconnect()
        return

    chat = chats[0]
    raw_id = chat.id
    # For channels/supergroups the peer id needs the -100 prefix
    # when used as a chat_id against Telegram Bot/MT APIs.
    if getattr(chat, "broadcast", False) or getattr(chat, "megagroup", False):
        full_id = int(f"-100{raw_id}")
    else:
        full_id = raw_id

    print(f"Joined: {getattr(chat, 'title', raw_id)}")
    print(f"chat_id: {full_id}")
    print(
        "\nPaste this id into the dashboard: "
        "Settings -> API Keys -> telegram_channels",
    )
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
