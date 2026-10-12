"""Economic calendar and the macro entry gate.

High-impact releases (FOMC, CPI, NFP, ...) move crypto with gaps and
spikes that stops do not survive well. The gate blocks new entries from
``before`` minutes ahead of such an event to ``after`` minutes past it;
exits are never blocked.

Source: Forex Factory's public weekly JSON (no key). It is fetched at
most every ``REFRESH_EVERY`` and retried no sooner than ``RETRY_AFTER``
after a failure (the feed asks for a light touch), through a
``RateLimiter`` with bounded retries that honours ``Retry-After``. A
payload that is empty or covers another week is a failure, not "no
events". Each successful fetch replaces that week's rows (Sunday to
Sunday UTC) in ``macro_events``; earlier weeks stay, so the table builds
up a history a future backtest can replay.

Fail-closed like the regime gate: in live mode a calendar older than
``stale_after`` blocks entries (we cannot tell whether an event is
near); in simulation it switches the gate off. Staleness is notified.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from trdex.market.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

SOURCE = "forexfactory"
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
REFRESH_EVERY = timedelta(hours=6)
RETRY_AFTER = timedelta(hours=1)
NOTIFY_EVERY = timedelta(hours=24)
IMPACTS = ("High", "Medium", "Low", "Holiday")
MAX_WINDOW_MIN = 24 * 60  # longest before/after window accepted from config
FETCH_ATTEMPTS = 3
MAX_RETRY_AFTER = 300.0  # seconds; a longer Retry-After waits for RETRY_AFTER instead


@dataclass(frozen=True)
class MacroEvent:
    currency: str
    title: str
    time: datetime  # aware UTC
    impact: str
    forecast: str | None = None
    previous: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "title": self.title,
            "time": self.time.isoformat(),
            "impact": self.impact,
            "forecast": self.forecast,
            "previous": self.previous,
        }


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def parse_ff(payload: Any) -> list[MacroEvent]:
    """Forex Factory weekly JSON -> events. Malformed rows are skipped."""
    if not isinstance(payload, list):
        raise ValueError("calendar payload is not a list")
    out: list[MacroEvent] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            when = datetime.fromisoformat(str(row["date"]))
            if when.tzinfo is None:
                continue  # a time without zone cannot be placed safely
            impact = str(row.get("impact") or "")
            if impact not in IMPACTS:
                continue
            out.append(
                MacroEvent(
                    currency=str(row["country"]).strip().upper(),
                    title=str(row["title"]).strip(),
                    time=when.astimezone(UTC),
                    impact=impact,
                    forecast=(str(row.get("forecast") or "").strip() or None),
                    previous=(str(row.get("previous") or "").strip() or None),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    if not payload:
        raise ValueError("calendar payload is empty")
    if not out:
        raise ValueError("calendar payload has no parsable events")
    return sorted(out, key=lambda e: e.time)


def week_window(events: list[MacroEvent]) -> tuple[datetime, datetime]:
    """[Sunday 00:00, next Sunday 00:00) UTC around the payload's week.

    The week is the one of the median event (Forex Factory weeks run
    Sunday to Saturday in New York, so a few Sunday-evening events fall
    on Sunday UTC). Raises on an empty list.
    """
    if not events:
        raise ValueError("no events")
    mid = sorted(e.time for e in events)[len(events) // 2]
    monday = datetime(mid.year, mid.month, mid.day, tzinfo=UTC) - timedelta(days=mid.weekday())
    return monday - timedelta(days=1), monday + timedelta(days=6)


# ── gate ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MacroGateConfig:
    enabled: bool = True
    before: timedelta = timedelta(minutes=30)
    after: timedelta = timedelta(minutes=60)
    impacts: frozenset[str] = frozenset({"High"})
    currencies: frozenset[str] | None = frozenset({"USD"})  # None = all
    stale_after: timedelta = timedelta(hours=24)

    def matches(self, event: MacroEvent) -> bool:
        return event.impact in self.impacts and (
            self.currencies is None or event.currency in self.currencies
        )


def _csv_set(raw: Any, default: frozenset[str]) -> frozenset[str] | None:
    text = str(raw or "").strip()
    if not text:
        return default
    if text.upper() == "ALL":
        return None
    return frozenset(p.strip() for p in text.split(",") if p.strip())


def macro_gate_config(cfg: Any) -> MacroGateConfig:
    """Gate settings from Runtime Config (thresholds.macro_gate_*), defaults otherwise.

    Raises ValueError on nonsense (negative window, unknown impact): the
    caller blocks, as for the other gates.
    """
    base = MacroGateConfig()
    if cfg is None:
        return base

    def minutes(key: str, default: timedelta) -> timedelta:
        raw = str(cfg.get("thresholds", key, "") or "").strip()
        if not raw:
            return default
        value = float(raw)
        if not 0 <= value <= MAX_WINDOW_MIN:  # also rejects nan / inf
            raise ValueError(f"{key} must be between 0 and {MAX_WINDOW_MIN} minutes, got {raw}")
        return timedelta(minutes=value)

    impacts = _csv_set(cfg.get("thresholds", "macro_gate_impacts", ""), base.impacts)
    if impacts is None:
        impacts = frozenset(IMPACTS)
    unknown = {i for i in impacts if i not in IMPACTS}
    if unknown:
        raise ValueError(f"unknown macro_gate_impacts {sorted(unknown)}; use {IMPACTS}")
    currencies = _csv_set(cfg.get("thresholds", "macro_gate_currencies", ""), frozenset({"USD"}))
    if currencies is not None:
        currencies = frozenset(c.upper() for c in currencies)
    enabled_raw = str(cfg.get("thresholds", "macro_gate_enabled", "") or "").strip().lower()
    return MacroGateConfig(
        enabled=enabled_raw not in ("false", "0", "no", "off"),
        before=minutes("macro_gate_before_min", base.before),
        after=minutes("macro_gate_after_min", base.after),
        impacts=impacts,
        currencies=currencies,
    )


def macro_block_reason(
    events: Iterable[MacroEvent],
    now: datetime,
    cfg: MacroGateConfig,
    *,
    last_success: datetime | None,
    live: bool,
) -> str | None:
    """Why a new entry must wait, or None. Pure."""
    if not cfg.enabled:
        return None
    now = _utc(now)
    if last_success is None or now - _utc(last_success) > cfg.stale_after:
        if not live:
            return None  # simulation keeps collecting data
        since = (
            "never" if last_success is None else f"since {_utc(last_success):%Y-%m-%d %H:%M} UTC"
        )
        return f"economic calendar unavailable ({since}) — live entries wait (fail-closed)"
    for e in events:
        if cfg.matches(e) and e.time - cfg.before <= now <= e.time + cfg.after:
            return (
                f"{e.currency} {e.title} ({e.impact}) at {e.time:%Y-%m-%d %H:%M} UTC — "
                f"no new entries from {int(cfg.before.total_seconds() // 60)} min before "
                f"to {int(cfg.after.total_seconds() // 60)} min after"
            )
    return None


# ── calendar service ──────────────────────────────────────────────────────

Fetch = Callable[[], Awaitable[Any]]


_FF_LIMITER = RateLimiter("forexfactory", default_rpm=2)  # >= 30 s between requests


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return float(resp.headers.get("Retry-After", ""))
    except ValueError:
        return None


async def fetch_ff_week(
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    limiter: RateLimiter | None = None,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> Any:
    """GET the weekly JSON through the rate limiter, with bounded retries.

    Network errors and 5xx are retried (``FETCH_ATTEMPTS`` in total);
    429 waits ``Retry-After`` when it is at most ``MAX_RETRY_AFTER``,
    otherwise gives up (the caller retries after ``RETRY_AFTER``). Other
    statuses fail at once.
    """
    limiter = limiter or _FF_LIMITER
    last = "no attempt"
    async with httpx.AsyncClient(
        timeout=15.0,
        headers={"User-Agent": "Mozilla/5.0 (compatible; trdex calendar)"},
        transport=transport,
    ) as client:
        for attempt in range(1, FETCH_ATTEMPTS + 1):
            await limiter.acquire()
            wait = 30.0 * attempt
            try:
                resp = await client.get(FF_URL)
            except httpx.TransportError as exc:
                last = f"{type(exc).__name__}"
            else:
                if resp.status_code == 200:
                    limiter.report_success()
                    return resp.json()
                last = f"calendar HTTP {resp.status_code}"
                if resp.status_code == 429:
                    limiter.report_rate_limit()
                    retry_after = _retry_after(resp)
                    if retry_after is not None and retry_after > MAX_RETRY_AFTER:
                        break
                    wait = max(wait, retry_after or 0.0)
                elif resp.status_code < 500:
                    break
            if attempt < FETCH_ATTEMPTS:
                await sleep(wait)
    raise RuntimeError(last)


@dataclass
class MacroCalendar:
    """In-memory view of upcoming events, backed by ``macro_events``."""

    session_factory: Any = None
    fetch: Fetch = fetch_ff_week
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(tz=UTC))
    events: list[MacroEvent] = field(default_factory=list)
    last_success: datetime | None = None
    last_attempt: datetime | None = None
    last_error: str | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def due(self, now: datetime) -> bool:
        last_try = self.last_attempt
        if last_try is not None and self.last_error is not None and now - last_try < RETRY_AFTER:
            return False
        return self.last_success is None or now - self.last_success >= REFRESH_EVERY

    async def load(self) -> None:
        """Restore events and the last fetch time from the DB (startup)."""
        if self.session_factory is None:
            return
        from trdex.storage.macro_events_repo import MacroEventsRepository

        now = self.clock()
        async with self.session_factory() as session:
            repo = MacroEventsRepository(session)
            self.events = await repo.between(
                SOURCE, now - timedelta(days=2), now + timedelta(days=9)
            )
            self.last_success = await repo.last_fetched(SOURCE)

    async def refresh(self, *, force: bool = False) -> bool:
        """Fetch when due; True if a fetch succeeded. Never raises."""
        async with self._lock:
            now = self.clock()
            if not force and not self.due(now):
                return False
            self.last_attempt = now
            try:
                events = parse_ff(await self.fetch())
                start, end = week_window(events)
                if not start <= now < end + timedelta(days=1):
                    raise ValueError(
                        f"calendar covers {start:%Y-%m-%d}..{end:%Y-%m-%d}, not the current week"
                    )
                if self.session_factory is not None:
                    from trdex.storage.macro_events_repo import MacroEventsRepository

                    async with self.session_factory() as session:
                        await MacroEventsRepository(session).replace_window(
                            SOURCE, events, now, start=start, end=end
                        )
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"[:200]
                logger.warning("[macro-calendar] refresh failed: %s", self.last_error)
                return False
            # Same replacement as in the DB: the fetched week's rows go,
            # the rest stays (only the last two days of it are needed).
            keep_from = now - timedelta(days=2)
            kept = [e for e in self.events if e.time >= keep_from and not start <= e.time < end]
            self.events = sorted(kept + events, key=lambda e: e.time)
            self.last_success, self.last_error = now, None
            logger.info("[macro-calendar] %d events loaded", len(events))
            return True

    def block_reason(self, now: datetime, cfg: MacroGateConfig, *, live: bool) -> str | None:
        return macro_block_reason(self.events, now, cfg, last_success=self.last_success, live=live)

    def upcoming(
        self, now: datetime, cfg: MacroGateConfig, *, hours: int = 72
    ) -> list[MacroEvent]:
        now = _utc(now)
        return [
            e
            for e in self.events
            if cfg.matches(e) and now - cfg.after <= e.time <= now + timedelta(hours=hours)
        ]

    def status(self) -> dict[str, Any]:
        return {
            "source": SOURCE,
            "events": len(self.events),
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_attempt": self.last_attempt.isoformat() if self.last_attempt else None,
            "last_error": self.last_error,
        }


_calendar: MacroCalendar | None = None


def get_macro_calendar() -> MacroCalendar:
    global _calendar
    if _calendar is None:
        _calendar = MacroCalendar()
    return _calendar


def set_macro_calendar(calendar: MacroCalendar) -> None:
    global _calendar
    _calendar = calendar


async def macro_calendar_loop(
    calendar: MacroCalendar,
    *,
    notify: Callable[..., Awaitable[Any]],
    cfg_provider: Callable[[], Any],
    tick_seconds: float = 900,
) -> None:
    """Keep the calendar fresh; tell the operator (daily) while it is stale."""
    last_notified: datetime | None = None
    try:
        await calendar.load()
    except Exception:
        logger.exception("[macro-calendar] load from DB failed")
    while True:
        try:
            await calendar.refresh()
            now = calendar.clock()
            gate = macro_gate_config(cfg_provider())
            stale = calendar.last_success is None or now - calendar.last_success > gate.stale_after
            if (
                gate.enabled
                and stale
                and (last_notified is None or now - last_notified >= NOTIFY_EVERY)
            ):
                from trdex.notify.events import Event

                await notify(
                    Event.MACRO_CALENDAR_STALE,
                    "Economic calendar unavailable — live entries would wait",
                    f"Last successful update: "
                    f"{calendar.last_success.isoformat() if calendar.last_success else 'never'}. "
                    f"Last error: {calendar.last_error or 'none'}. The macro gate blocks new live "
                    "entries until it is fresh again (simulation: gate off).",
                )
                last_notified = now
            elif not stale:
                last_notified = None
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[macro-calendar] tick failed")
        await asyncio.sleep(tick_seconds)
