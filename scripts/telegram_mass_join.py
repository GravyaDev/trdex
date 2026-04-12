"""Mass-join Telegram channels and dump their recent messages.

Usage:
    python scripts/telegram_mass_join.py channels_to_join.txt

Input file: one entry per line. Accepts:
    @username
    https://t.me/username
    https://t.me/+invitehash
    t.me/username

Lines starting with # are comments. Empty lines are skipped.

For each channel:
  1. Attempts to join (skips if already a member)
  2. Fetches the last 20 messages
  3. Appends to the output JSON

Output: telegram_mass_join_dump.json in the current directory.
Includes a per-channel summary at the end.

IMPORTANT: Telegram rate-limits joins aggressively. The script
waits 8 seconds between each join to avoid FloodWait bans. For
170 channels this takes ~23 minutes. Do not interrupt — a partial
dump is written on any error so progress is not lost.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import timezone
from pathlib import Path

from trdex.config import get_settings

JOIN_DELAY_SECONDS = 8
MESSAGES_PER_CHANNEL = 20
OUTPUT_FILE = "telegram_mass_join_dump.json"


def _parse_input(line: str) -> str | None:
    """Extract a joinable identifier from a line.

    Returns @username, invite hash, or None if unparseable.
    """
    s = line.strip()
    if not s or s.startswith("#"):
        return None

    # Strip markdown table formatting if present
    if "|" in s:
        # Try to extract @handle from table columns
        for part in s.split("|"):
            part = part.strip()
            if part.startswith("@"):
                return part.split()[0]  # take just the @handle, ignore trailing text
            for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
                if part.startswith(prefix):
                    rest = part[len(prefix):]
                    if rest.startswith("+"):
                        return rest  # invite hash
                    return f"@{rest.split()[0]}"
        return None

    # Direct formats
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if s.startswith(prefix):
            rest = s[len(prefix):]
            if rest.startswith("+"):
                return rest  # invite hash for ImportChatInviteRequest
            return f"@{rest}"

    if s.startswith("@"):
        return s.split()[0]  # @handle, ignore trailing text

    return None


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: telegram_mass_join.py <channels_file>", file=sys.stderr)
        sys.exit(2)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Parse all identifiers from the input file
    raw_lines = input_path.read_text(encoding="utf-8").splitlines()
    identifiers: list[str] = []
    seen: set[str] = set()
    for line in raw_lines:
        ident = _parse_input(line)
        if ident and ident.lower() not in seen:
            identifiers.append(ident)
            seen.add(ident.lower())

    print(f"Parsed {len(identifiers)} unique channels from {input_path}")
    if not identifiers:
        print("No channels found. Check the file format.", file=sys.stderr)
        sys.exit(2)

    from telethon import TelegramClient  # type: ignore[import-untyped]
    from telethon.tl.functions.channels import JoinChannelRequest  # type: ignore[import-untyped]
    from telethon.tl.functions.messages import (  # type: ignore[import-untyped]
        ImportChatInviteRequest,
        CheckChatInviteRequest,
    )
    from telethon.tl.types import ChatInviteAlready  # type: ignore[import-untyped]
    from telethon.tl.functions.account import (  # type: ignore[import-untyped]
        UpdateNotifySettingsRequest,
    )
    from telethon.tl.types import (  # type: ignore[import-untyped]
        InputPeerNotifySettings,
        InputNotifyPeer,
    )
    from telethon.errors import (  # type: ignore[import-untyped]
        FloodWaitError,
        ChannelPrivateError,
        UserAlreadyParticipantError,
        InviteHashExpiredError,
    )

    from telethon.tl.functions.folders import (  # type: ignore[import-untyped]
        EditPeerFoldersRequest,
    )
    from telethon.tl.types import InputFolderPeer  # type: ignore[import-untyped]

    async def _mute_and_archive(client, entity) -> None:
        """Mute + archive a channel so it doesn't flood the phone.

        Archived channels still deliver messages to Telethon's
        NewMessage handler — archive is UI-only, the MTProto
        stream is unaffected.
        """
        try:
            input_entity = await client.get_input_entity(entity)
            # Mute forever
            await client(UpdateNotifySettingsRequest(
                peer=InputNotifyPeer(peer=input_entity),
                settings=InputPeerNotifySettings(
                    mute_until=2147483647,  # max int32 = forever
                ),
            ))
            # Archive (folder_id=1 = Archived)
            await client(EditPeerFoldersRequest(
                folder_peers=[InputFolderPeer(
                    peer=input_entity,
                    folder_id=1,
                )]
            ))
        except Exception:
            pass  # best-effort

    s = get_settings()
    client = TelegramClient(
        "session/trdex_telegram", s.telegram_api_id, s.telegram_api_hash,
    )
    await client.start(phone=s.telegram_phone)
    me = await client.get_me()
    print(f"Logged in as: {me.first_name} (@{me.username})\n")

    dump: dict[str, dict] = {}
    stats = {"joined": 0, "already": 0, "failed": 0, "dumped": 0}

    for i, ident in enumerate(identifiers, 1):
        label = f"[{i}/{len(identifiers)}]"

        # --- Join ---
        try:
            if ident.startswith("+") or (not ident.startswith("@") and len(ident) > 10):
                # Invite hash
                invite_hash = ident.lstrip("+")
                try:
                    check = await client(CheckChatInviteRequest(hash=invite_hash))
                    if isinstance(check, ChatInviteAlready):
                        print(f"{label} Already in: {getattr(check.chat, 'title', ident)}")
                        entity = check.chat
                        stats["already"] += 1
                    else:
                        updates = await client(ImportChatInviteRequest(hash=invite_hash))
                        entity = updates.chats[0] if updates.chats else None
                        if entity:
                            print(f"{label} Joined: {getattr(entity, 'title', ident)}")
                            stats["joined"] += 1
                        else:
                            print(f"{label} Joined but no entity returned: {ident}")
                            stats["joined"] += 1
                            continue
                except InviteHashExpiredError:
                    print(f"{label} SKIP (invite expired): {ident}")
                    stats["failed"] += 1
                    continue
            else:
                # @username — try to join directly
                username = ident.lstrip("@")
                try:
                    entity = await client.get_entity(username)
                    # Check if already a participant by trying to get messages
                    try:
                        await client(JoinChannelRequest(entity))
                        print(f"{label} Joined: {getattr(entity, 'title', ident)}")
                        stats["joined"] += 1
                    except UserAlreadyParticipantError:
                        print(f"{label} Already in: {getattr(entity, 'title', ident)}")
                        stats["already"] += 1
                except ChannelPrivateError:
                    print(f"{label} SKIP (private/banned): {ident}")
                    stats["failed"] += 1
                    continue
                except ValueError:
                    print(f"{label} SKIP (not found): {ident}")
                    stats["failed"] += 1
                    continue

        except FloodWaitError as e:
            wait = e.seconds + 5
            print(f"{label} FloodWait! Sleeping {wait}s...")
            await asyncio.sleep(wait)
            # Retry once after waiting
            try:
                username = ident.lstrip("@")
                entity = await client.get_entity(username)
                await client(JoinChannelRequest(entity))
                print(f"{label} Joined (after wait): {getattr(entity, 'title', ident)}")
                stats["joined"] += 1
            except Exception as retry_exc:
                print(f"{label} FAIL (after FloodWait retry): {ident}: {retry_exc}")
                stats["failed"] += 1
                continue
        except Exception as exc:
            print(f"{label} FAIL: {ident}: {exc}")
            stats["failed"] += 1
            continue

        # --- Mute + Archive ---
        await _mute_and_archive(client, entity)

        # --- Dump messages ---
        try:
            messages = await client.get_messages(entity, limit=MESSAGES_PER_CHANNEL)
            chat_id = str(getattr(entity, "id", ident))
            # Prefix with -100 for channels/supergroups
            if getattr(entity, "broadcast", False) or getattr(entity, "megagroup", False):
                raw_id = entity.id
                full_id = f"-100{raw_id}"
            else:
                full_id = chat_id

            messages_data = []
            for msg in messages:
                dt = msg.date
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                messages_data.append({
                    "id": msg.id,
                    "date": dt.isoformat() if dt else None,
                    "text": msg.text,
                })

            dump[full_id] = {
                "title": getattr(entity, "title", str(ident)),
                "username": f"@{getattr(entity, 'username', '')}" if getattr(entity, "username", None) else None,
                "messages": messages_data,
            }
            stats["dumped"] += 1
        except Exception as exc:
            print(f"{label} Dump failed for {ident}: {exc}")

        # Save progress incrementally
        if i % 10 == 0:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(dump, f, ensure_ascii=False, indent=2)
            print(f"  ... progress saved ({len(dump)} channels)")

        # Delay between joins to avoid FloodWait
        if i < len(identifiers):
            await asyncio.sleep(JOIN_DELAY_SECONDS)

    # Final save
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=2)

    await client.disconnect()

    print(f"\n{'='*60}")
    print(f"Done. {len(dump)} channels dumped to {OUTPUT_FILE}")
    print(f"  Joined:  {stats['joined']}")
    print(f"  Already: {stats['already']}")
    print(f"  Failed:  {stats['failed']}")
    print(f"  Dumped:  {stats['dumped']}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
