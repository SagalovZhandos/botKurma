from __future__ import annotations

from datetime import date

import httpx
import pytest

from bot.config import City
from bot.services import air, currency, holidays, quotes, weather
from bot.services.ai import AIClient, AIError, Message, Provider, build_providers, clean_answer
from bot.services.images import ImageError, build_url, generate_image
from tests.conftest import HISTORY_JSON, RATES_XML, ai_reply, api_router, mock_client

ALMATY = City("Алматы", 43.24, 76.89)


class TestWeather:
    async def test_fetch_and_format(self):
        w = await weather.fetch_weather(mock_client(api_router), ALMATY, "Asia/Almaty")
        assert (w.temp_min, w.temp_max, w.code, w.precip_prob) == (3.4, 12.6, 2, 40)
        line = weather.format_weather_line(w)
        assert "<b>Алматы</b>: +3…+13°, переменная облачность" in line
        assert "осадки 40%" in line and "ветер до 15 км/ч" in line

    def test_low_precip_hidden_and_unknown_code(self):
        w = weather.CityWeather("Астана", -5.4, -12, -3, 1234, 5, 20)
        line = weather.format_weather_line(w)
        assert "осадки" not in line
        assert "-12…-3°" in line and "без описания" in line

    def test_signed(self):
        assert [weather.signed(v) for v in (0.2, 4.6, -0.4, -3.5)] == ["0", "+5", "0", "-4"]

    async def test_http_error(self):
        client = mock_client(lambda r: httpx.Response(500))
        with pytest.raises(httpx.HTTPStatusError):
            await weather.fetch_weather(client, ALMATY, "Asia/Almaty")


class TestAir:
    async def test_fetch_and_format(self):
        a = await air.fetch_air(mock_client(api_router), ALMATY, "Asia/Almaty")
        assert a.aqi == 128
        assert air.format_air_line(a) == "🟠 <b>Алматы</b>: AQI 128 — вредно для чувствительных (PM2.5 34)"

    @pytest.mark.parametrize(
        ("aqi", "label"),
        [(10, "хорошо"), (50, "хорошо"), (51, "умеренно"), (180, "вредно"), (250, "очень вредно"), (400, "опасно")],
    )
    def test_levels(self, aqi, label):
        assert air.aqi_level(aqi)[1] == label

    def test_advice(self):
        good = air.AirQuality("Актобе", 40, 5, 10)
        bad = air.AirQuality("Алматы", 170, 80, 90)
        assert air.air_advice((good,)) is None
        assert "Алматы" in air.air_advice((good, bad))
        assert "A&amp;B" in air.air_advice((air.AirQuality("A&B", 200, 1, 1),))


class TestCurrency:
    def test_parse_keeps_order_and_filters(self):
        rates = currency.parse_rates(RATES_XML)
        assert [r.code for r in rates] == ["USD", "EUR", "RUB"]

    def test_format(self):
        usd, eur, rub = currency.parse_rates(RATES_XML)
        assert currency.format_rate_line(usd) == "🇺🇸 USD = <b>512.34 ₸</b> ▲1.20"
        assert currency.format_rate_line(eur).endswith("▼2.50")
        assert currency.format_rate_line(rub) == "🇷🇺 RUB = <b>6.30 ₸</b>"
        assert currency.format_rate_line(currency.Rate("KRW", 36.5, 100, 0)).startswith("💵 100 KRW")

    async def test_fetch_passes_date(self):
        seen = {}

        def router(request: httpx.Request) -> httpx.Response:
            seen["fdate"] = request.url.params["fdate"]
            return httpx.Response(200, text=RATES_XML)

        rates = await currency.fetch_rates(mock_client(router), date(2026, 3, 5))
        assert seen["fdate"] == "05.03.2026" and len(rates) == 3


class TestHolidaysAndHistory:
    def test_holidays(self):
        assert "Наурыз" in holidays.holiday_on(date(2026, 3, 22))
        assert "Республики" in holidays.holiday_on(date(2026, 10, 25))
        assert holidays.holiday_on(date(2026, 10, 30)) is None

    def test_parse_and_pick(self):
        events = holidays.parse_history(HISTORY_JSON)
        assert len(events) == 4
        picked = holidays.pick_events(events, 3, seed=1)
        assert len(picked) == 3
        assert [e.year for e in picked] == sorted(e.year for e in picked)
        assert holidays.pick_events(events, 3, seed=1) == picked
        assert len(holidays.pick_events(events[:2], 3, seed=1)) == 2

    async def test_fetch_and_escape(self):
        events = await holidays.fetch_history(mock_client(api_router), date(2026, 10, 30), count=10)
        line = holidays.format_event_line(next(e for e in events if e.year == 1990))
        assert "&lt;без&gt;" in line and "&amp;" in line


