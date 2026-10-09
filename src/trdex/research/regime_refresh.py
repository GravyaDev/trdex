"""Regime refresher: keeps the volatility-regime bounds fresh with no human step.

Every ``scheduler.regime_refresh_interval_days`` (default 7):

1. sync closed 1h Binance OHLCV of the agent symbols into the DB,
   backfilling up to ``lookback_days`` on the first run, forward-filling
   afterwards (a symbol that fails is skipped and reported; at least half
   must succeed);
2. backtest the live rules (``LiveRuleEngine`` with the same Runtime
   Config risk settings the Risk node and StopLossMonitor read, net of
   fees) on the validation window;
3. if the backtest clears the same bar the simulation must clear (trades,
   net return > 0, win rate, max drawdown, Sharpe, at least
   ``min_dev_days`` of data) and the CV range is sane, write
   regime_cv_min/max (CV percentiles of that window) and regime_data_end.
   Otherwise keep the old bounds: they expire after regime_max_age_days
   and live entries stop (fail-closed).

The validation window is the whole lookback (``holdout`` 0): the job fits
nothing, it replays fixed rules, so there is no in-sample period to
protect. The sealed holdout belongs to manual research (scripts/backtest),
where people do iterate on rules. Using recent data also makes
regime_data_end the true end of the data the bounds describe, which is
what the readiness freshness check assumes.

Every tick (hourly) the watchdog also notifies when the bounds are about
to expire and when live readiness flips. Validation covers the rules
the agent falls back to; LLM decisions cannot be replayed historically.
"""

from __future__ import annotations

import asyncio
import logging
import math
import multiprocessing
from collections.abc import Awaitable, Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from typing import Any, Literal

from trdex.research.engine import BacktestResult, EngineParams, run_backtest
from trdex.research.stats import data_end, dev_period, regime_range
from trdex.research.strategies import LiveRuleEngine

logger = logging.getLogger(__name__)

TIMEFRAME = "1h"
BAR_MS = 3_600_000
ERROR_RETRY = timedelta(hours=6)
NOTIFY_EVERY = timedelta(hours=24)
EXPIRY_WARNING_DAYS = 14

FetchPage = Callable[[str, int], Awaitable[list[Any]]]  # (symbol, since_ms) -> [OHLCV]
Notify = Callable[..., Awaitable[Any]]


# ── validation ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ValidationCriteria:
    min_trades: int = 20
    min_win_rate: float = 0.40  # fraction
    max_drawdown: float = 0.20  # fraction
    min_sharpe: float = 1.0
    min_dev_days: int = 365


def validation_failures(
    result: BacktestResult, criteria: ValidationCriteria, dev_days: float
) -> list[str]:
    """Unmet criteria for a backtest of the live rules (empty = validated)."""
    out: list[str] = []
    if dev_days < criteria.min_dev_days:
        out.append(f"history {dev_days:.0f} days < {criteria.min_dev_days} required")
    if result.trades_count < criteria.min_trades:
        out.append(f"trades {result.trades_count} < {criteria.min_trades}")
    if result.return_pct <= 0:
        out.append(f"net return {result.return_pct:+.2f}% <= 0")
    if result.win_rate < criteria.min_win_rate:
        out.append(f"win rate {result.win_rate:.1%} < {criteria.min_win_rate:.1%}")
    if result.max_drawdown_pct / 100.0 > criteria.max_drawdown:
        out.append(f"max drawdown {result.max_drawdown_pct:.1f}% > {criteria.max_drawdown:.0%}")
    if result.sharpe < criteria.min_sharpe:
        out.append(f"Sharpe {result.sharpe:.2f} < {criteria.min_sharpe:.2f}")
    return out


# ── pure evaluation ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class RefreshConfig:
    symbols: tuple[str, ...]
    engine: EngineParams
    risk_per_trade_pct: float
    criteria: ValidationCriteria = field(default_factory=ValidationCriteria)
    lookback_days: int = 1825
    holdout: float = 0.0  # 0 = validate on the whole lookback (see module doc)
    lo_pct: float = 0.5
    hi_pct: float = 99.5


