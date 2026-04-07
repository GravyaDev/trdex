"""Tier 5 — Entity graph predicate ontology.

A small set of well-known predicate names used by trdex agents. Importing
constants from here instead of using string literals prevents typos and gives
the IDE autocomplete on the agent surface.

Subject types are also enumerated for the same reason.
"""

from __future__ import annotations

from typing import Final

# ---- subject_type constants -----------------------------------------------
SUBJECT_SYMBOL: Final = "symbol"
SUBJECT_CHANNEL: Final = "channel"
SUBJECT_STRATEGY: Final = "strategy"
SUBJECT_PORTFOLIO: Final = "portfolio"

ALL_SUBJECTS: Final = frozenset(
    {SUBJECT_SYMBOL, SUBJECT_CHANNEL, SUBJECT_STRATEGY, SUBJECT_PORTFOLIO}
)

# ---- predicate constants ---------------------------------------------------
# Symbol-level
PRED_VOLATILITY_REGIME: Final = "volatility_regime"
PRED_LAST_SIGNAL: Final = "last_signal"
PRED_TREND_REGIME: Final = "trend_regime"
PRED_CORRELATES_WITH: Final = "correlates_with"
PRED_LAST_DRAWDOWN_PCT: Final = "last_drawdown_pct"

# Channel-level (telegram signal sources)
PRED_WIN_RATE: Final = "win_rate"
PRED_SAMPLE_SIZE: Final = "sample_size"
PRED_REPUTATION: Final = "reputation"

# Portfolio-level
PRED_CURRENT_DRAWDOWN: Final = "current_drawdown"
PRED_PEAK_EQUITY: Final = "peak_equity"
PRED_KILL_SWITCH_REASON: Final = "kill_switch_reason"

# Strategy-level
PRED_HYPERPARAMS: Final = "hyperparams"
PRED_LAST_BACKTEST_SHARPE: Final = "last_backtest_sharpe"

ALL_PREDICATES: Final = frozenset(
    {
        PRED_VOLATILITY_REGIME,
        PRED_LAST_SIGNAL,
        PRED_TREND_REGIME,
        PRED_CORRELATES_WITH,
        PRED_LAST_DRAWDOWN_PCT,
        PRED_WIN_RATE,
        PRED_SAMPLE_SIZE,
        PRED_REPUTATION,
        PRED_CURRENT_DRAWDOWN,
        PRED_PEAK_EQUITY,
        PRED_KILL_SWITCH_REASON,
        PRED_HYPERPARAMS,
        PRED_LAST_BACKTEST_SHARPE,
    }
)


def is_known_predicate(predicate: str) -> bool:
    return predicate in ALL_PREDICATES


def is_known_subject(subject_type: str) -> bool:
    return subject_type in ALL_SUBJECTS
