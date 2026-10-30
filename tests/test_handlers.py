from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from telegram.constants import ChatType
from telegram.error import BadRequest, NetworkError

from bot.handlers import access, chat, daily, games, images
from bot.health import start_health_server
from bot.services.images import ImageError
from bot.main import build_application, read_env_file
from tests.conftest import FakeBot


class FakeMessage:
    def __init__(self, text: str = "", chat_type: str = ChatType.SUPERGROUP, reply_to=None):
        self.text = text
        self.caption = None
        self.chat = SimpleNamespace(type=chat_type)
        self.chat_id = -100
        self.reply_to_message = reply_to
        self.replies: list[str] = []
        self.photos: list[tuple[bytes, str]] = []
        self.deleted = 0

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)
        return self

    async def reply_photo(self, photo, caption=None, **kwargs):
        self.photos.append((photo, caption))

    async def delete(self):
        self.deleted += 1


def make_update(message: FakeMessage, chat_id: int = -100, user_id: int = 1):
    return SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=chat_id, type=message.chat.type),
        effective_user=SimpleNamespace(id=user_id, first_name="Айдос", username="aidos", is_bot=False),
    )


class TestChatHelpers:
    def test_split_text(self):
        assert chat.split_text("abcdef", 4) == ("abcd", "ef")
        assert chat.split_text("") == ("…",)

    def test_strip_mention(self):
        assert chat.strip_mention("@Friends_Bot, как дела?", "friends_bot") == "как дела?"

    def test_addressed(self):
        bot_reply = SimpleNamespace(from_user=SimpleNamespace(id=999))
        assert chat.is_addressed_to_bot(FakeMessage("привет", ChatType.PRIVATE), 999, "b")
        assert chat.is_addressed_to_bot(FakeMessage("ну", reply_to=bot_reply), 999, "b")
        assert chat.is_addressed_to_bot(FakeMessage("эй @B ответь"), 999, "b")
        assert not chat.is_addressed_to_bot(FakeMessage("просто болтаем"), 999, "b")

    def test_draw_intent(self):
        match = chat.DRAW_INTENT.match("Нарисуй, кота в шапке")
        assert match and "Нарисуй, кота в шапке"[match.end():] == "кота в шапке"
        assert chat.DRAW_INTENT.match("что нарисуешь?") is None


class TestAccess:
    async def test_group_in_list_allowed(self, fake_context):
        assert await access.is_allowed(make_update(FakeMessage()), fake_context())

    async def test_foreign_group_denied(self, fake_context):
        assert not await access.is_allowed(make_update(FakeMessage(), chat_id=-555), fake_context())

    async def test_private_admin_and_member(self, fake_context):
        private = FakeMessage(chat_type=ChatType.PRIVATE)
        assert await access.is_allowed(make_update(private, chat_id=7, user_id=7), fake_context())

        bot = FakeBot()
        statuses = {42: "member", 43: "left"}

        async def get_chat_member(chat_id, user_id):
            return SimpleNamespace(status=statuses[user_id])

        bot.get_chat_member = get_chat_member
        ctx = fake_context(bot)
        assert await access.is_allowed(make_update(private, chat_id=42, user_id=42), ctx)
        assert not await access.is_allowed(make_update(private, chat_id=43, user_id=43), ctx)
        assert ctx.application.bot_data[access.MEMBER_CACHE_KEY][43][0] is False

    async def test_network_error_not_cached_and_muted_member_allowed(self, fake_context):
        bot = FakeBot()
        outcomes = {50: [NetworkError("timeout"), SimpleNamespace(status="member")],
                    51: [SimpleNamespace(status="restricted", is_member=True)],
                    52: [BadRequest("user not found")]}

        async def get_chat_member(chat_id, user_id):
            result = outcomes[user_id].pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        bot.get_chat_member = get_chat_member
        ctx = fake_context(bot)
        private = FakeMessage(chat_type=ChatType.PRIVATE)
        assert not await access.is_allowed(make_update(private, chat_id=50, user_id=50), ctx)
        assert 50 not in ctx.application.bot_data[access.MEMBER_CACHE_KEY]
        assert await access.is_allowed(make_update(private, chat_id=50, user_id=50), ctx)  # повтор прошёл
        assert await access.is_allowed(make_update(private, chat_id=51, user_id=51), ctx)
        assert not await access.is_allowed(make_update(private, chat_id=52, user_id=52), ctx)
        assert ctx.application.bot_data[access.MEMBER_CACHE_KEY][52][0] is False

    async def test_restricted_replies_in_private(self, fake_context):
        called = []

        @access.restricted
        async def handler(update, context):
            called.append(True)

        message = FakeMessage(chat_type=ChatType.PRIVATE)
        bot = FakeBot()

        async def get_chat_member(chat_id, user_id):
            return SimpleNamespace(status="left")

        bot.get_chat_member = get_chat_member
        await handler(make_update(message, chat_id=5, user_id=5), fake_context(bot))
        assert not called and "только для своего чата" in message.replies[0]

    def test_cooldown(self, fake_context):
        ctx = fake_context()
        assert access.cooldown_left(ctx, "k", 10) == 0
        assert access.cooldown_left(ctx, "k", 10) > 0


