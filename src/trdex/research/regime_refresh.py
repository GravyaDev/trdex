"""Regime refresher: keeps the volatility-regime bounds fresh with no human step.

Every ``scheduler.regime_refresh_interval_days`` (default 7):

1. sync closed 1h OHLCV of the agent symbols into the DB, backfilling up
   to ``lookback_days`` on the first run, forward-filling afterwards;
2. drop the sealed holdout (most recent ``holdout`` fraction, never read
   here, kept for manual research);
3. backtest the live rules (``LiveRuleEngine`` with the Runtime Config
   risk settings, net of fees) on the development period;
4. if the backtest clears the same bar the simulation must clear (trades,
   net return > 0, win rate, max drawdown, Sharpe, at least
   ``min_dev_days`` of data), write regime_cv_min/max (CV percentiles of
   that period) and regime_data_end. Otherwise keep the old bounds: they
   expire after regime_max_age_days and live entries stop (fail-closed).

Every tick (hourly) the watchdog also notifies when the bounds are about
to expire and when live readiness flips. Validation covers the rules
the agent falls back to; LLM decisions cannot be replayed historically.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
from collections.abc import Awaitable, Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from trdex.research.engine import BacktestResult, EngineParams, run_backtest
from trdex.research.stats import data_end, dev_period, regime_range
from trdex.research.strategies import LiveRuleEngine

logger = logging.getLogger(__name__)

TIMEFRAME = "1h"
BAR_MS = 3_600_000
PAGE_LIMIT = 1000
ERROR_RETRY = timedelta(hours=6)
NOTIFY_EVERY = timedelta(hours=24)
EXPIRY_WARNING_DAYS = 14

FetchPage = Callable[[str, int], Awaitable[list[Any]]]  # (symbol, since_ms) -> [OHLCV]


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
    holdout: float = 0.3
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

    def summary(self) -> str:
        m = self.metrics
        perf = (
            f"dev period to {self.dev_cutoff}: {int(m.get('trades', 0))} trades, "
            f"return {m.get('return_pct', 0):+.2f}%, win {m.get('win_rate', 0):.1%}, "
            f"max DD {m.get('max_drawdown_pct', 0):.1f}%, Sharpe {m.get('sharpe', 0):.2f}"
        )
        if self.status == "refreshed":
            return f"refreshed: CV {self.cv_min:.5f}-{self.cv_max:.5f}, data to {self.data_end}; {perf}"
        return f"validation failed ({'; '.join(self.failures)}); {perf}"


def evaluate(ohlcv_by_symbol: dict[str, list[list[Any]]], cfg: RefreshConfig) -> RefreshOutcome:
    """Backtest the live rules on the dev period; bounds only if they pass. CPU-bound."""
    data = {s: b for s, b in ohlcv_by_symbol.items() if b}
    if not data:
        raise ValueError("no OHLCV data for any symbol")
    dev, cutoff = dev_period(data, cfg.holdout)
    dev = {s: b for s, b in dev.items() if len(b) > 50}
    if not dev:
        raise ValueError("development period too short for every symbol")
    first = min(b[0][0] for b in dev.values())
    dev_days = (cutoff - first) / 86_400_000
    result = run_backtest(
        LiveRuleEngine(risk_per_trade_pct=cfg.risk_per_trade_pct), dev, cfg.engine
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
    ranges = regime_range(dev, lo_pct=cfg.lo_pct, hi_pct=cfg.hi_pct)
    if "*" not in ranges:
        failures.append("no CV data")
    end = datetime.fromtimestamp(data_end(data) / 1000, tz=UTC).date()
    cut = datetime.fromtimestamp(cutoff / 1000, tz=UTC).date()
    if failures:
        return RefreshOutcome("validation_failed", end, cut, metrics=metrics, failures=failures)
    lo, _, hi, _ = ranges["*"]
    return RefreshOutcome("refreshed", end, cut, cv_min=lo, cv_max=hi, metrics=metrics)


# ── data ──────────────────────────────────────────────────────────────────


def _naive_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


def _ms(dt: datetime) -> int:
    return int(_naive_utc(dt).replace(tzinfo=UTC).timestamp() * 1000)


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
        closed = [c for c in page if _ms(c.timestamp) < end_ms]
        if closed:
            async with session_factory() as session:
                inserted += await OHLCVRepository(session).upsert(symbol, TIMEFRAME, closed)
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


def _num(cfg: Any, category: str, key: str, default: float) -> float:
    raw = cfg.get(category, key, "")
    try:
        value = float(raw) if str(raw).strip() else default
    except ValueError:
        return default
    return value if value > 0 else default


def build_refresh_config(cfg: Any, settings: Any) -> RefreshConfig:
    """RefreshConfig from Runtime Config, with the same fallbacks as the Risk node."""
    from trdex.agents.risk import MAX_POSITION_FRACTION
    from trdex.risk.readiness import MIN_TRADES_FOR_EVALUATION

    symbols_csv = (
        cfg.get("symbols", "agent_scheduler_symbols", "") or settings.agent_scheduler_symbols
    )
    symbols = tuple(s.strip() for s in symbols_csv.split(",") if s.strip())
    if not symbols:
        raise ValueError("no agent symbols configured (symbols.agent_scheduler_symbols)")
    th = "thresholds"
    engine = EngineParams(
        position_size_pct=min(
            _num(cfg, th, "max_position_pct", settings.max_position_pct), MAX_POSITION_FRACTION
        ),
        fee_pct=0.001,
        sl_pct=_num(cfg, th, "sl_position_pct", settings.sl_position_pct),
        tp_pct=_num(cfg, th, "sl_take_profit_pct", settings.sl_take_profit_pct),
        trail_pct=_num(cfg, th, "sl_trailing_stop_pct", settings.sl_trailing_stop_pct),
    )
    criteria = ValidationCriteria(
        min_trades=MIN_TRADES_FOR_EVALUATION,
        min_win_rate=settings.gate_min_win_rate,
        max_drawdown=_num(cfg, th, "gate_max_drawdown", settings.gate_max_drawdown),
        min_sharpe=settings.gate_min_sharpe,
    )
    return RefreshConfig(
        symbols=symbols,
        engine=engine,
        risk_per_trade_pct=_num(cfg, th, "risk_per_trade_pct", settings.risk_per_trade_pct),
        criteria=criteria,
        lookback_days=int(_num(cfg, "scheduler", "regime_lookback_days", 1825)),
    )


# ── watchdog ──────────────────────────────────────────────────────────────


async def run_in_subprocess(fn: Callable[..., Any], *args: Any) -> Any:
    """Run a CPU-bound function in a fresh process.

    The backtest takes ~30 s on 5 years x 10 symbols; in a thread it would
    hold the GIL and slow the event loop (stop-loss checks, agent cycles).
    ``spawn`` avoids forking a process that has a running loop and threads.
    """
    loop = asyncio.get_running_loop()
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    try:
        return await loop.run_in_executor(pool, fn, *args)
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


class RegimeWatchdog:
    """Hourly tick: refresh when due, warn before expiry, report readiness flips."""

    def __init__(
        self,
        *,
        session_factory: Any,
        fetch_page: FetchPage,
        cfg_provider: Callable[[], Any],
        settings_provider: Callable[[], Any],
        notify: Callable[..., Awaitable[Any]],
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
        interval = int(_num(cfg, "scheduler", "regime_refresh_interval_days", 7))
        last = _parse(cfg.get("thresholds", "regime_last_refresh_at", ""))
        if last is not None and _naive_utc(now) - last < timedelta(days=interval):
            return False
        last_err = _parse(cfg.get("watchdog", "last_error_at", ""))
        return not (last_err is not None and _naive_utc(now) - last_err < ERROR_RETRY)

    async def _maybe_refresh(self, cfg: Any, now: datetime) -> None:
        if not self._refresh_due(cfg, now):
            return
        from trdex.notify.events import Event

        try:
            rc = build_refresh_config(cfg, self._settings())
            data: dict[str, list[list[Any]]] = {}
            for symbol in rc.symbols:
                await sync_symbol(
                    self._sf, self._fetch_page, symbol, lookback_days=rc.lookback_days, now=now
                )
                data[symbol] = await load_symbol(
                    self._sf, symbol, lookback_days=rc.lookback_days, now=now
                )
            outcome: RefreshOutcome = await self._run_cpu(evaluate, data, rc)
        except Exception as exc:
            logger.exception("[regime-watchdog] refresh failed")
            await cfg.put_category("watchdog", {"last_error_at": _iso(now)})
            if self._should_notify(cfg, "last_error_notified_at", now, NOTIFY_EVERY):
                await self._notify(
                    Event.REGIME_REFRESH_ERROR,
                    "Regime refresh failed — will retry in 6h",
                    f"{type(exc).__name__}: {exc}\nCurrent bounds are unchanged; "
                    "they expire after regime_max_age_days.",
                )
                await cfg.put_category("watchdog", {"last_error_notified_at": _iso(now)})
            return

        pairs = {
            "regime_last_refresh_at": _iso(now),
            "regime_last_refresh_status": outcome.summary()[:1000],
        }
        if outcome.status == "refreshed":
            pairs |= {
                "regime_cv_min": f"{outcome.cv_min:.6f}",
                "regime_cv_max": f"{outcome.cv_max:.6f}",
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

    # -- expiry --

    async def _check_expiry(self, cfg: Any, now: datetime) -> None:
        end = _parse(cfg.get("thresholds", "regime_data_end", ""))
        if end is None:
            return
        max_age = int(_num(cfg, "thresholds", "regime_max_age_days", 90))
        days_left = max_age - (_naive_utc(now).date() - end.date()).days
        if days_left > EXPIRY_WARNING_DAYS:
            return
        if not self._should_notify(cfg, "last_expiry_notified_at", now, NOTIFY_EVERY):
            return
        from trdex.notify.events import Event

        if days_left >= 0:
            subject = f"Regime bounds expire in {days_left} days"
            body = (
                f"regime_data_end {end.date()} + {max_age} days. The refresher has not renewed "
                "them; at expiry live entries stop. Last refresh: "
                f"{cfg.get('thresholds', 'regime_last_refresh_status', '') or 'never'}"
            )
        else:
            subject = "Regime bounds EXPIRED — live entries blocked"
            body = (
                f"Expired {-days_left} days ago (data end {end.date()}). Last refresh: "
                f"{cfg.get('thresholds', 'regime_last_refresh_status', '') or 'never'}"
            )
        await self._notify(Event.REGIME_EXPIRING, subject, body)
        await cfg.put_category("watchdog", {"last_expiry_notified_at": _iso(now)})

    # -- readiness --

    async def _check_readiness(self, cfg: Any, now: datetime) -> None:
        from trdex.notify.events import Event
        from trdex.risk.readiness import evaluate_readiness

        settings = self._settings()
        async with self._sf() as session:
            report = await evaluate_readiness(session, settings, cfg)
        state = "READY" if report.ready else "NOT READY"
        if cfg.get("watchdog", "last_readiness", "") == state:
            return
        await cfg.put_category("watchdog", {"last_readiness": state})
        lines = [f"Mode: {getattr(settings.mode, 'value', settings.mode)}"]
        lines += [f"- {f}" for f in report.failures] or ["All criteria met."]
        lines += [f"! {w}" for w in report.warnings]
        await self._notify(Event.READINESS_CHANGED, f"Live readiness: {state}", "\n".join(lines))

    @staticmethod
    def _should_notify(cfg: Any, key: str, now: datetime, every: timedelta) -> bool:
        last = _parse(cfg.get("watchdog", key, ""))
        return last is None or _naive_utc(now) - last >= every


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
