"""Список друзей и дни рождения (файл friends.json)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Friend:
    name: str
    username: str | None = None
    birth_day: int | None = None
    birth_month: int | None = None
    birth_year: int | None = None

    @property
    def mention(self) -> str:
        return f"@{self.username}" if self.username else self.name

    @property
    def has_birthday(self) -> bool:
        return self.birth_day is not None and self.birth_month is not None


def parse_birthday(raw: str) -> tuple[int, int, int | None]:
    """«15.03» или «15.03.1998» -> (день, месяц, год|None)."""
    parts = raw.strip().split(".")
    if len(parts) not in (2, 3):
        raise ValueError(f"дата рождения «{raw}»: нужен формат ДД.ММ или ДД.ММ.ГГГГ")
    day, month = int(parts[0]), int(parts[1])
    year = int(parts[2]) if len(parts) == 3 else None
    date(year or 2000, month, day)  # проверка корректности (2000 — високосный)
    return day, month, year


def parse_friend(item: dict[str, Any]) -> Friend:
    name = str(item.get("name", "")).strip()
    if not name:
        raise ValueError(f"у друга нет имени: {item}")
    username = str(item.get("username", "")).strip().lstrip("@") or None
    birthday = item.get("birthday")
    if not birthday:
        return Friend(name=name, username=username)
    day, month, year = parse_birthday(str(birthday))
    return Friend(name, username, day, month, year)


def parse_friends(data: dict[str, Any]) -> tuple[Friend, ...]:
    return tuple(parse_friend(item) for item in data.get("friends", []))


def load_friends(path: Path) -> tuple[Friend, ...]:
    if not path.exists():
        logger.warning("Файл друзей %s не найден — дни рождения и /who отключены", path)
        return ()
    try:
        return parse_friends(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError) as exc:
        logger.error("Не удалось прочитать %s: %s", path, exc)
        return ()


def birthday_in_year(friend: Friend, year: int) -> date:
    """29 февраля в невисокосный год празднуем 28-го."""
    assert friend.birth_day is not None and friend.birth_month is not None
    try:
        return date(year, friend.birth_month, friend.birth_day)
    except ValueError:
        return date(year, 2, 28)


def next_birthday(friend: Friend, today: date) -> date:
    this_year = birthday_in_year(friend, today.year)
    return this_year if this_year >= today else birthday_in_year(friend, today.year + 1)


def age_on(friend: Friend, day: date) -> int | None:
    return day.year - friend.birth_year if friend.birth_year else None


def birthdays_on(friends: tuple[Friend, ...], day: date) -> tuple[Friend, ...]:
    return tuple(f for f in friends if f.has_birthday and birthday_in_year(f, day.year) == day)


def upcoming_birthdays(friends: tuple[Friend, ...], today: date, days: int) -> tuple[tuple[Friend, date], ...]:
    """Дни рождения в ближайшие `days` дней (включая сегодня), по порядку."""
    limit = today + timedelta(days=days)
    pairs = ((f, next_birthday(f, today)) for f in friends if f.has_birthday)
    return tuple(sorted((p for p in pairs if p[1] <= limit), key=lambda p: p[1]))