class TestQuotes:
    def test_cycle_covers_all_quotes(self):
        start = date(2026, 1, 1).toordinal()
        seen = {quotes.quote_of_day(date.fromordinal(start + i)) for i in range(len(quotes.QUOTES))}
        assert len(seen) == len(quotes.QUOTES)

    def test_format_with_translation(self):
        q = quotes.Quote("Адам бол!", "Абай", "Будь человеком!")
        assert quotes.format_quote(q) == "«Адам бол!»\n<i>Будь человеком!</i>\n— Абай"
        assert quotes.format_quote(quotes.Quote("a<b", "X")) == "«a&lt;b»\n— X"


class TestAI:
    def test_providers(self):
        assert [p.name for p in build_providers("u", "m", None)] == ["pollinations-anon"]
        assert [p.name for p in build_providers("u", "m", "k")] == ["primary", "pollinations-anon"]
        with_token = build_providers("u", "m", "k", "sk_x")
        assert [p.name for p in with_token] == ["primary", "pollinations"]
        assert with_token[1].api_key == "sk_x" and with_token[1].url.startswith("https://gen.pollinations.ai")

    def test_clean_answer(self):
        assert clean_answer("<think>хм</think>\n Привет ") == "Привет"

    async def test_fallback_to_second_provider(self):
        calls = []

        def router(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.host)
            if request.url.host == "api.groq.com":
                return httpx.Response(429)
            return ai_reply("из запасного")

        client = AIClient(mock_client(router), build_providers("https://api.groq.com/v1", "m", "k"))
        assert await client.chat((Message("user", "a"), Message("assistant", "b"))) == "из запасного"
        assert calls == ["api.groq.com", "text.pollinations.ai"]

    async def test_sends_key_and_history(self):
        captured = {}

        def router(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("authorization")
            captured["body"] = request.read().decode()
            return ai_reply("ok")

        client = AIClient(mock_client(router), (Provider("p", "https://x.test/c", "model-x", "secret"),))
        await client.chat((Message("user", "раньше"),), "Сейчас пятница")
        assert captured["auth"] == "Bearer secret"
        assert "model-x" in captured["body"] and "раньше" in captured["body"]
        assert "Сейчас пятница" in captured["body"] and "reasoning_effort" not in captured["body"]

    async def test_primary_only_and_reasoning_effort(self):
        calls = []

        def router(request: httpx.Request) -> httpx.Response:
            calls.append((request.url.host, request.read().decode()))
            return httpx.Response(429)

        providers = build_providers("https://api.groq.com/v1", "openai/gpt-oss-120b", "k")
        client = AIClient(mock_client(router), providers)
        with pytest.raises(AIError):
            await client.chat((Message("user", "q"),), primary_only=True)
        assert [h for h, _ in calls] == ["api.groq.com"]  # запасной не тронут
        assert '"reasoning_effort": "low"' in calls[0][1] or '"reasoning_effort":"low"' in calls[0][1]

    async def test_all_fail(self):
        client = AIClient(mock_client(lambda r: ai_reply("")), (Provider("p", "https://x.test", "m"),))
        with pytest.raises(AIError):
            await client.complete((Message("user", "q"),))

    async def test_image_prompt_falls_back_to_request(self):
        client = AIClient(mock_client(lambda r: httpx.Response(500)), (Provider("p", "https://x.test", "m"),))
        assert await client.to_image_prompt("кот") == "кот"
        ok = AIClient(mock_client(lambda r: ai_reply('"a cat"')), (Provider("p", "https://x.test", "m"),))
        assert await ok.to_image_prompt("кот") == "a cat"


class TestImages:
    def test_url_encoding(self):
        url = build_url("https://gen.pollinations.ai/image/{prompt}", "кот / на коне?")
        assert "/" not in url.split("/image/")[1] and "?" not in url

    async def test_generate_uses_token(self):
        seen = {}

        def router(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("authorization")
            seen["seed"] = request.url.params["seed"]
            seen["model"] = request.url.params["model"]
            return httpx.Response(200, content=b"img", headers={"content-type": "image/jpeg"})

        assert await generate_image(mock_client(router), "cat", token="tok", seed=5) == b"img"
        assert seen == {"auth": "Bearer tok", "seed": "5", "model": "zimage"}

    async def test_fallback_and_failure(self):
        hosts = []

        def router(request: httpx.Request) -> httpx.Response:
            hosts.append(request.url.host)
            if request.url.host == "gen.pollinations.ai":
                return httpx.Response(200, json={"error": "x"})
            return httpx.Response(200, content=b"img2", headers={"content-type": "image/png"})

        assert await generate_image(mock_client(router), "cat") == b"img2"
        assert hosts == ["gen.pollinations.ai", "image.pollinations.ai"]
        with pytest.raises(ImageError):
            await generate_image(mock_client(lambda r: httpx.Response(503)), "cat")
