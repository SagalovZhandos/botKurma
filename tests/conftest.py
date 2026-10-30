from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Callable
from zoneinfo import ZoneInfo

import httpx
import pytest

from bot.config import load_settings
from bot.context import SERVICES_KEY, Services
from bot.friends import Friend
from bot.services.ai import AIClient, Provider

Router = Callable[[httpx.Request], httpx.Response]


def mock_client(router: Router) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(router))


WEATHER_JSON = {
    "current": {"temperature_2m": 9.2},
    "daily": {
        "weather_code": [2],
        "temperature_2m_min": [3.4],
        "temperature_2m_max": [12.6],
        "precipitation_probability_max": [40],
        "wind_speed_10m_max": [14.8],
    },
}
AIR_JSON = {"current": {"us_aqi": 128, "pm2_5": 34.1, "pm10": 40.9}}
RATES_XML = """<?xml version="1.0" encoding="utf-8"?>
<rates>
  <item><fullname>ДОЛЛАР США</fullname><title>USD</title><description>512.34</description>
    <quant>1</quant><index>UP</index><change>1.20</change></item>
  <item><fullname>ЕВРО</fullname><title>EUR</title><description>590.10</description>
    <quant>1</quant><index>DOWN</index><change>-2.50</change></item>
  <item><fullname>РОССИЙСКИЙ РУБЛЬ</fullname><title>RUB</title><description>6.30</description>
    <quant>1</quant><index>CHANGE</index><change>0.00</change></item>
  <item><fullname>АВСТРАЛИЙСКИЙ ДОЛЛАР</fullname><title>AUD</title><description>319.18</description>
    <quant>1</quant><index>DOWN</index><change>-2.02</change></item>
</rates>"""
HISTORY_JSON = {
    "selected": [
        {"year": 2005, "text": "В Дрездене освящена церковь Фрауэнкирхе."},
        {"year": 1961, "text": "Испытание «Царь-бомбы»."},
        {"year": 1938, "text": "Радиопостановка «Войны миров»."},
        {"year": 1990, "text": "Событие <без> тегов & прочего."},
        {"text": "без года"},
    ]
}


def ai_reply(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def api_router(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if host == "api.open-meteo.com":
        return httpx.Response(200, json=WEATHER_JSON)
    if host == "air-quality-api.open-meteo.com":
        return httpx.Response(200, json=AIR_JSON)
    if host == "nationalbank.kz":
        return httpx.Response(200, text=RATES_XML)
    if host == "api.wikimedia.org":
        return httpx.Response(200, json=HISTORY_JSON)
    if "pollinations" in host and path.startswith(("/image", "/prompt")):
        return httpx.Response(200, content=b"\x89PNG fake", headers={"content-type": "image/png"})
    if host in {"text.pollinations.ai", "api.groq.com", "gen.pollinations.ai"}:
        return ai_reply("Ответ AI")
    return httpx.Response(404)


@pytest.fixture
def settings(tmp_path: Path):
    friends_file = tmp_path / "friends.json"
    friends_file.write_text(json.dumps({"friends": [{"name": "Дана", "username": "dana", "birthday": "30.10.2000"}]}))
    return load_settings({
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "CHAT_IDS": "-100",
        "ADMIN_IDS": "7",
        "FRIENDS_FILE": str(friends_file),
    })


@pytest.fixture
def services(settings):
    http = mock_client(api_router)
    ai = AIClient(http, (Provider("test", "https://api.groq.com/x", "m", "key"),))
    friends = (Friend("Дана", "dana", 30, 10, 2000), Friend("Ерлан", None, 2, 11))
    return Services(settings, http, ai, friends)


class FakeBot:
    def __init__(self, title: str = "Старое"):
        self.id = 999
        self.username = "friends_bot"
        self.title = title
        self.calls: list[tuple] = []

    async def get_chat(self, chat_id):
        return SimpleNamespace(id=chat_id, title=self.title)

    async def set_chat_title(self, chat_id, title):
        self.calls.append(("set_chat_title", chat_id, title))

    async def send_message(self, chat_id, text, **kwargs):
        self.calls.append(("send_message", chat_id, text))

    async def send_chat_action(self, chat_id, action):
        self.calls.append(("action", chat_id, action))

    async def send_poll(self, chat_id, question, options, **kwargs):
        self.poll_kwargs = {**kwargs, "option_modes": [o.text_parse_mode for o in options]}
        self.calls.append(("poll", chat_id, question, tuple(o.text for o in options)))

    async def send_dice(self, chat_id, emoji):
        self.calls.append(("dice", chat_id, emoji))


@pytest.fixture
def fake_context(services):
    def make(bot: FakeBot | None = None, args: list[str] | None = None):
        app = SimpleNamespace(bot_data={SERVICES_KEY: services})
        return SimpleNamespace(application=app, bot=bot or FakeBot(), args=args or [], chat_data={}, user_data={})

    return make


TZ = ZoneInfo("Asia/Almaty")
