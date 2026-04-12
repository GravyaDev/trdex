"""Leave specific Telegram channels by chat_id.

Usage:
    # Leave specific channels by chat_id:
    python scripts/telegram_leave_channels.py -1001312615047 -1001169143349

    # Leave all channels listed in a file (one chat_id per line):
    python scripts/telegram_leave_channels.py --file channels_to_leave.txt

    # Dry run — show what would be left without actually leaving:
    python scripts/telegram_leave_channels.py --dry-run -1001312615047

Run from the production container after Telethon login.
"""

from __future__ import annotations

import asyncio
import sys

from trdex.config import get_settings


async def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(
            "Usage: telegram_leave_channels.py [--dry-run] [--file FILE] <chat_id> [chat_id ...]",
            file=sys.stderr,
        )
        sys.exit(2)

    dry_run = "--dry-run" in args
    if dry_run:
        args.remove("--dry-run")

    chat_ids: list[int] = []
    if "--file" in args:
        idx = args.index("--file")
        if idx + 1 >= len(args):
            print("--file requires a filename", file=sys.stderr)
            sys.exit(2)
        filepath = args[idx + 1]
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    chat_ids.append(int(line))
        args = [a for i, a in enumerate(args) if i != idx and i != idx + 1]

    for a in args:
        try:
            chat_ids.append(int(a))
        except ValueError:
            print(f"Skipping non-numeric argument: {a}", file=sys.stderr)

    if not chat_ids:
        print("No chat_ids to leave.", file=sys.stderr)
        sys.exit(2)

    from telethon import TelegramClient  # type: ignore[import-untyped]
    from telethon.tl.functions.channels import LeaveChannelRequest  # type: ignore[import-untyped]

    s = get_settings()
    client = TelegramClient(
        "session/trdex_telegram", s.telegram_api_id, s.telegram_api_hash,
    )
    await client.start(phone=s.telegram_phone)

    for cid in chat_ids:
        try:
            entity = await client.get_entity(cid)
            title = getattr(entity, "title", str(cid))
            if dry_run:
                print(f"[DRY RUN] Would leave: {title} ({cid})")
            else:
                await client(LeaveChannelRequest(entity))
                print(f"Left: {title} ({cid})")
        except Exception as exc:
            print(f"Error leaving {cid}: {exc}", file=sys.stderr)

    await client.disconnect()

    if dry_run:
        print(f"\nDry run complete. {len(chat_ids)} channels would be left.")
    else:
        print(f"\nDone. Left {len(chat_ids)} channels.")


if __name__ == "__main__":
    asyncio.run(main())
