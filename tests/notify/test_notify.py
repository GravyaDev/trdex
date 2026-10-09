"""Operator notifications: channels, per-event routing, kill switch hook."""

from __future__ import annotations

import asyncio
import json
import smtplib
from typing import ClassVar

import httpx
import pytest

from trdex.notify.channels import EmailChannel, NotificationError, TelegramBotChannel
from trdex.notify.events import DEFAULT_ROUTES, Event
from trdex.notify.service import Notifier, build_channel, notify_background, route_for

TOKEN = "123456:SECRET-TOKEN"


def _telegram(handler, **kw):
    transport = httpx.MockTransport(handler)
    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    ch = TelegramBotChannel(
        TOKEN,
        "42",
        client_factory=lambda **k: httpx.AsyncClient(transport=transport, **k),
        sleep=fake_sleep,
        **kw,
    )
    return ch, sleeps


# ── Telegram ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_telegram_sends_subject_and_body_to_the_chat():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={"ok": True})

    ch, _ = _telegram(handler)
    await ch.send("Kill switch", "drawdown 21%")
    assert seen[0].url.path == f"/bot{TOKEN}/sendMessage"
    payload = json.loads(seen[0].content)
    assert payload["chat_id"] == "42"
    assert payload["text"] == "Kill switch\n\ndrawdown 21%"


@pytest.mark.asyncio
async def test_telegram_honours_retry_after_on_429():
    calls = iter(
        [
            httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 7}}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    ch, sleeps = _telegram(lambda req: next(calls))
    await ch.send("s", "b")
    assert sleeps == [7.0]


@pytest.mark.asyncio
async def test_telegram_client_errors_fail_fast_without_leaking_the_token():
    attempts = []

    def handler(req):
        attempts.append(req)
        return httpx.Response(401, json={"ok": False, "description": f"Unauthorized {TOKEN}"})

    ch, sleeps = _telegram(handler)
    with pytest.raises(NotificationError) as exc:
        await ch.send("s", "b")
    assert len(attempts) == 1 and sleeps == []
    assert "SECRET-TOKEN" not in str(exc.value)
    assert "401" in str(exc.value)


@pytest.mark.asyncio
async def test_telegram_retries_network_and_5xx_with_backoff_then_gives_up():
    responses = iter([httpx.ConnectError("boom"), httpx.Response(502, json={})])

    def handler(req):
        r = next(responses, httpx.Response(503, json={}))
        if isinstance(r, Exception):
            raise r
        return r

    ch, sleeps = _telegram(handler, max_attempts=3, base_delay=1.0)
    with pytest.raises(NotificationError) as exc:
        await ch.send("s", "b")
    assert sleeps == [1.0, 2.0]
    assert "gave up after 3 attempts" in str(exc.value)


@pytest.mark.asyncio
async def test_telegram_truncates_to_the_api_limit():
    seen = []

    def handler(req):
        seen.append(json.loads(req.content)["text"])
        return httpx.Response(200, json={"ok": True})

    ch, _ = _telegram(handler)
    await ch.send("s", "x" * 5000)
    assert len(seen[0]) == 4096


# ── Email ─────────────────────────────────────────────────────────────────


class FakeSMTP:
    instances: ClassVar[list[FakeSMTP]] = []
    fail_with: ClassVar[Exception | None] = None

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port
        self.ops: list[str] = []
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.ops.append("starttls")

    def login(self, user, pw):
        self.ops.append(f"login:{user}")
        if FakeSMTP.fail_with:
            raise FakeSMTP.fail_with

    def send_message(self, msg):
        self.sent.append(msg)


@pytest.fixture
def fake_smtp():
    FakeSMTP.instances = []
    FakeSMTP.fail_with = None
    return FakeSMTP


def _email(security="starttls", **kw):
    async def no_sleep(_):
        return None

    return EmailChannel(
        host="smtp.example.com",
        port=587,
        sender="bot@example.com",
        recipients=["me@example.com", "ops@example.com"],
        username="bot",
        password="pw-secret",
        security=security,
        smtp_factory=FakeSMTP,
        smtp_ssl_factory=FakeSMTP,
        sleep=no_sleep,
        **kw,
    )


@pytest.mark.asyncio
async def test_email_starttls_login_and_send(fake_smtp):
    await _email().send("Readiness changed", "NOT READY: bounds stale")
    smtp = fake_smtp.instances[0]
    assert smtp.ops == ["starttls", "login:bot"]
    msg = smtp.sent[0]
    assert msg["Subject"] == "[trdex] Readiness changed"
    assert msg["To"] == "me@example.com, ops@example.com"
    assert "bounds stale" in msg.get_content()


