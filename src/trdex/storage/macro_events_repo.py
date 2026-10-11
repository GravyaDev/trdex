"""Repository for ``macro_events`` (economic calendar, migration 016)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from trdex.market.macro_calendar import MacroEvent


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


class MacroEventsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_window(
        self, source: str, events: list[MacroEvent], fetched_at: datetime
    ) -> int:
        """Replace ``source`` rows inside the fetched window with ``events``.

        The window spans the first to the last fetched event, so moved or
        cancelled events of that week disappear while earlier weeks stay.
        One transaction: readers never see a half-replaced week.
        """
        if not events:
            return 0
        start = min(e.time for e in events) - timedelta(minutes=1)
        end = max(e.time for e in events) + timedelta(minutes=1)
        await self._session.execute(
            text(
                "DELETE FROM macro_events WHERE source = :source "
                "AND event_time BETWEEN :start AND :end"
            ),
            {"source": source, "start": start, "end": end},
        )
        await self._session.execute(
            text(
                "INSERT INTO macro_events "
                "(source, currency, title, event_time, impact, forecast, previous, fetched_at) "
                "VALUES (:source, :currency, :title, :event_time, :impact, :forecast, "
                ":previous, :fetched_at) "
                "ON CONFLICT ON CONSTRAINT uq_macro_events DO UPDATE SET "
                "impact = EXCLUDED.impact, forecast = EXCLUDED.forecast, "
                "previous = EXCLUDED.previous, fetched_at = EXCLUDED.fetched_at"
            ),
            [
                {
                    "source": source,
                    "currency": e.currency,
                    "title": e.title,
                    "event_time": e.time,
                    "impact": e.impact,
                    "forecast": e.forecast,
                    "previous": e.previous,
                    "fetched_at": _aware(fetched_at),
                }
                for e in events
            ],
        )
        await self._session.commit()
        return len(events)

    async def between(self, source: str, start: datetime, end: datetime) -> list[MacroEvent]:
        from trdex.market.macro_calendar import MacroEvent

        rows = (
            await self._session.execute(
                text(
                    "SELECT currency, title, event_time, impact, forecast, previous "
                    "FROM macro_events WHERE source = :source "
                    "AND event_time BETWEEN :start AND :end ORDER BY event_time"
                ),
                {"source": source, "start": _aware(start), "end": _aware(end)},
            )
        ).all()
        return [
            MacroEvent(
                currency=r[0],
                title=r[1],
                time=_aware(r[2]),
                impact=r[3],
                forecast=r[4],
                previous=r[5],
            )
            for r in rows
        ]

    async def last_fetched(self, source: str) -> datetime | None:
        value = (
            await self._session.execute(
                text("SELECT MAX(fetched_at) FROM macro_events WHERE source = :source"),
                {"source": source},
            )
        ).scalar()
        return _aware(value) if value is not None else None