class TestChatFlow:
    async def test_ask_answers_and_remembers(self, fake_context):
        message = FakeMessage("/ask как дела")
        ctx = fake_context(args=["как", "дела"])
        await chat.ask_command(make_update(message), ctx)
        assert message.replies == ["Ответ AI"]
        log = ctx.chat_data[chat.LOG_KEY]
        assert (log[0].author, log[0].text) == ("Айдос", "как дела")
        assert log[1].text == "Ответ AI" and log[1].from_bot

    async def test_ask_without_question(self, fake_context):
        message = FakeMessage("/ask")
        await chat.ask_command(make_update(message), fake_context())
        assert "Напиши вопрос" in message.replies[0]

    async def test_text_ignored_when_not_addressed(self, fake_context):
        message = FakeMessage("просто болтаем")
        await chat.text_message(make_update(message), fake_context())
        assert message.replies == []

    async def test_reset(self, fake_context):
        ctx = fake_context()
        ctx.chat_data[chat.LOG_KEY] = ("x",)
        await chat.reset_command(make_update(FakeMessage("/reset")), ctx)
        assert ctx.chat_data[chat.LOG_KEY] == ()


class TestGamesHandlers:
    async def test_poll(self, fake_context):
        bot = FakeBot()
        await games.poll_command(make_update(FakeMessage("/poll Пицца & пиво? | <3 | нет")), fake_context(bot))
        assert bot.calls == [("poll", -100, "Пицца & пиво?", ("<3", "нет"))]
        # HTML-разбор отключён, иначе Telegram отклонит «&» и «<»
        assert bot.poll_kwargs["question_parse_mode"] is None
        assert bot.poll_kwargs["option_modes"] == [None, None]

    async def test_poll_rejected_by_telegram(self, fake_context):
        bot = FakeBot()

        async def send_poll(*args, **kwargs):
            raise BadRequest("Poll question is too long")

        bot.send_poll = send_poll
        message = FakeMessage("/poll Куда? | Кино | Парк")
        await games.poll_command(make_update(message), fake_context(bot))
        assert "не принял опрос" in message.replies[0]

    async def test_poll_error(self, fake_context):
        message = FakeMessage("/poll ")
        await games.poll_command(make_update(message), fake_context())
        assert "Формат" in message.replies[0]

    async def test_who_uses_friends(self, fake_context):
        message = FakeMessage("/who платит за кофе")
        await games.who_command(make_update(message), fake_context())
        assert "платит за кофе" in message.replies[0]
        assert "@dana" in message.replies[0] or "Ерлан" in message.replies[0]

    async def test_track_user(self, fake_context):
        ctx = fake_context()
        await games.track_user(make_update(FakeMessage("hi")), ctx)
        assert ctx.chat_data[games.SEEN_KEY] == {1: "@aidos"}

    async def test_simple_games(self, fake_context):
        bot = FakeBot()
        ctx = fake_context(bot, args=["🎰"])
        await games.dice_command(make_update(FakeMessage("/dice 🎰")), ctx)
        assert bot.calls == [("dice", -100, "🎰")]
        for handler, text in (
            (games.coin_command, "/coin"),
            (games.choose_command, "/choose чай или кофе"),
            (games.shar_command, "/shar"),
            (games.random_command, "/random"),
        ):
            message = FakeMessage(text)
            await handler(make_update(message), fake_context())
            assert message.replies


