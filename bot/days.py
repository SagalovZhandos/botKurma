"""Названия дней недели и месяцев, заголовок группы."""

from __future__ import annotations

from datetime import date

KAZAKH_DAYS = ("Дүйсенбі", "Сейсенбі", "Сәрсенбі", "Бейсенбі", "Жұма", "Сенбі", "Жексенбі")
RUSSIAN_DAYS = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")
RUSSIAN_MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

TELEGRAM_TITLE_LIMIT = 128


def kazakh_day(d: date) -> str:
    return KAZAKH_DAYS[d.weekday()]


def russian_day(d: date) -> str:
    return RUSSIAN_DAYS[d.weekday()]


def human_date(d: date) -> str:
    """«30 октября»."""
    return f"{d.day} {RUSSIAN_MONTHS_GENITIVE[d.month - 1]}"


def build_title(template: str, d: date) -> str:
    """Подставляет {day}, {day_ru}, {date} в шаблон названия группы."""
    title = template.format(
        day=kazakh_day(d),
        day_ru=russian_day(d),
        date=d.strftime("%d.%m"),
    ).strip()
    return (title or kazakh_day(d))[:TELEGRAM_TITLE_LIMIT]
