"""Праздники Казахстана и «в этот день в истории» (Википедия)."""

from __future__ import annotations

import html
import random
from dataclasses import dataclass
from datetime import date

import httpx

ON_THIS_DAY_URL = "https://api.wikimedia.org/feed/v1/wikipedia/ru/onthisday/selected/{month:02d}/{day:02d}"

# Праздники с фиксированной датой. Курбан айт меняет дату каждый год — его тут нет.
KZ_HOLIDAYS: dict[tuple[int, int], str] = {
    (1, 1): "Новый год 🎄",
    (1, 2): "Новый год 🎄",
    (1, 7): "Рождество Христово",
    (3, 8): "Международный женский день 💐",
    (3, 21): "Наурыз мейрамы 🌷",
    (3, 22): "Наурыз мейрамы 🌷",
    (3, 23): "Наурыз мейрамы 🌷",
    (5, 1): "Праздник единства народа Казахстана",
    (5, 7): "День защитника Отечества",
    (5, 9): "День Победы",
    (7, 6): "День столицы",
    (8, 30): "День Конституции",
    (10, 25): "День Республики 🇰🇿",
    (12, 16): "День Независимости 🇰🇿",
    (2, 14): "День всех влюблённых ❤️",
    (4, 1): "День смеха 😄",
    (5, 31): "День памяти жертв политических репрессий и голода",
    (12, 31): "Канун Нового года 🎆",
}


@dataclass(frozen=True)
class HistoryEvent:
    year: int
    text: str


def holiday_on(day: date) -> str | None:
    return KZ_HOLIDAYS.get((day.month, day.day))


def parse_history(data: dict) -> tuple[HistoryEvent, ...]:
    events = (
        HistoryEvent(int(item["year"]), str(item["text"]).strip())
        for item in data.get("selected", [])
        if "year" in item and item.get("text")
    )
    return tuple(events)


def pick_events(events: tuple[HistoryEvent, ...], count: int, seed: int) -> tuple[HistoryEvent, ...]:
    """Детерминированно выбирает `count` событий (одинаково в течение дня) и сортирует по году."""
    if len(events) <= count:
        return tuple(sorted(events, key=lambda e: e.year))
    chosen = random.Random(seed).sample(list(events), count)
    return tuple(sorted(chosen, key=lambda e: e.year))


async def fetch_history(client: httpx.AsyncClient, day: date, count: int = 3) -> tuple[HistoryEvent, ...]:
    url = ON_THIS_DAY_URL.format(month=day.month, day=day.day)
    response = await client.get(url)
    response.raise_for_status()
    return pick_events(parse_history(response.json()), count, seed=day.toordinal())


def format_event_line(e: HistoryEvent) -> str:
    return f"• <b>{e.year}</b> — {html.escape(e.text)}"
