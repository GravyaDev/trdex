"""Post-hoc TP/SL evaluator for Telegram observe-only signals.

For each open signal in `signal_outcomes` (exit_price IS NULL), fetch
OHLCV candles covering the window from `executed_at` to now, and check
whether any target or stop was touched. The first touch wins (TP if
reached before SL, SL otherwise). If neither is touched within the
evaluation window, the signal stays open and will be retried on the
next scheduler tick.

This module is intentionally pure: the scoring function takes OHLCV
candles and signal parameters as input and returns a resolution
decision. Only the wrapper `evaluate_open_signals` touches the DB and
the feed manager — that's what the app-level scheduler calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable

from trdex.market.models import OHLCV

logger = logging.getLogger(__name__)


# Maximum age of an open signal before we give up scoring it. Zanni's
# scalping signals resolve in minutes; after 24h a signal that still
# hasn't touched TP or SL is effectively noise — we mark it as stale
# so the open set doesn't grow unbounded.
STALE_AFTER = timedelta(hours=24)


@dataclass
class Resolution:
    """Outcome of scoring an open signal against historical candles."""

    status: str                 # "tp" | "sl" | "stale" | "open"
    exit_price: Decimal | None  # None iff status == "open"
    closed_at: datetime | None
    touched_target: float | None = None  # which TP level hit (1-indexed)


def score_signal(
    direction: str,
    entry_price: Decimal,
    targets: list[float],
    stop_loss: float | None,
    candles: Iterable[OHLCV],
    executed_at: datetime,
    now: datetime,
    stale_after: timedelta = STALE_AFTER,
) -> Resolution:
    """Decide whether the signal has hit TP or SL in the given window.

    Rule: walk candles in chronological order. For each candle, check
    if the high/low crossed a target or stop. First touch wins. If a
    single candle touches both (unusual but possible on volatile bars)
    we resolve conservatively to SL — scalping signals with tight TPs
    are more likely to trigger SL first in high-volatility moves.

    A signal without a stop_loss can still resolve on TP touch. A
    signal without any target can still resolve on SL touch.
    """
    if entry_price <= 0:
        return Resolution(status="open", exit_price=None, closed_at=None)

    # Sanity: reject wildly unreasonable targets/stop that could come
    # from a poisoned Telegram signal. A target more than 10x the entry
    # price (or less than 1/10) is almost certainly garbage.
    import math
    sane_targets = [
        t for t in targets
        if math.isfinite(t) and t > 0
        and 0.1 * float(entry_price) < t < 10 * float(entry_price)
    ]
    sane_stop: float | None = None
    if stop_loss is not None and math.isfinite(stop_loss) and stop_loss > 0:
        if 0.1 * float(entry_price) < stop_loss < 10 * float(entry_price):
            sane_stop = stop_loss

    sorted_candles = sorted(candles, key=lambda c: c.timestamp)
    sorted_candles = [c for c in sorted_candles if c.timestamp >= executed_at]

    # BUY: TPs are above entry, SL is below. SELL: inverted.
    if direction == "BUY":
        relevant_targets = sorted([t for t in sane_targets if t > float(entry_price)])
        sl_hit = lambda c: sane_stop is not None and float(c.low) <= sane_stop
        tp_hit = lambda c, t: float(c.high) >= t
    else:
        relevant_targets = sorted([t for t in sane_targets if t < float(entry_price)], reverse=True)
        sl_hit = lambda c: sane_stop is not None and float(c.high) >= sane_stop
        tp_hit = lambda c, t: float(c.low) <= t

    for candle in sorted_candles:
        sl_touched = sl_hit(candle)
        tp_touched_idx: int | None = None
        for i, t in enumerate(relevant_targets):
            if tp_hit(candle, t):
                tp_touched_idx = i
                break

        if sl_touched and tp_touched_idx is not None:
            # Ambiguous bar — resolve to SL conservatively.
            return Resolution(
                status="sl",
                exit_price=Decimal(str(sane_stop)) if sane_stop is not None else candle.close,
                closed_at=candle.timestamp,
            )
        if sl_touched:
            return Resolution(
                status="sl",
                exit_price=Decimal(str(sane_stop)) if sane_stop is not None else candle.close,
                closed_at=candle.timestamp,
            )
        if tp_touched_idx is not None:
            target = relevant_targets[tp_touched_idx]
            return Resolution(
                status="tp",
                exit_price=Decimal(str(target)),
                closed_at=candle.timestamp,
                touched_target=float(tp_touched_idx + 1),
            )

    # Nothing touched within the window — age out if older than threshold.
    age = now - executed_at
    if age > stale_after:
        last_close = sorted_candles[-1].close if sorted_candles else entry_price
        return Resolution(
            status="stale",
            exit_price=last_close,
            closed_at=now,
        )
    return Resolution(status="open", exit_price=None, closed_at=None)


def _is_finite_positive(v: float) -> bool:
    """Reject NaN, inf, negative, and zero values."""
    import math
    return math.isfinite(v) and v > 0


def _parse_note(note: str | None) -> tuple[list[float], float | None]:
    """Extract targets and stop_loss from the JSON note field.

    Validates that all parsed values are finite positive numbers —
    a poisoned Telegram signal with `stop_loss: 1e308` or negative
    floats could corrupt the scoring logic or cause Decimal overflow.
    """
    if not note:
        return [], None
    try:
        payload = json.loads(note)
        raw_targets = payload.get("targets", [])
        targets = [float(t) for t in raw_targets if _is_finite_positive(float(t))]
        stop_raw = payload.get("stop_loss")
        stop: float | None = None
        if stop_raw is not None:
            sv = float(stop_raw)
            stop = sv if _is_finite_positive(sv) else None
        return targets, stop
    except (json.JSONDecodeError, TypeError, ValueError, OverflowError):
        return [], None


def _timeframe_for(executed_at: datetime, now: datetime) -> tuple[str, int]:
    """Pick a timeframe that covers the window in a reasonable candle count.

    Binance allows up to 1000 candles per call. For scalping (hours) we
    want 5m candles; for stale signals (many hours) we step up to 15m
    to keep the fetch bounded.
    """
    hours = max(1, int((now - executed_at).total_seconds() // 3600) + 1)
    if hours <= 6:
        return "5m", min(1000, hours * 12 + 2)
    if hours <= 24:
        return "15m", min(1000, hours * 4 + 2)
    return "1h", min(1000, hours + 2)


async def evaluate_open_signals(
    session_factory,
    feed_manager,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Score all open signals against recent OHLCV, close the resolved
    ones, leave the rest for the next tick.

    Returns a counter dict with totals: `tp`, `sl`, `stale`, `open`,
    `errors`. Safe to call concurrently with the streaming handler —
    only reads open rows and updates each one independently.
    """
    from trdex.storage.signal_outcome_repo import SignalOutcomeRepository

    now = now or datetime.now(tz=timezone.utc)
    counters = {"tp": 0, "sl": 0, "stale": 0, "open": 0, "errors": 0}

    async with session_factory() as session:
        repo = SignalOutcomeRepository(session)
        open_records = await repo.open_outcomes()
        logger.info("[tg-eval] scoring %d open signals", len(open_records))

    for record in open_records:
        try:
            executed_at = record.executed_at
            if executed_at.tzinfo is None:
                executed_at = executed_at.replace(tzinfo=timezone.utc)
            targets, stop_loss = _parse_note(record.note)

            timeframe, limit = _timeframe_for(executed_at, now)
            since_ms = int(executed_at.timestamp() * 1000)
            try:
                candles = await feed_manager.get_ohlcv(
                    record.symbol,
                    timeframe=timeframe,
                    limit=limit,
                    since=since_ms,
                )
            except Exception as exc:
                logger.warning(
                    "[tg-eval] feed error for %s: %s — leaving open",
                    record.symbol, exc,
                )
                counters["errors"] += 1
                continue

            resolution = score_signal(
                direction=record.direction,
                entry_price=record.entry_price,
                targets=targets,
                stop_loss=stop_loss,
                candles=candles,
                executed_at=executed_at,
                now=now,
            )

            if resolution.status == "open":
                counters["open"] += 1
                continue

            # Preserve the targets/stop payload in note and append the
            # resolution reason for traceability.
            reason_note = json.dumps({
                "targets": targets,
                "stop_loss": stop_loss,
                "resolution": resolution.status,
                "touched_target": resolution.touched_target,
            })
            async with session_factory() as session:
                repo = SignalOutcomeRepository(session)
                assert resolution.exit_price is not None
                assert resolution.closed_at is not None
                await repo.close_outcome(
                    outcome_id=record.id,
                    exit_price=resolution.exit_price,
                    closed_at=resolution.closed_at,
                    note=reason_note,
                )
            counters[resolution.status] += 1
            logger.info(
                "[tg-eval] resolved %s %s id=%s → %s @ %s",
                record.direction, record.symbol, record.id,
                resolution.status, resolution.exit_price,
            )
        except Exception:
            logger.exception(
                "[tg-eval] failed to score signal id=%s", record.id
            )
            counters["errors"] += 1

    return counters


async def evaluator_loop(
    session_factory,
    feed_manager,
    interval_seconds: int = 3600,
) -> None:
    """Background loop: run `evaluate_open_signals` every interval.

    Designed to be spawned as an asyncio task from the FastAPI lifespan.
    Cancels cleanly on shutdown and swallows per-tick exceptions so a
    transient feed failure doesn't kill the loop.
    """
    logger.info(
        "[tg-eval] loop started — interval=%ds", interval_seconds,
    )
    try:
        while True:
            try:
                counters = await evaluate_open_signals(
                    session_factory, feed_manager,
                )
                logger.info(
                    "[tg-eval] tick complete — tp=%d sl=%d stale=%d open=%d errors=%d",
                    counters["tp"], counters["sl"], counters["stale"],
                    counters["open"], counters["errors"],
                )
            except Exception:
                logger.exception("[tg-eval] tick failed")
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("[tg-eval] loop cancelled")
        raise
