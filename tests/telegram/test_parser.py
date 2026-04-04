"""Tests for Telegram signal parser."""

from decimal import Decimal

from trdex.telegram.parser import parse_signal
from trdex.telegram.tracker import SignalOutcome, SignalTracker


# ── Parser tests ─────────────────────────────────────────────────────────────

def test_parse_buy_signal_with_targets() -> None:
    msg = "BTC/USDT BUY\nEntry: 67000\nTP1: 68000\nTP2: 70000\nSL: 65000"
    sig = parse_signal(msg, source="@testchannel")
    assert sig is not None
    assert sig.symbol == "BTC/USDT"
    assert sig.direction == "BUY"
    assert sig.entry == 67000.0
    assert sig.stop_loss == 65000.0
    assert len(sig.targets) == 2


def test_parse_sell_signal() -> None:
    msg = "ETH/USDT SELL\nEntry: 3500\nSL: 3600\nTP: 3200"
    sig = parse_signal(msg, source="@testchannel")
    assert sig is not None
    assert sig.direction == "SELL"
    assert sig.symbol == "ETH/USDT"


def test_parse_no_symbol_returns_none() -> None:
    sig = parse_signal("Buy the dip! Market looks good.", source="@noise")
    assert sig is None


def test_parse_ambiguous_direction_returns_none() -> None:
    msg = "BTC/USDT — buy or sell? Not sure!"
    sig = parse_signal(msg, source="@confused")
    assert sig is None


def test_parse_italian_signal() -> None:
    msg = "SOL/USDT\nCompra zona 140\nTP1: 155\nTP2: 170\nSL: 130"
    sig = parse_signal(msg, source="@italian_channel")
    assert sig is not None
    assert sig.direction == "BUY"
    assert sig.symbol == "SOL/USDT"


# ── SignalTracker tests ───────────────────────────────────────────────────────

def test_tracker_win_rate() -> None:
    tracker = SignalTracker(default_budget=Decimal("100"))
    tracker.record(SignalOutcome(
        source="@ch", symbol="BTC/USDT", direction="BUY",
        entry_price=Decimal("60000"), exit_price=Decimal("62000"),
        budget=Decimal("100"),
    ))
    tracker.record(SignalOutcome(
        source="@ch", symbol="BTC/USDT", direction="BUY",
        entry_price=Decimal("60000"), exit_price=Decimal("58000"),
        budget=Decimal("100"),
    ))
    stats = tracker.stats("@ch")
    assert stats.total_signals == 2
    assert stats.wins == 1
    assert stats.losses == 1
    assert stats.win_rate == 0.5


def test_tracker_pnl_buy() -> None:
    outcome = SignalOutcome(
        source="@ch", symbol="BTC/USDT", direction="BUY",
        entry_price=Decimal("50000"), exit_price=Decimal("55000"),
        budget=Decimal("100"),
    )
    # qty = 100/50000 = 0.002 BTC; pnl = (55000-50000)*0.002 = 10
    assert outcome.pnl == Decimal("10")


def test_tracker_report_sorted_by_roi() -> None:
    tracker = SignalTracker()
    tracker.record(SignalOutcome(
        source="@bad", symbol="BTC/USDT", direction="BUY",
        entry_price=Decimal("60000"), exit_price=Decimal("58000"),
        budget=Decimal("100"),
    ))
    tracker.record(SignalOutcome(
        source="@good", symbol="ETH/USDT", direction="BUY",
        entry_price=Decimal("3000"), exit_price=Decimal("3300"),
        budget=Decimal("100"),
    ))
    report = tracker.report()
    assert report[0].source == "@good"
    assert report[1].source == "@bad"