@dataclass
class RefreshOutcome:
    status: Literal["refreshed", "validation_failed"]
    data_end: date
    dev_cutoff: date
    cv_min: float | None = None
    cv_max: float | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)  # symbol -> reason

    def summary(self) -> str:
        m = self.metrics
        perf = (
            f"window to {self.dev_cutoff}: {int(m.get('trades', 0))} trades, "
            f"return {m.get('return_pct', 0):+.2f}%, win {m.get('win_rate', 0):.1%}, "
            f"max DD {m.get('max_drawdown_pct', 0):.1f}%, Sharpe {m.get('sharpe', 0):.2f}"
        )
        skipped = (
            f"; skipped {', '.join(f'{s} ({r})' for s, r in self.skipped.items())}"
            if self.skipped
            else ""
        )
        if self.status == "refreshed":
            head = f"refreshed: CV {self.cv_min:.6f}-{self.cv_max:.6f}, data to {self.data_end}"
        else:
            head = f"validation failed ({'; '.join(self.failures)})"
        return f"{head}; {perf}{skipped}"


def evaluate(ohlcv_by_symbol: dict[str, list[list[Any]]], cfg: RefreshConfig) -> RefreshOutcome:
    """Backtest the live rules on the window; bounds only if they pass. CPU-bound."""
    data = {s: b for s, b in ohlcv_by_symbol.items() if b}
    if not data:
        raise ValueError("no OHLCV data for any symbol")
    if cfg.holdout > 0:
        window, cutoff = dev_period(data, cfg.holdout)
    else:
        window, cutoff = data, data_end(data) + BAR_MS
    window = {s: b for s, b in window.items() if len(b) > 50}
    if not window:
        raise ValueError("validation window too short for every symbol")
    first = min(b[0][0] for b in window.values())
    dev_days = (cutoff - first) / 86_400_000
    result = run_backtest(
        LiveRuleEngine(risk_per_trade_pct=cfg.risk_per_trade_pct), window, cfg.engine
    )
    metrics = {
        "trades": float(result.trades_count),
        "return_pct": result.return_pct,
        "win_rate": result.win_rate,
        "max_drawdown_pct": result.max_drawdown_pct,
        "sharpe": result.sharpe,
        "dev_days": dev_days,
    }
    failures = validation_failures(result, cfg.criteria, dev_days)
    ranges = regime_range(window, lo_pct=cfg.lo_pct, hi_pct=cfg.hi_pct)
    lo = hi = None
    if "*" not in ranges:
        failures.append("no CV data")
    else:
        lo, _, hi, _ = ranges["*"]
        if not (math.isfinite(lo) and math.isfinite(hi) and 0 < lo < hi):
            failures.append(f"degenerate CV range {lo!r}-{hi!r}")
    end = datetime.fromtimestamp(data_end(data) / 1000, tz=UTC).date()
    cut = datetime.fromtimestamp((cutoff - BAR_MS) / 1000, tz=UTC).date()
    if failures:
        return RefreshOutcome("validation_failed", end, cut, metrics=metrics, failures=failures)
    return RefreshOutcome("refreshed", end, cut, cv_min=lo, cv_max=hi, metrics=metrics)


# ── data ──────────────────────────────────────────────────────────────────


def _naive_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


def _ms(dt: datetime) -> int:
    return int(_naive_utc(dt).replace(tzinfo=UTC).timestamp() * 1000)


def _check_hourly(symbol: str, page: list[Any]) -> None:
    """Refuse anything that is not on-the-hour, strictly increasing 1h bars."""
    stamps = [_ms(c.timestamp) for c in page]
    if any(ts % BAR_MS for ts in stamps) or any(b <= a for a, b in pairwise(stamps)):
        raise ValueError(f"{symbol}: feed returned bars that are not 1h-aligned and ordered")


