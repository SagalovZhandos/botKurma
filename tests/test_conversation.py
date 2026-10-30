from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from telegram.constants import ChatType

from bot import conversation
from bot.conversation import AmbientState, LogEntry
from bot.handlers import chat
from bot.services.ai import AIClient
from tests.conftest import FakeBot


def tg_message(text="привет", user_id=1, name="Айдос", is_bot=False, reply_to=None, caption=None):
    return SimpleNamespace(
        text=text, caption=caption, chat_id=-100,
        chat=SimpleNamespace(type=ChatType.SUPERGROUP),
        from_user=SimpleNamespace(id=user_id, first_name=name, is_bot=is_bot, username=None),
        reply_to_message=reply_to,
    )


def update_for(message):
    return SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=-100, type=message.chat.type),
        effective_user=message.from_user,
    )


class TestLogic:
    def test_append_trims_and_limits(self):
        log = ()
        for i in range(conversation.LOG_LIMIT + 5):
            log = conversation.append(log, LogEntry("A", str(i)))
        assert len(log) == conversation.LOG_LIMIT and log[-1].text == str(conversation.LOG_LIMIT + 4)
        long = conversation.append((), LogEntry("A", "x" * 2000))
        assert len(long[0].text) == conversation.ENTRY_CHAR_LIMIT

    def test_to_messages_roles_and_budget(self):
        log = (LogEntry("Дана", "старое " * 50), LogEntry("Айдос", "привет"), LogEntry("бот", "салем!", True))
        messages = conversation.to_messages(log)
        assert [m.role for m in messages] == ["user", "user", "assistant"]
        assert messages[1].content == "Айдос: привет" and messages[2].content == "салем!"
        short = conversation.to_messages(log, max_chars=40)
        assert [m.content for m in short] == ["Айдос: привет", "салем!"]

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("SKIP", None), (" skip. ", None), ("SKIP — нечего добавить", None), ("", None),
         ("Бот: Попробуйте плов в Чайхане!", "Попробуйте плов в Чайхане!"), ("Ха-ха, жиза 😄", "Ха-ха, жиза 😄")],
    )
    def test_parse_ambient_reply(self, raw, expected):
        assert conversation.parse_ambient_reply(raw) == expected

    def test_should_check_respects_cooldown_and_budget(self):
        normal = conversation.MODES["normal"]
        state = AmbientState()
        assert conversation.should_check(state, normal, 1000.0)
        assert not conversation.should_check(state.with_reply(1000.0), normal, 1100.0)
        assert conversation.should_check(state.with_reply(1000.0), normal, 1000.0 + normal.cooldown)
        busy = AmbientState(checks=tuple(float(i) for i in range(normal.checks_per_hour)))
        assert not conversation.should_check(busy, normal, 100.0)
        assert conversation.should_check(busy, normal, 100.0 + conversation.HOUR)  # старые проверки истекли
        assert not conversation.should_check(state, conversation.MODES["off"], 1000.0)

    def test_resolve_mode_and_now_line(self):
        assert conversation.resolve_mode("Тихо").key == "quiet"
        assert conversation.resolve_mode("active").key == "active"
        assert conversation.resolve_mode("громко") is None
        assert conversation.now_line(datetime(2026, 10, 30, 17, 5)) == "Сейчас Жұма, 30 октября 2026, 17:05 (Алматы)."


