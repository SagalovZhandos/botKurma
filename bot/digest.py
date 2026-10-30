"""Утренний дайджест: погода, воздух, курсы, праздник, история, цитата."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from typing import Awaitable, TypeVar

import httpx

from bot.config import City
from bot.days import human_date, kazakh_day, russian_day
from bot.services import air, currency, holidays, quotes, weather

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class DigestDeps:
    client: httpx.AsyncClient
    cities: tuple[City, ...]
    tz_name: str


async def safe(awaitable: Awaitable[T], what: str) -> T | None:
    """Одна упавшая секция не должна ломать весь дайджест."""
    try:
        return await awaitable
    except Exception as exc:  # noqa: BLE001 — внешние API падают по-разному
        logger.warning("Не удалось получить %s: %s", what, exc)
        return None


async def weather_section(deps: DigestDeps) -> str | None:
    results = await asyncio.gather(
        *(safe(weather.fetch_weather(deps.client, c, deps.tz_name), f"погоду {c.name}") for c in deps.cities)
    )
    lines = [weather.format_weather_line(w) for w in results if w is not None]
    return "🌤 <b>Погода</b>\n" + "\n".join(lines) if lines else None


async def air_section(deps: DigestDeps) -> str | None:
    results = await asyncio.gather(
        *(safe(air.fetch_air(deps.client, c, deps.tz_name), f"воздух {c.name}") for c in deps.cities)
    )
    items = tuple(a for a in results if a is not None)
    if not items:
        return None
    lines = ["🌫 <b>Качество воздуха</b>", *(air.format_air_line(a) for a in items)]
    advice = air.air_advice(items)
    return "\n".join([*lines, advice] if advice else lines)


async def rates_section(deps: DigestDeps, day: date) -> str | None:
    rates = await safe(currency.fetch_rates(deps.client, day), "курсы валют")
    if not rates:
        return None
    return "💱 <b>Курс Нацбанка</b>\n" + "\n".join(currency.format_rate_line(r) for r in rates)


async def history_section(deps: DigestDeps, day: date) -> str | None:
    events = await safe(holidays.fetch_history(deps.client, day), "события дня")
    if not events:
        return None
    return "📜 <b>В этот день</b>\n" + "\n".join(holidays.format_event_line(e) for e in events)


def header(day: date) -> str:
    lines = [
        "☀️ <b>Қайырлы таң! Доброе утро!</b>",
        f"Сегодня {kazakh_day(day)} ({russian_day(day).lower()}), {human_date(day)}",
    ]
    holiday = holidays.holiday_on(day)
    if holiday:
        lines.append(f"📅 {holiday}")
    return "\n".join(lines)


def quote_section(day: date) -> str:
    return "💭 <b>Мысль дня</b>\n" + quotes.format_quote(quotes.quote_of_day(day))


async def build_digest(deps: DigestDeps, day: date) -> str:
    sections = await asyncio.gather(
        weather_section(deps),
        air_section(deps),
        rates_section(deps, day),
        history_section(deps, day),
    )
    parts = [header(day), *(s for s in sections if s), quote_section(day)]
    return "\n\n".join(parts)
