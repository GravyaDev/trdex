"""One-time backfill: replace numeric chat_ids in signal_outcomes.source with channel names.

Reads all dialogs from Telethon, builds a chat_id → title map, then updates
every signal_outcomes row where source is a numeric id (positive or negative).
Run once after deploying the monitor.py fix that stores names going forward.

Run from the project root:

    .venv/Scripts/python.exe scripts/backfill_signal_sources.py

Or from a running production container:

    docker exec <app-container> \
        /app/.venv/bin/python scripts/backfill_signal_sources.py

Idempotent: rows already containing a non-numeric source are not touched.
"""

from __future__ import annotations

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _is_numeric_source(s: str) -> bool:
    """Return True if source looks like a raw chat_id (e.g. '-1001234567890')."""
    return s.lstrip("-").isdigit()


async def main() -> None:
    from telethon import TelegramClient  # type: ignore[import-untyped]

    from trdex.config import get_settings
    from trdex.storage.db import get_session_factory
    async_session_factory = get_session_factory()
    from trdex.storage.signal_outcome_models import SignalOutcomeRecord
    from sqlalchemy import select, update

    s = get_settings()

    # ── Build chat_id → title map from Telethon ──────────────────────────────
    client = TelegramClient(
        "session/trdex_telegram", s.telegram_api_id, s.telegram_api_hash,
    )
    await client.start(phone=s.telegram_phone)

    id_to_name: dict[str, str] = {}
    async for dialog in client.iter_dialogs():
        title = dialog.name or ""
        if title:
            id_to_name[str(dialog.id)] = title
            logger.info("  %s → %s", dialog.id, title)

    await client.disconnect()
    logger.info("Built map: %d channels", len(id_to_name))

    if not id_to_name:
        logger.warning("No channels found — nothing to update.")
        return

    # ── Update DB rows ────────────────────────────────────────────────────────
    async with async_session_factory() as session:
        result = await session.execute(select(SignalOutcomeRecord))
        records = list(result.scalars().all())

        updated = 0
        for rec in records:
            if not _is_numeric_source(rec.source):
                continue  # already has a name, skip
            name = id_to_name.get(rec.source)
            if name:
                rec.source = name
                updated += 1
                logger.info("  id=%d  %s → %s", rec.id, rec.source, name)
            else:
                logger.warning(
                    "  id=%d  source=%s not in dialog list — left unchanged",
                    rec.id, rec.source,
                )

        await session.commit()
        logger.info("Done — updated %d / %d records.", updated, len(records))


if __name__ == "__main__":
    asyncio.run(main())