class TestLogging:
    def test_log_entry_for(self):
        assert chat.log_entry_for(tg_message("/digest"), 999) is None
        assert chat.log_entry_for(tg_message(is_bot=True), 999) is None
        assert chat.log_entry_for(tg_message(text=None, caption="закат"), 999).text == "[фото] закат"
        dana = SimpleNamespace(from_user=SimpleNamespace(id=2, first_name="Дана"))
        assert chat.log_entry_for(tg_message("да", reply_to=dana), 999).text == "(в ответ Дана) да"
        to_bot = SimpleNamespace(from_user=SimpleNamespace(id=999, first_name="bot"))
        assert chat.log_entry_for(tg_message("спасибо", reply_to=to_bot), 999).text == "(в ответ тебе) спасибо"

    async def test_log_message_only_in_allowed_chats(self, fake_context):
        ctx = fake_context()
        await chat.log_message(update_for(tg_message("всем привет")), ctx)
        assert ctx.chat_data[chat.LOG_KEY] == (LogEntry("Айдос", "всем привет"),)
        foreign = update_for(tg_message("чужой чат"))
        foreign.effective_chat = SimpleNamespace(id=-555, type=ChatType.SUPERGROUP)
        other = fake_context()
        await chat.log_message(foreign, other)
        assert chat.LOG_KEY not in other.chat_data


class TestAmbient:
    async def test_unaddressed_message_schedules_check(self, fake_context):
        ctx = fake_context()
        await chat.text_message(update_for(tg_message("кто идёт в кино?")), ctx)
        await chat.text_message(update_for(tg_message("я иду")), ctx)
        assert [s[2:] for s in ctx.job_queue.scheduled] == [(-100, "ambient--100")] * 2
        assert ctx.job_queue.scheduled[0][1] == conversation.MODES["normal"].delay
        assert ctx.job_queue.removed == 1  # первая проверка перенесена

    async def test_mode_off_does_not_schedule(self, fake_context):
        ctx = fake_context()
        ctx.chat_data[chat.MODE_KEY] = "off"
        await chat.text_message(update_for(tg_message("кто идёт в кино?")), ctx)
        assert ctx.job_queue.scheduled == []

    def job_context(self, fake_context, log):
        bot = FakeBot()
        ctx = fake_context(bot)
        ctx.job = SimpleNamespace(chat_id=-100)
        ctx.chat_data[chat.LOG_KEY] = log
        return ctx, bot

    async def test_ambient_reply_is_sent_and_remembered(self, fake_context):
        ctx, bot = self.job_context(fake_context, (LogEntry("Айдос", "где поесть плов?"),))
        await chat.ambient_job(ctx)
        assert bot.calls == [("send_message", -100, "Ответ AI")]
        assert ctx.chat_data[chat.LOG_KEY][-1] == LogEntry("бот", "Ответ AI", True)
        # сразу после реплики бот не будет вмешиваться снова (кулдаун)
        ctx.chat_data[chat.LOG_KEY] = (*ctx.chat_data[chat.LOG_KEY], LogEntry("Дана", "спасибо"))
        await chat.ambient_job(ctx)
        assert len(bot.calls) == 1

    async def test_ambient_skip(self, fake_context):
        ctx, bot = self.job_context(fake_context, (LogEntry("Айдос", "ок"),))
        with patch.object(AIClient, "chat", AsyncMock(return_value="SKIP")) as ai_chat:
            await chat.ambient_job(ctx)
        assert bot.calls == []
        assert ai_chat.await_args.kwargs["primary_only"] is True  # не тратим запасной лимит
        assert ai_chat.await_args.kwargs["reasoning"] == "medium"
        assert len(ctx.chat_data[chat.AMBIENT_KEY].checks) == 1

    async def test_ambient_silent_when_bot_spoke_last(self, fake_context):
        ctx, bot = self.job_context(fake_context, (LogEntry("бот", "я тут", True),))
        await chat.ambient_job(ctx)
        assert bot.calls == []


class TestModeCommand:
    async def test_show_and_set(self, fake_context):
        from tests.test_handlers import FakeMessage, make_update

        ctx = fake_context()
        show = FakeMessage("/mode")
        await chat.mode_command(make_update(show), ctx)
        assert "обычно" in show.replies[0]
        ctx.args = ["тихо"]
        done = FakeMessage("/mode тихо")
        await chat.mode_command(make_update(done), ctx)
        assert ctx.chat_data[chat.MODE_KEY] == "quiet" and "тихо" in done.replies[0]
