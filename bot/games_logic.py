"""Чистая логика мини-игр (без Telegram) — легко тестировать."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

MAX_POLL_OPTIONS = 10

MAGIC_BALL = (
    "Бесспорно ✅", "Даже не сомневайся 💯", "Да 👍", "Скорее да 🙂", "Знаки говорят — да ✨",
    "Пока неясно, спроси позже 🤔", "Лучше не рассказывать сейчас 🤐", "Сконцентрируйся и спроси снова 🔮",
    "Даже не думай ❌", "Мой ответ — нет 👎", "Весьма сомнительно 😬", "Звёзды против 🌑",
)


class GameInputError(ValueError):
    """Неверные аргументы команды — текст ошибки показываем пользователю."""


@dataclass(frozen=True)
class PollSpec:
    question: str
    options: tuple[str, ...]


def parse_poll(raw: str) -> PollSpec:
    """«Куда идём? | Кино | Боулинг | Дома» -> вопрос + варианты."""
    parts = [p.strip() for p in re.split(r"\||\n", raw) if p.strip()]
    if len(parts) < 3:
        raise GameInputError("Формат: /poll Вопрос | Вариант 1 | Вариант 2 [| ...]")
    question, options = parts[0], tuple(parts[1:])
    if len(options) > MAX_POLL_OPTIONS:
        raise GameInputError(f"Максимум {MAX_POLL_OPTIONS} вариантов")
    return PollSpec(question[:300], tuple(o[:100] for o in options))


def parse_choices(raw: str) -> tuple[str, ...]:
    """«пицца, суши или плов» -> 3 варианта."""
    parts = [p.strip() for p in re.split(r",|\s+или\s+|\s+немесе\s+|\n", raw) if p.strip()]
    if len(parts) < 2:
        raise GameInputError("Дай хотя бы два варианта: /choose пицца, суши, плов")
    return tuple(parts)


def parse_range(args: list[str]) -> tuple[int, int]:
    try:
        numbers = [int(a) for a in args[:2]]
    except ValueError as exc:
        raise GameInputError("Формат: /random или /random 10 или /random 5 50") from exc
    if not numbers:
        return 1, 100
    low, high = (1, numbers[0]) if len(numbers) == 1 else (numbers[0], numbers[1])
    return (low, high) if low <= high else (high, low)


def coin(rng: random.Random | None = None) -> str:
    return (rng or random).choice(("🦅 Орёл", "🪙 Решка"))


def magic_answer(rng: random.Random | None = None) -> str:
    return (rng or random).choice(MAGIC_BALL)