@pytest.mark.asyncio
async def test_email_auth_error_is_not_retried_and_password_is_redacted(fake_smtp):
    fake_smtp.fail_with = smtplib.SMTPAuthenticationError(535, b"bad pw-secret")
    with pytest.raises(NotificationError) as exc:
        await _email().send("s", "b")
    assert len(fake_smtp.instances) == 1
    assert "pw-secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_email_transient_error_is_retried(fake_smtp):
    fake_smtp.fail_with = smtplib.SMTPServerDisconnected("dropped")
    with pytest.raises(NotificationError):
        await _email(max_attempts=2).send("s", "b")
    assert len(fake_smtp.instances) == 2


# ── routing ───────────────────────────────────────────────────────────────


class Cfg:
    def __init__(self, **values):
        self.v = values  # keys "category.key"

    def get(self, category, key, default=""):
        return self.v.get(f"{category}.{key}", default)


TG = {"credentials.telegram_bot_token": TOKEN, "notifications.telegram_bot_chat_id": "42"}
MAIL = {
    "notifications.smtp_host": "smtp.example.com",
    "notifications.email_from": "bot@example.com",
    "notifications.email_to": "me@example.com",
}


def test_routes_default_per_event_and_reject_garbage():
    assert route_for(Cfg(), Event.KILL_SWITCH) == "both"
    assert route_for(Cfg(), Event.REGIME_REFRESHED) == "telegram"
    assert (
        route_for(Cfg(**{"notifications.route_kill_switch": "email"}), Event.KILL_SWITCH)
        == "email"
    )
    assert (
        route_for(Cfg(**{"notifications.route_kill_switch": "sms"}), Event.KILL_SWITCH) == "both"
    )
    assert set(DEFAULT_ROUTES) == set(Event)


def test_channels_need_complete_settings():
    assert build_channel(Cfg(), "telegram") is None
    assert build_channel(Cfg(**TG), "telegram") is not None
    assert build_channel(Cfg(**{**MAIL, "notifications.email_to": " , "}), "email") is None
    email = build_channel(Cfg(**{**MAIL, "notifications.smtp_security": "ssl"}), "email")
    assert email is not None and email._port == 465


class Recorder:
    def __init__(self, name, fail=False):
        self.name, self.fail, self.sent = name, fail, []

    async def send(self, subject, body):
        if self.fail:
            raise NotificationError(f"{self.name} down")
        self.sent.append((subject, body))


@pytest.mark.asyncio
async def test_both_route_delivers_on_each_configured_channel(monkeypatch):
    chans = {"telegram": Recorder("telegram"), "email": Recorder("email")}
    monkeypatch.setattr("trdex.notify.service.build_channel", lambda cfg, n: chans[n])
    out = await Notifier(lambda: Cfg()).notify(Event.KILL_SWITCH, "s", "b")
    assert out == {"telegram": "sent", "email": "sent"}
    assert chans["telegram"].sent == chans["email"].sent == [("s", "b")]


@pytest.mark.asyncio
async def test_one_channel_down_does_not_stop_the_other_nor_raise(monkeypatch):
    chans = {"telegram": Recorder("telegram", fail=True), "email": Recorder("email")}
    monkeypatch.setattr("trdex.notify.service.build_channel", lambda cfg, n: chans[n])
    out = await Notifier(lambda: Cfg()).notify(Event.READINESS_CHANGED, "s", "b")
    assert out["telegram"].startswith("error") and out["email"] == "sent"


@pytest.mark.asyncio
async def test_route_none_and_unconfigured_channels_send_nothing(monkeypatch):
    none = Cfg(**{"notifications.route_regime_refreshed": "none"})
    assert await Notifier(lambda: none).notify(Event.REGIME_REFRESHED, "s", "b") == {}
    out = await Notifier(lambda: Cfg()).notify(Event.KILL_SWITCH, "s", "b")
    assert out == {"telegram": "not configured", "email": "not configured"}


@pytest.mark.asyncio
async def test_notify_background_runs_without_blocking(monkeypatch):
    got = []

    async def fake_notify(event, subject, body):
        got.append(event)

    monkeypatch.setattr("trdex.notify.service.notify", fake_notify)
    notify_background(Event.KILL_SWITCH, "s", "b")
    await asyncio.sleep(0)
    assert got == [Event.KILL_SWITCH]


# ── kill switch hook ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kill_switch_activation_notifies_once(monkeypatch):
    from trdex.risk.stop_loss import KillSwitch

    sent = []
    monkeypatch.setattr(
        "trdex.notify.notify_background", lambda ev, subject, body: sent.append((ev, body))
    )
    ks = KillSwitch()
    await ks.activate_async("portfolio drawdown 21% > 20%")
    await ks.activate_async("again")  # already active: no second message
    assert len(sent) == 1
    assert sent[0][0] == Event.KILL_SWITCH and "drawdown 21%" in sent[0][1]
