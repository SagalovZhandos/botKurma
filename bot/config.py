"""Настройки бота из переменных окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(ValueError):
    """Ошибка в переменных окружения."""


@dataclass(frozen=True)
class City:
    name: str
    lat: float
    lon: float


DEFAULT_CITIES = (
    City("Алматы", 43.2389, 76.8897),
    City("Астана", 51.1694, 71.4491),
    City("Актобе", 50.2839, 57.1670),
)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_AI_MODEL = "openai/gpt-oss-120b"


@dataclass(frozen=True)
class Settings:
    bot_token: str
    chat_ids: tuple[int, ...]
    admin_ids: tuple[int, ...]
    timezone: ZoneInfo
    morning_time: time
    title_template: str
    cities: tuple[City, ...]
    ai_url: str
    ai_api_key: str | None
    ai_model: str
    pollinations_token: str | None
    friends_file: Path
    port: int | None
    delete_title_service_msg: bool
    birthday_remind_days: int


def parse_int_list(raw: str, name: str) -> tuple[int, ...]:
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    try:
        return tuple(int(p) for p in parts)
    except ValueError as exc:
        raise ConfigError(f"{name}: ожидаются числа через запятую, получено «{raw}»") from exc


def parse_time(raw: str, name: str) -> time:
    try:
        hours, minutes = (int(x) for x in raw.strip().split(":"))
        return time(hours, minutes)
    except ValueError as exc:
        raise ConfigError(f"{name}: ожидается время ЧЧ:ММ, получено «{raw}»") from exc


def parse_cities(raw: str) -> tuple[City, ...]:
    """Формат: «Алматы:43.24:76.89;Астана:51.17:71.45»."""
    if not raw.strip():
        return DEFAULT_CITIES
    cities = []
    for chunk in raw.split(";"):
        if not chunk.strip():
            continue
        try:
            name, lat, lon = (p.strip() for p in chunk.split(":"))
            cities.append(City(name, float(lat), float(lon)))
        except ValueError as exc:
            raise ConfigError(f"CITIES: неверный формат «{chunk}», нужно Город:широта:долгота") from exc
    return tuple(cities)


def parse_timezone(raw: str) -> ZoneInfo:
    try:
        return ZoneInfo(raw.strip())
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"TZ_NAME: неизвестный часовой пояс «{raw}», пример: Asia/Almaty") from exc


def validate_title_template(template: str) -> str:
    """Ошибку в шаблоне лучше увидеть при запуске, а не молча в полночь."""
    try:
        template.format(day="", day_ru="", date="")
    except (KeyError, IndexError, ValueError) as exc:
        raise ConfigError(
            f"TITLE_TEMPLATE: неверный шаблон «{template}», доступны {{day}}, {{day_ru}}, {{date}}"
        ) from exc
    return template


def parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on", "да"}


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("TELEGRAM_BOT_TOKEN не задан (получите у @BotFather)")

    port_raw = env.get("PORT", "").strip()
    try:
        remind_days = int(env.get("BIRTHDAY_REMIND_DAYS", "3"))
        port = int(port_raw) if port_raw else None
    except ValueError as exc:
        raise ConfigError("BIRTHDAY_REMIND_DAYS и PORT должны быть числами") from exc

    return Settings(
        bot_token=token,
        chat_ids=parse_int_list(env.get("CHAT_IDS", ""), "CHAT_IDS"),
        admin_ids=parse_int_list(env.get("ADMIN_IDS", ""), "ADMIN_IDS"),
        timezone=parse_timezone(env.get("TZ_NAME", "Asia/Almaty")),
        morning_time=parse_time(env.get("MORNING_TIME", "08:00"), "MORNING_TIME"),
        title_template=validate_title_template(env.get("TITLE_TEMPLATE", "{day}")),
        cities=parse_cities(env.get("CITIES", "")),
        ai_url=env.get("AI_URL", GROQ_URL),
        ai_api_key=env.get("AI_API_KEY", "").strip() or None,
        ai_model=env.get("AI_MODEL", DEFAULT_AI_MODEL),
        pollinations_token=env.get("POLLINATIONS_TOKEN", "").strip() or None,
        friends_file=Path(env.get("FRIENDS_FILE", "friends.json")),
        port=port,
        delete_title_service_msg=parse_bool(env.get("DELETE_TITLE_SERVICE_MSG", "true")),
        birthday_remind_days=remind_days,
    )
