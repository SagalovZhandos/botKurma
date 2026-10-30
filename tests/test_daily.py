from __future__ import annotations

import random
from datetime import date
from unittest.mock import patch

import httpx
import pytest

from bot import birthdays, digest, games_logic
from bot.config import City
from bot.friends import Friend
from bot.handlers import daily
from bot.services.ai import AIClient, Provider
from tests.conftest import FakeBot, api_router, mock_client

FRIDAY = date(2026, 10, 30)
CITIES = (City("Алматы", 43.2, 76.9), City("Астана", 51.2, 71.4))


class TestDigest:
    async def test_full_digest(self):
        text = await digest.build_digest(digest.DigestDeps(mock_client(api_router), CITIES, "Asia/Almaty"), FRIDAY)
        assert text.startswith("☀️ <b>Қайырлы таң!")
        assert "Жұма (пятница), 30 октября" in text
        for section in ("Погода", "Качество воздуха", "Курс Нацбанка", "В этот день", "Мысль дня"):
            assert section in text
        assert text.count("<b>Алматы</b>") == 2

    async def test_digest_survives_api_outage(self):
        deps = digest.DigestDeps(mock_client(lambda r: httpx.Response(503)), CITIES, "Asia/Almaty")
        text = await digest.build_digest(deps, date(2026, 3, 21))
        assert "Наурыз" in text and "Мысль дня" in text
        assert "Погода" not in text and "Курс" not in text

    async def test_partial_city_failure(self):
        def router(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("latitude") == "51.2":
                return httpx.Response(500)
            return api_router(request)

        text = await digest.weather_section(digest.DigestDeps(mock_client(router), CITIES, "Asia/Almaty"))
        assert "Алматы" in text and "Астана" not in text


class TestBirthdays:
    def test_age_suffix(self):
        assert [birthdays.age_suffix(n) for n in (21, 22, 25, 11, 12, 30, 101)] == [
            "год", "года", "лет", "лет", "лет", "лет", "год",
        ]

    async def test_greeting_with_ai_and_fallback(self):
        dana = Friend("Дана", "dana", 30, 10, 2000)
        ai = AIClient(mock_client(api_router), (Provider("p", "https://api.groq.com/x", "m"),))
        text = await birthdays.build_greeting(dana, FRIDAY, ai)
        assert "@dana" in text and "26 лет" in text and "Ответ AI" in text

        broken = AIClient(mock_client(lambda r: httpx.Response(500)), (Provider("p", "https://x.test", "m"),))
        fallback = await birthdays.build_greeting(Friend("Ерлан"), FRIDAY, broken)
        assert any(w in fallback for w in birthdays.TEMPLATE_WISHES)
        assert "лет" not in fallback.split("\n")[0]

    def test_reminder(self):
        friends = (Friend("Дана", None, 2, 11),)
        assert "Дана" in birthdays.reminder_text(friends, FRIDAY, 3)
        assert birthdays.reminder_text(friends, FRIDAY, 2) is None
        assert birthdays.reminder_text(friends, FRIDAY, 0) is None

    def test_upcoming_text(self):
        friends = (Friend("Дана", None, 30, 10), Friend("Ерлан", None, 2, 11))
        text = birthdays.upcoming_text(friends, FRIDAY)
        assert "Дана — сегодня" in text and "Ерлан — 2 ноября (через 3 дн.)" in text
        assert "нет" in birthdays.upcoming_text((), FRIDAY)


class TestGamesLogic:
    def test_poll(self):
        spec = games_logic.parse_poll("Куда идём? | Кино | Боулинг\nДома")
        assert spec.question == "Куда идём?" and spec.options == ("Кино", "Боулинг", "Дома")
        with pytest.raises(games_logic.GameInputError):
            games_logic.parse_poll("Вопрос | один")
        with pytest.raises(games_logic.GameInputError):
            games_logic.parse_poll("Q|" + "|".join(str(i) for i in range(11)))

    def test_choices(self):
        assert games_logic.parse_choices("пицца, суши или плов") == ("пицца", "суши", "плов")
        assert games_logic.parse_choices("бешбармак немесе манты") == ("бешбармак", "манты")
        with pytest.raises(games_logic.GameInputError):
            games_logic.parse_choices("только одно")

    def test_range(self):
        assert games_logic.parse_range([]) == (1, 100)
        assert games_logic.parse_range(["6"]) == (1, 6)
        assert games_logic.parse_range(["50", "5"]) == (5, 50)
        with pytest.raises(games_logic.GameInputError):
            games_logic.parse_range(["много"])

    def test_random_helpers(self):
        rng = random.Random(3)
        assert games_logic.coin(rng) in ("🦅 Орёл", "🪙 Решка")
        assert games_logic.magic_answer(rng) in games_logic.MAGIC_BALL


class TestDailyJobs:
    async def test_update_titles_sets_kazakh_day(self, fake_context, services):
        bot = FakeBot(title="Старое название")
        with patch.object(type(services), "today", lambda self: FRIDAY):
            await daily.update_titles(fake_context(bot))
        assert bot.calls == [("set_chat_title", -100, "Жұма")]

    async def test_update_titles_skips_when_same(self, fake_context, services):
        bot = FakeBot(title="Жұма")
        with patch.object(type(services), "today", lambda self: FRIDAY):
            await daily.update_titles(fake_context(bot))
        assert bot.calls == []

    async def test_morning_job_sends_digest_and_birthday(self, fake_context, services):
        bot = FakeBot()
        with patch.object(type(services), "today", lambda self: FRIDAY):
            await daily.morning_job(fake_context(bot))
        texts = [c[2] for c in bot.calls if c[0] == "send_message"]
        assert len(texts) == 3  # дайджест, поздравление Даны, напоминание про Ерлана (через 3 дня)
        assert "Доброе утро" in texts[0]
        assert "@dana" in texts[1]
        assert "Ерлан" in texts[2]