async def _store_range(
    session_factory: Any, fetch_page: FetchPage, symbol: str, start_ms: int, end_ms: int
) -> int:
    """Fetch closed bars in [start_ms, end_ms) page by page and upsert them."""
    from trdex.storage.ohlcv_repo import OHLCVRepository

    inserted, cursor = 0, start_ms
    while cursor < end_ms:
        page = await fetch_page(symbol, cursor)
        if not page:
            break
        _check_hourly(symbol, page)
        closed = [c for c in page if _ms(c.timestamp) < end_ms]
        if closed:
            async with session_factory() as session:
                inserted += await OHLCVRepository(session).upsert(
                    symbol, TIMEFRAME, closed, source="binance"
                )
        nxt = _ms(page[-1].timestamp) + BAR_MS
        if nxt <= cursor or not closed:
            break
        cursor = nxt
    return inserted


async def sync_symbol(
    session_factory: Any, fetch_page: FetchPage, symbol: str, *, lookback_days: int, now: datetime
) -> int:
    """Make the DB hold closed 1h bars of ``symbol`` from now - lookback to now.

    Backfills what is missing before the first stored bar (one request if
    the exchange has nothing older, e.g. a recently listed coin), then
    forward-fills after the last one. The forming bar is never stored.
    """
    from trdex.storage.ohlcv_repo import OHLCVRepository

    end_ms = (_ms(now) // BAR_MS) * BAR_MS  # start of the forming bar
    start_ms = end_ms - lookback_days * 86_400_000
    async with session_factory() as session:
        first, last = await OHLCVRepository(session).time_range(symbol, TIMEFRAME)
    if first is None or last is None:
        return await _store_range(session_factory, fetch_page, symbol, start_ms, end_ms)
    inserted = 0
    if _ms(first) > start_ms + BAR_MS:
        inserted += await _store_range(session_factory, fetch_page, symbol, start_ms, _ms(first))
    inserted += await _store_range(session_factory, fetch_page, symbol, _ms(last) + BAR_MS, end_ms)
    return inserted


async def load_symbol(
    session_factory: Any, symbol: str, *, lookback_days: int, now: datetime
) -> list[list[Any]]:
    """Stored closed 1h bars as [ts_ms, open, high, low, close, volume]."""
    from trdex.storage.ohlcv_repo import OHLCVRepository

    end_ms = (_ms(now) // BAR_MS) * BAR_MS  # same window as sync_symbol
    since = datetime.fromtimestamp((end_ms - lookback_days * 86_400_000) / 1000, tz=UTC)
    async with session_factory() as session:
        rows = await OHLCVRepository(session).fetch(
            symbol, TIMEFRAME, since=_naive_utc(since), limit=lookback_days * 24 + 48
        )
    out = [
        [
            _ms(r.timestamp),
            float(r.open),
            float(r.high),
            float(r.low),
            float(r.close),
            float(r.volume),
        ]
        for r in rows
    ]
    return [b for b in out if b[0] < end_ms]


# ── config ────────────────────────────────────────────────────────────────


def _threshold(cfg: Any, key: str, default: float) -> float:
    """Same read as the Risk node's ``_cfg_float``: Runtime Config value as is."""
    value = cfg.get_typed("thresholds", key, default)
    return float(default if value is None else value)


def _sched(cfg: Any, key: str, default: int) -> int:
    """Positive whole number of days from ``scheduler``; garbage -> default."""
    raw = cfg.get("scheduler", key, "")
    try:
        value = float(raw) if str(raw).strip() else default
    except ValueError:
        return default
    return max(1, int(value)) if value > 0 else default


def build_refresh_config(cfg: Any, settings: Any) -> RefreshConfig:
    """RefreshConfig from Runtime Config, read exactly as the live path reads it.

    Risk/exit settings: ``thresholds`` via get_typed, like the Risk node and
    the StopLossMonitor (0 stays 0). Criteria: the settings the readiness
    gate judges the simulation with.
    """
    from trdex.agents.risk import MAX_POSITION_FRACTION
    from trdex.risk.readiness import MIN_TRADES_FOR_EVALUATION

    symbols_csv = (
        cfg.get("symbols", "agent_scheduler_symbols", "") or settings.agent_scheduler_symbols
    )
    symbols = tuple(s.strip() for s in symbols_csv.split(",") if s.strip())
    if not symbols:
        raise ValueError("no agent symbols configured (symbols.agent_scheduler_symbols)")
    engine = EngineParams(
        position_size_pct=min(
            _threshold(cfg, "max_position_pct", settings.max_position_pct), MAX_POSITION_FRACTION
        ),
        fee_pct=0.001,
        sl_pct=_threshold(cfg, "sl_position_pct", settings.sl_position_pct),
        tp_pct=_threshold(cfg, "sl_take_profit_pct", settings.sl_take_profit_pct),
        trail_pct=_threshold(cfg, "sl_trailing_stop_pct", settings.sl_trailing_stop_pct),
    )
    criteria = ValidationCriteria(
        min_trades=MIN_TRADES_FOR_EVALUATION,
        min_win_rate=settings.gate_min_win_rate,
        max_drawdown=settings.gate_max_drawdown,
        min_sharpe=settings.gate_min_sharpe,
    )
    return RefreshConfig(
        symbols=symbols,
        engine=engine,
        risk_per_trade_pct=_threshold(cfg, "risk_per_trade_pct", settings.risk_per_trade_pct),
        criteria=criteria,
        lookback_days=_sched(cfg, "regime_lookback_days", 1825),
    )


# ── watchdog ──────────────────────────────────────────────────────────────


async def run_in_subprocess(fn: Callable[..., Any], *args: Any) -> Any:
    """Run a CPU-bound function in a fresh process.

    The backtest takes ~30 s on 5 years x 10 symbols; in a thread it would
    hold the GIL and slow the event loop (stop-loss checks, agent cycles).
    ``spawn`` avoids forking a process that has a running loop and threads.
    On cancellation (app shutdown) the worker is terminated, so a shutdown
    does not wait for the backtest to finish.
    """
    loop = asyncio.get_running_loop()
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    try:
        return await loop.run_in_executor(pool, fn, *args)
    except asyncio.CancelledError:
        for proc in list(getattr(pool, "_processes", {}).values()):
            proc.terminate()
        raise
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _parse(raw: Any) -> datetime | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return _naive_utc(datetime.fromisoformat(str(raw).strip()))
    except ValueError:
        return None


def _iso(now: datetime) -> str:
    return _naive_utc(now).replace(tzinfo=UTC).isoformat(timespec="seconds")


def _delivered(outcome: Any) -> bool:
    """True unless a channel errored: then the caller retries next tick.

    "not configured" counts as done: nothing to retry until the operator
    sets a channel up (the Notifier logs the undelivered message).
    """
    if not isinstance(outcome, dict):
        return True
    return not any(str(v).startswith("error") for v in outcome.values())


class RegimeWatchdog:
    """Hourly tick: refresh when due, warn before expiry, report readiness flips."""

    def __init__(
        self,
        *,
        session_factory: Any,
        fetch_page: FetchPage,
        cfg_provider: Callable[[], Any],
        settings_provider: Callable[[], Any],
        notify: Notify,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
        run_cpu: Callable[..., Awaitable[Any]] = run_in_subprocess,
    ) -> None:
        self._sf = session_factory
        self._fetch_page = fetch_page
        self._cfg = cfg_provider
        self._settings = settings_provider
        self._notify = notify
        self._clock = clock
        self._run_cpu = run_cpu

    async def tick(self) -> None:
        cfg = self._cfg()
        if cfg is None:
            logger.warning("[regime-watchdog] Runtime Config not ready, skipping tick")
            return
        now = self._clock()
        for step in (self._maybe_refresh, self._check_expiry, self._check_readiness):
            try:
                await step(cfg, now)
            except Exception:
                logger.exception("[regime-watchdog] %s failed", step.__name__)

    # -- refresh --

    def _refresh_due(self, cfg: Any, now: datetime) -> bool:
        if not cfg.get_typed("scheduler", "regime_refresh_enabled", True):
            return False
        interval = _sched(cfg, "regime_refresh_interval_days", 7)
        last = _parse(cfg.get("thresholds", "regime_last_refresh_at", ""))
        if last is not None and _naive_utc(now) - last < timedelta(days=interval):
            return False
        last_err = _parse(cfg.get("watchdog", "last_error_at", ""))
        return not (last_err is not None and _naive_utc(now) - last_err < ERROR_RETRY)

    async def _collect(
        self, rc: RefreshConfig, now: datetime
    ) -> tuple[dict[str, list[list[Any]]], dict[str, str]]:
        data: dict[str, list[list[Any]]] = {}
        skipped: dict[str, str] = {}
        for symbol in rc.symbols:
            try:
                await sync_symbol(
                    self._sf, self._fetch_page, symbol, lookback_days=rc.lookback_days, now=now
                )
                bars = await load_symbol(self._sf, symbol, lookback_days=rc.lookback_days, now=now)
            except Exception as exc:
                logger.warning("[regime-watchdog] %s skipped: %s", symbol, exc)
                skipped[symbol] = f"{type(exc).__name__}: {exc}"[:200]
                continue
            if bars:
                data[symbol] = bars
            else:
                skipped[symbol] = "no data"
        if len(data) * 2 < len(rc.symbols):
            raise RuntimeError(
                f"only {len(data)}/{len(rc.symbols)} symbols have data; skipped: {skipped}"
            )
        return data, skipped

    async def _maybe_refresh(self, cfg: Any, now: datetime) -> None:
        if not self._refresh_due(cfg, now):
            return
        from trdex.notify.events import Event

        try:
            rc = build_refresh_config(cfg, self._settings())
            data, skipped = await self._collect(rc, now)
            outcome: RefreshOutcome = await self._run_cpu(evaluate, data, rc)
            outcome.skipped = skipped
        except Exception as exc:
            logger.exception("[regime-watchdog] refresh failed")
            await self._refresh_error(cfg, now, exc)
            return

        pairs = {
            "regime_last_refresh_at": _iso(now),
            "regime_last_refresh_status": outcome.summary()[:1000],
        }
        if outcome.status == "refreshed":
            pairs |= {
                "regime_cv_min": repr(outcome.cv_min),
                "regime_cv_max": repr(outcome.cv_max),
                "regime_data_end": outcome.data_end.isoformat(),
            }
        await cfg.put_category("thresholds", pairs)
        await cfg.put_category("watchdog", {"last_error_at": ""})
        logger.info("[regime-watchdog] %s", outcome.summary())
        if outcome.status == "refreshed":
            await self._notify(
                Event.REGIME_REFRESHED, "Regime bounds refreshed", outcome.summary()
            )
        else:
            await self._notify(
                Event.REGIME_VALIDATION_FAILED,
                "Live rules failed revalidation — regime bounds NOT refreshed",
                outcome.summary() + "\nThe previous bounds stay until they expire; then live "
                "entries stop. Next attempt at the next refresh interval.",
            )

    async def _refresh_error(self, cfg: Any, now: datetime, exc: Exception) -> None:
        """Notify first (the DB may be what failed), then record the backoff."""
        from trdex.notify.events import Event

        try:
            notify_now = self._should_notify(cfg, "last_error_notified_at", now, NOTIFY_EVERY)
        except Exception:
            notify_now = True
        if notify_now:
            await self._notify(
                Event.REGIME_REFRESH_ERROR,
                "Regime refresh failed — will retry in 6h",
                f"{type(exc).__name__}: {exc}\nCurrent bounds are unchanged; "
                "they expire after regime_max_age_days.",
            )
        try:
            state = {"last_error_at": _iso(now)}
            if notify_now:
                state["last_error_notified_at"] = _iso(now)
            await cfg.put_category("watchdog", state)
        except Exception:
            logger.exception("[regime-watchdog] could not record the refresh error")

    # -- expiry --

    async def _check_expiry(self, cfg: Any, now: datetime) -> None:
        end = _parse(cfg.get("thresholds", "regime_data_end", ""))
        if end is None:
            return
        max_age = _threshold_int(cfg, "regime_max_age_days", 90)  # as readiness reads it
        days_left = max_age - (_naive_utc(now).date() - end.date()).days
        if days_left > EXPIRY_WARNING_DAYS:
            return
        if not self._should_notify(cfg, "last_expiry_notified_at", now, NOTIFY_EVERY):
            return
        from trdex.notify.events import Event

        last = cfg.get("thresholds", "regime_last_refresh_status", "") or "never"
        if days_left >= 0:
            subject = f"Regime bounds expire in {days_left} days"
            body = (
                f"regime_data_end {end.date()} + {max_age} days. The refresher has not renewed "
                f"them; at expiry live entries stop. Last refresh: {last}"
            )
        else:
            subject = "Regime bounds EXPIRED — live entries blocked"
            body = f"Expired {-days_left} days ago (data end {end.date()}). Last refresh: {last}"
        outcome = await self._notify(Event.REGIME_EXPIRING, subject, body)
        if _delivered(outcome):
            await cfg.put_category("watchdog", {"last_expiry_notified_at": _iso(now)})

    # -- readiness --

    async def _check_readiness(self, cfg: Any, now: datetime) -> None:
        """Notify a flip once it has held for two consecutive ticks (no flapping)."""
        from trdex.notify.events import Event
        from trdex.risk.readiness import evaluate_readiness

        settings = self._settings()
        async with self._sf() as session:
            report = await evaluate_readiness(session, settings, cfg)
        state = "READY" if report.ready else "NOT READY"
        if cfg.get("watchdog", "last_readiness", "") == state:
            if cfg.get("watchdog", "pending_readiness", ""):
                await cfg.put_category("watchdog", {"pending_readiness": ""})
            return
        if cfg.get("watchdog", "pending_readiness", "") != state:
            await cfg.put_category("watchdog", {"pending_readiness": state})
            return
        lines = [f"Mode: {getattr(settings.mode, 'value', settings.mode)}"]
        lines += [f"- {f}" for f in report.failures] or ["All criteria met."]
        lines += [f"! {w}" for w in report.warnings]
        outcome = await self._notify(
            Event.READINESS_CHANGED, f"Live readiness: {state}", "\n".join(lines)
        )
        if _delivered(outcome):
            await cfg.put_category("watchdog", {"last_readiness": state, "pending_readiness": ""})

    @staticmethod
    def _should_notify(cfg: Any, key: str, now: datetime, every: timedelta) -> bool:
        last = _parse(cfg.get("watchdog", key, ""))
        return last is None or _naive_utc(now) - last >= every


def _threshold_int(cfg: Any, key: str, default: int) -> int:
    raw = cfg.get("thresholds", key, "")
    try:
        value = int(float(raw)) if str(raw).strip() else default
    except ValueError:
        return default
    return value if value > 0 else default


async def watchdog_loop(
    watchdog: RegimeWatchdog, *, tick_seconds: float = 3600, initial_delay: float = 120
) -> None:
    """Run ``watchdog.tick`` forever; a failing tick never stops the loop."""
    await asyncio.sleep(initial_delay)
    while True:
        try:
            await watchdog.tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[regime-watchdog] tick crashed")
        await asyncio.sleep(tick_seconds)
