"""Signal parser: extracts trading signals from Telegram message text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


@dataclass
class TelegramSignal:
    """A parsed trading signal extracted from a Telegram message."""

    source: str                                      # channel/group username
    symbol: str                                      # e.g. "BTC/USDT"
    direction: Literal["BUY", "SELL"]
    entry: float | None = None                       # entry price (None = at market)
    targets: list[float] = field(default_factory=list)  # take-profit levels
    stop_loss: float | None = None
    raw_text: str = ""
    parsed_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


# ── Regex patterns ──────────────────────────────────────────────────────────

_SYMBOL_RE = re.compile(
    r"\b([A-Z]{2,10})[/\-_]?(USDT|BTC|ETH|BUSD|USD)\b",
    re.IGNORECASE,
)
_DIRECTION_BUY_RE = re.compile(r"\b(buy|long|compra|acquisto)\b", re.IGNORECASE)
_DIRECTION_SELL_RE = re.compile(r"\b(sell|short|vendi|vendita)\b", re.IGNORECASE)
_PRICE_RE = re.compile(r"\b(\d{1,10}(?:[.,]\d+)?)\b")
_ENTRY_RE = re.compile(
    r"(?:entry|entra|enter|zona|zone|price)[:\s]+(\d{1,10}(?:[.,]\d+)?)",
    re.IGNORECASE,
)
_SL_RE = re.compile(
    r"(?:sl|stop[_\s-]?loss|stop)[:\s]+(\d{1,10}(?:[.,]\d+)?)",
    re.IGNORECASE,
)
_TP_RE = re.compile(
    r"(?:tp\d*|target\d*|take[_\s-]?profit\d*)[:\s]+(\d{1,10}(?:[.,]\d+)?)",
    re.IGNORECASE,
)


def _parse_number(s: str) -> float:
    return float(s.replace(",", "."))


def parse_signal(text: str, source: str) -> TelegramSignal | None:
    """Try to extract a trading signal from a message.

    Returns None if no clear signal is found.
    """
    # Symbol
    sym_match = _SYMBOL_RE.search(text)
    if not sym_match:
        return None
    base = sym_match.group(1).upper()
    quote = sym_match.group(2).upper()
    symbol = f"{base}/{quote}"

    # Direction
    is_buy = bool(_DIRECTION_BUY_RE.search(text))
    is_sell = bool(_DIRECTION_SELL_RE.search(text))
    if is_buy == is_sell:  # both or neither → ambiguous
        return None
    direction: Literal["BUY", "SELL"] = "BUY" if is_buy else "SELL"

    # Entry
    entry: float | None = None
    entry_match = _ENTRY_RE.search(text)
    if entry_match:
        entry = _parse_number(entry_match.group(1))

    # Stop loss
    stop_loss: float | None = None
    sl_match = _SL_RE.search(text)
    if sl_match:
        stop_loss = _parse_number(sl_match.group(1))

    # Take profit targets
    targets = [_parse_number(m.group(1)) for m in _TP_RE.finditer(text)]

    return TelegramSignal(
        source=source,
        symbol=symbol,
        direction=direction,
        entry=entry,
        targets=targets,
        stop_loss=stop_loss,
        raw_text=text,
    )
