"""Signal parser: extracts trading signals from Telegram message text.

Handles multiple signal formats from diverse Telegram channels:
- Standard labeled: "BUY EURUSD Entry: 1.0850 TP: 1.0900 SL: 1.0820"
- Inline entry: "SELL 1.38350" on first line
- Commodity aliases: "GOLD BUY 2350" → XAU/USD
- Index symbols: "NAS100 SELL 18500" → NAS100/USD
- Italian: "Compra zona 140"
- Variant labels: "Entry Level:", "Goal:", "Target Level:",
  "Safe Stop Loss:", "Stoploss:"

Also classifies messages as report/update vs live signal to avoid
acting on historical recaps.
"""

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


# ── Commodity / index aliases ───────────────────────────────────────────────
# Maps bare commodity or index names to a normalized symbol pair.
# These names appear without a quote currency suffix in many channels
# (e.g. "GOLD BUY 2350" instead of "XAUUSD BUY 2350").

_COMMODITY_ALIASES: dict[str, str] = {
    "GOLD": "XAU/USD",
    "XAUUSD": "XAU/USD",
    "XAUEUR": "XAU/EUR",
    "SILVER": "XAG/USD",
    "XAGUSD": "XAG/USD",
    "USOIL": "WTI/USD",
    "WTI": "WTI/USD",
    "BRENT": "BRENT/USD",
    "NATGAS": "NATGAS/USD",
    "US30": "US30/USD",
    "NAS100": "NAS100/USD",
    "USTEC": "NAS100/USD",
    "GER40": "GER40/EUR",
    "DE40": "GER40/EUR",
    "UK100": "UK100/GBP",
    "SPX500": "SPX500/USD",
    "US500": "SPX500/USD",
}


# ── Report / update detection ───────────────────────────────────────────────
# Messages containing these patterns are recaps of trades already closed
# or updates to existing positions — NOT new actionable signals.

_REPORT_KEYWORDS_RE = re.compile(
    r"\b("
    r"closed|chiuso|chiusa|"
    r"hit\s+(?:tp|sl|target|stop)|tp\s*\d*\s*hit|sl\s*hit|"
    r"reached|raggiunto|raggiunta|"
    r"profit|profitto|loss\s+taken|"
    r"breakeven|break\s*even|moved?\s+(?:sl|stop)\s+to|"
    r"running\s+in\s+profit|"
    r"update|aggiornamento|"
    r"result|risultat[oi]|"
    r"pips?\s+(?:gain|profit|won|earned)|"
    r"\+\d+\s*pips?"
    r")\b",
    re.IGNORECASE,
)


def is_report_message(text: str) -> bool:
    """Return True if the message is a report/update, not a live signal."""
    return bool(_REPORT_KEYWORDS_RE.search(text))


# ── Regex patterns ──────────────────────────────────────────────────────────

# Standard symbol with quote currency: BTC/USDT, EURUSD, GBP-JPY
_SYMBOL_RE = re.compile(
    r"(?:#?\b)([A-Z]{2,10})[/\-_]?"
    r"(USDT|BTC|ETH|BUSD|USD|EUR|GBP|JPY|CAD|CHF|AUD|NZD)\b",
    re.IGNORECASE,
)

# Bare commodity / index name (no quote currency)
_COMMODITY_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _COMMODITY_ALIASES) + r")\b",
    re.IGNORECASE,
)

_DIRECTION_BUY_RE = re.compile(
    r"\b(buy|long|compra|acquisto|buy[_\s-]?limit|buy[_\s-]?stop)\b",
    re.IGNORECASE,
)
_DIRECTION_SELL_RE = re.compile(
    r"\b(sell|short|vendi|vendita|sell[_\s-]?limit|sell[_\s-]?stop)\b",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(r"\b(\d{1,10}(?:[.,]\d+)?)\b")

# Entry price — multiple label variants from different channels
_ENTRY_RE = re.compile(
    r"(?:"
    r"entry\s*(?:level|price)?|"
    r"entra|enter|"
    r"zona|zone|"
    r"price|"
    r"buy\s*entry|sell\s*entry|"
    r"open(?:ing)?\s*price"
    r")[:\s\-@]+(\d{1,10}(?:[.,]\d+)?)",
    re.IGNORECASE,
)

# Stop loss — including "stoploss" (no space), "safe stop loss"
_SL_RE = re.compile(
    r"(?:"
    r"sl|"
    r"safe\s*stop\s*loss|"
    r"(?:my\s+)?stop\s*loss|"
    r"stoploss|"
    r"stop"
    r")[:\s\-@]+(\d{1,10}(?:[.,]\d+)?)",
    re.IGNORECASE,
)

# Take profit — including "goal", "target level", "target" (no digit)
_TP_RE = re.compile(
    r"(?:"
    r"tp\d*|"
    r"target\s*(?:level\s*)?\d*|"
    r"take[_\s-]?profit\s*\d*|"
    r"goal\s*\d*"
    r")[:\s\-@]+(\d{1,10}(?:[.,]\d+)?)",
    re.IGNORECASE,
)


def _parse_number(s: str) -> float:
    return float(s.replace(",", "."))


def _extract_symbol(text: str) -> str | None:
    """Try to find a symbol: first standard pair, then commodity alias."""
    sym_match = _SYMBOL_RE.search(text)
    if sym_match:
        base = sym_match.group(1).upper()
        quote = sym_match.group(2).upper()
        return f"{base}/{quote}"

    # Try commodity / index aliases
    com_match = _COMMODITY_RE.search(text)
    if com_match:
        alias = com_match.group(1).upper()
        return _COMMODITY_ALIASES.get(alias)

    return None


def parse_signal(text: str, source: str) -> TelegramSignal | None:
    """Try to extract a trading signal from a message.

    Returns None if:
    - No symbol is found
    - Direction is ambiguous (both buy and sell, or neither)
    - The message is a report/update (not a live signal)
    """
    if not text:
        return None

    # Filter out reports and updates
    if is_report_message(text):
        return None

    # Symbol
    symbol = _extract_symbol(text)
    if not symbol:
        return None

    # Direction
    is_buy = bool(_DIRECTION_BUY_RE.search(text))
    is_sell = bool(_DIRECTION_SELL_RE.search(text))
    if is_buy == is_sell:  # both or neither → ambiguous
        return None
    direction: Literal["BUY", "SELL"] = "BUY" if is_buy else "SELL"

    # Entry — try labeled pattern first ("entry: 1.38350"), then
    # fall back to a price directly after the direction keyword on the
    # first line ("SELL 1.38350"), common in Forex signal groups.
    entry: float | None = None
    entry_match = _ENTRY_RE.search(text)
    if entry_match:
        entry = _parse_number(entry_match.group(1))
    else:
        _inline_entry = re.search(
            r"(?:buy|long|sell|short)\s+(?:limit\s+|stop\s+)?(?:@\s*)?(\d{1,10}(?:[.,]\d+)?)",
            text.split("\n")[0],
            re.IGNORECASE,
        )
        if _inline_entry:
            entry = _parse_number(_inline_entry.group(1))

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