class TestImageHandler:
    async def test_img_draws_and_cleans_status(self, fake_context):
        message = FakeMessage("/img кот")
        await images.img_command(make_update(message), fake_context(args=["кот"]))
        assert message.photos == [(b"\x89PNG fake", "🖼 кот")]
        assert message.deleted == 1  # «Рисую…» удалено

    async def test_img_cooldown_and_empty(self, fake_context):
        ctx = fake_context(args=["кот"])
        await images.img_command(make_update(FakeMessage("/img кот")), ctx)
        second = FakeMessage("/img кот")
        await images.img_command(make_update(second), ctx)
        assert "Кисти ещё сохнут" in second.replies[0]
        empty = FakeMessage("/img")
        await images.img_command(make_update(empty), fake_context())
        assert "Что нарисовать" in empty.replies[0]

    async def test_draw_intent_in_chat(self, fake_context):
        message = FakeMessage("@friends_bot нарисуй собаку")
        await chat.text_message(make_update(message), fake_context())
        assert message.photos and message.photos[0][1] == "🖼 собаку"

    async def test_img_failure(self, fake_context, services):
        message = FakeMessage("/img кот")
        with patch.object(images, "generate_image", side_effect=ImageError("down")):
            await images.img_command(make_update(message), fake_context(args=["кот"]))
        assert "Не получилось нарисовать" in message.replies[-1]


class TestDailyCommands:
    @pytest.mark.parametrize(
        ("handler", "expected"),
        [
            (daily.weather_command, "Погода"),
            (daily.air_command, "Качество воздуха"),
            (daily.rates_command, "USD"),
            (daily.quote_command, "Мысль дня"),
            (daily.today_command, "В этот день"),
            (daily.digest_command, "Доброе утро"),
            (daily.birthdays_command, "Ближайшие дни рождения"),
        ],
    )
    async def test_commands(self, fake_context, handler, expected):
        message = FakeMessage("/x")
        await handler(make_update(message), fake_context())
        assert expected in message.replies[0]

    async def test_settitle_admin_only(self, fake_context):
        message = FakeMessage("/settitle")
        await daily.settitle_command(make_update(message, user_id=1), fake_context())
        assert "Только для админов" in message.replies[0]
        bot = FakeBot()
        admin_msg = FakeMessage("/settitle")
        await daily.settitle_command(make_update(admin_msg, user_id=7), fake_context(bot))
        assert bot.calls and "Готово" in admin_msg.replies[0]


class TestApp:
    def test_read_env_file(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# comment\nA=1\nB = \"два\"\n\nbroken\n", encoding="utf-8")
        assert read_env_file(env) == {"A": "1", "B": "два"}
        assert read_env_file(tmp_path / "none") == {}

    def test_build_application_registers_jobs(self, settings):
        app = build_application(settings)
        assert app.concurrent_updates > 1  # долгая картинка не блокирует остальных
        names = {job.name for job in app.job_queue.jobs()}
        assert {"titles", "morning", "titles-on-start"} <= names
        commands = {c for h in app.handlers[0] for c in getattr(h, "commands", ())}
        assert {"ask", "img", "weather", "poll", "birthdays", "chatid"} <= commands

    async def test_health_server(self):
        server = await start_health_server(0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        await writer.drain()
        data = await reader.read()
        writer.close()
        server.close()
        await server.wait_closed()
        assert data.startswith(b"HTTP/1.1 200 OK") and data.endswith(b"ok")
