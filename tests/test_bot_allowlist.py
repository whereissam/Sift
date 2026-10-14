"""The Telegram bot serves only the operator's allowed users.

Regression tests for the security audit: every handler was registered with
no user filter, so any Telegram user who found the bot could run downloads
with the operator's cookies, disk and transcription compute.
"""

from types import SimpleNamespace

import pytest
from telegram import Update
from telegram.ext import ApplicationHandlerStop, TypeHandler

from app.bot.bot import SiftBot
from app.config import Settings


def _bot(monkeypatch, allowed: str) -> SiftBot:
    settings = Settings(telegram_allowed_user_ids=allowed)
    monkeypatch.setattr("app.bot.bot.get_settings", lambda: settings)
    return SiftBot(token="123456:TEST-TOKEN")


def _message_update(user_id: int):
    replies = []

    async def reply_text(text, **kwargs):
        replies.append(text)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        callback_query=None,
        effective_message=SimpleNamespace(reply_text=reply_text),
    )
    return update, replies


class TestAllowedIds:
    def test_parses_comma_separated_ids(self):
        s = Settings(telegram_allowed_user_ids="111, 222,,abc,-100333")
        assert s.telegram_allowed_ids() == {111, 222, -100333}

    def test_empty_means_nobody(self):
        assert Settings(telegram_allowed_user_ids="").telegram_allowed_ids() == frozenset()


class TestGate:
    async def test_stranger_is_stopped_and_told_their_id(self, monkeypatch):
        bot = _bot(monkeypatch, "111")
        update, replies = _message_update(999999999)
        with pytest.raises(ApplicationHandlerStop):
            await bot._require_allowed_user(update, None)
        assert replies == ["This bot is private. Your Telegram user ID is 999999999."]

    async def test_allowed_user_passes(self, monkeypatch):
        bot = _bot(monkeypatch, "111")
        update, replies = _message_update(111)
        await bot._require_allowed_user(update, None)
        assert replies == []

    async def test_empty_allowlist_refuses_everyone(self, monkeypatch):
        bot = _bot(monkeypatch, "")
        update, _ = _message_update(111)
        with pytest.raises(ApplicationHandlerStop):
            await bot._require_allowed_user(update, None)

    async def test_stranger_callback_is_stopped(self, monkeypatch):
        bot = _bot(monkeypatch, "111")
        answered = []

        async def answer(*args, **kwargs):
            answered.append(True)

        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=999),
            callback_query=SimpleNamespace(answer=answer),
            effective_message=None,
        )
        with pytest.raises(ApplicationHandlerStop):
            await bot._require_allowed_user(update, None)
        assert answered == [True]


def test_gate_runs_before_every_handler(monkeypatch):
    app = _bot(monkeypatch, "111").build_application()
    first_group = min(app.handlers)
    assert first_group < 0
    (gate,) = app.handlers[first_group]
    assert isinstance(gate, TypeHandler) and gate.type is Update
    assert all(group > first_group for group in app.handlers if group != first_group)
