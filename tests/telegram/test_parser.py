"""Tests for Telegram signal parser."""

from decimal import Decimal

from trdex.telegram.parser import is_report_message, parse_signal
from trdex.telegram.tracker import SignalOutcome, SignalTracker


# ── Parser tests (original) ─────────────────────────────────────────────────

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


# ── Commodity / index aliases ────────────────────────────────────────────────

def test_parse_gold_alias() -> None:
    msg = "GOLD BUY 2350\nSL: 2340\nTP: 2370"
    sig = parse_signal(msg, source="@gold_ch")
    assert sig is not None
    assert sig.symbol == "XAU/USD"
    assert sig.direction == "BUY"
    assert sig.entry == 2350.0


def test_parse_xauusd_alias() -> None:
    msg = "XAUUSD SELL 2350\nSL: 2365\nTP: 2330"
    sig = parse_signal(msg, source="@gold_ch")
    assert sig is not None
    assert sig.symbol == "XAU/USD"
    assert sig.direction == "SELL"


def test_parse_usoil_alias() -> None:
    msg = "USOIL BUY 72.50\nTP: 73.00\nSL: 72.00"
    sig = parse_signal(msg, source="@oil_ch")
    assert sig is not None
    assert sig.symbol == "WTI/USD"


def test_parse_nas100_alias() -> None:
    msg = "NAS100 SELL 18500\nSL: 18600\nTP: 18300"
    sig = parse_signal(msg, source="@index_ch")
    assert sig is not None
    assert sig.symbol == "NAS100/USD"


def test_parse_ger40_alias() -> None:
    msg = "GER40 SELL-LIMIT @23968\nSL: 24063\nTP1: 23913"
    sig = parse_signal(msg, source="@index_ch")
    assert sig is not None
    assert sig.symbol == "GER40/EUR"
    assert sig.direction == "SELL"


def test_parse_brent_alias() -> None:
    msg = "BRENT BUY 75.00\nTP: 76.00\nSL: 74.50"
    sig = parse_signal(msg, source="@oil_ch")
    assert sig is not None
    assert sig.symbol == "BRENT/USD"


# ── Extended label patterns ──────────────────────────────────────────────────

def test_parse_entry_level_label() -> None:
    """EliteTradingSignals format: 'Entry Level: 0.923'."""
    msg = "USDCHF\nSELL\nEntry Level: 0.923\nTarget Level: 0.921\nStop Loss: 0.924"
    sig = parse_signal(msg, source="@elite")
    assert sig is not None
    assert sig.entry == 0.923
    assert sig.stop_loss == 0.924
    assert 0.921 in sig.targets


def test_parse_goal_as_tp() -> None:
    """AnabelSignals format: 'Goal - 4728.4'."""
    msg = "XAUUSD SELL\nGoal - 4728.4\nMy Stop Loss - 4746.4"
    sig = parse_signal(msg, source="@anabel")
    assert sig is not None
    assert sig.symbol == "XAU/USD"
    assert 4728.4 in sig.targets


def test_parse_stoploss_no_space() -> None:
    """Jacob Crypto format: 'STOPLOSS: 0.09559'."""
    msg = "#ARPA/USDT\n#Long\nEntry: 0.10089\nTarget 1: 0.10217\nStoploss: 0.09559"
    sig = parse_signal(msg, source="@jacob")
    assert sig is not None
    assert sig.symbol == "ARPA/USDT"
    assert sig.direction == "BUY"
    assert sig.entry == 0.10089
    assert sig.stop_loss == 0.09559
    assert 0.10217 in sig.targets


def test_parse_safe_stop_loss() -> None:
    """AnabelSignals format: 'Safe Stop Loss - 1.1724'."""
    msg = "EURUSD SELL\nGoal - 1.1680\nSafe Stop Loss - 1.1724"
    sig = parse_signal(msg, source="@anabel")
    assert sig is not None
    assert sig.stop_loss == 1.1724


def test_parse_buy_entry_label() -> None:
    msg = "XAUUSD\nBuy Entry: 2350\nSL: 2340\nTP: 2370"
    sig = parse_signal(msg, source="@gold_ch")
    assert sig is not None
    assert sig.entry == 2350.0


def test_parse_sell_entry_label() -> None:
    msg = "XAUUSD\nSell Entry: 48200\nSL: 48500\nTP: 47800"
    sig = parse_signal(msg, source="@oil_ch")
    assert sig is not None
    assert sig.entry == 48200.0


def test_parse_buy_limit_direction() -> None:
    msg = "EURUSD BUY LIMIT 1.0850\nSL: 1.0820\nTP: 1.0900"
    sig = parse_signal(msg, source="@fx_ch")
    assert sig is not None
    assert sig.direction == "BUY"
    assert sig.entry == 1.0850


def test_parse_sell_limit_direction() -> None:
    msg = "GER40 SELL-LIMIT @23968\nSL: 24063\nTP1: 23913"
    sig = parse_signal(msg, source="@index_ch")
    assert sig is not None
    assert sig.direction == "SELL"


def test_parse_at_sign_entry() -> None:
    """Wolf FX format: 'buy limit @ 1.1862'."""
    msg = "EURUSD buy limit @ 1.1862\ntp @ 1.1870\nSL @ 1.1856"
    sig = parse_signal(msg, source="@wolffx")
    assert sig is not None
    assert sig.entry == 1.1862


def test_parse_hash_symbol_prefix() -> None:
    """Some channels prefix with #: '#ARPA/USDT'."""
    msg = "#BTC/USDT\nBUY\nEntry: 67000\nTP: 68000\nSL: 65000"
    sig = parse_signal(msg, source="@hashch")
    assert sig is not None
    assert sig.symbol == "BTC/USDT"


# ── Report / update filter ───────────────────────────────────────────────────

def test_report_closed_message_filtered() -> None:
    msg = "XAUUSD SELL\nClosed in profit +50 pips"
    assert is_report_message(msg) is True
    assert parse_signal(msg, source="@ch") is None


def test_report_tp_hit_filtered() -> None:
    msg = "EURUSD BUY\nTP1 Hit! +30 pips profit"
    assert is_report_message(msg) is True
    assert parse_signal(msg, source="@ch") is None


def test_report_sl_hit_filtered() -> None:
    msg = "GBPJPY SELL\nSL Hit. Loss taken -25 pips"
    assert is_report_message(msg) is True


def test_report_breakeven_filtered() -> None:
    msg = "XAUUSD BUY\nMoved SL to breakeven"
    assert is_report_message(msg) is True


def test_report_result_filtered() -> None:
    msg = "EURUSD BUY\nResult: +45 pips gained"
    assert is_report_message(msg) is True


def test_report_pips_gained_filtered() -> None:
    msg = "GOLD BUY\n+120 pips profit on this signal"
    assert is_report_message(msg) is True


def test_report_italian_filtered() -> None:
    msg = "XAUUSD SELL\nChiuso in profitto +50 pips"
    assert is_report_message(msg) is True


def test_live_signal_not_filtered() -> None:
    """A real live signal must NOT be detected as report."""
    msg = "XAUUSD BUY 2350\nSL: 2340\nTP: 2370"
    assert is_report_message(msg) is False
    sig = parse_signal(msg, source="@ch")
    assert sig is not None


def test_empty_text_returns_none() -> None:
    assert parse_signal("", source="@ch") is None
    assert parse_signal(None, source="@ch") is None  # type: ignore[arg-type]


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
