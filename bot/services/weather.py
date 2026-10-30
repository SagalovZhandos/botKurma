"""Погода по городам (Open-Meteo, без ключа)."""

from __future__ import annotations

import html
from dataclasses import dataclass

import httpx

from bot.config import City

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Коды погоды WMO -> (эмодзи, описание)
WMO_CODES: dict[int, tuple[str, str]] = {
    0: ("☀️", "ясно"),
    1: ("🌤", "преимущественно ясно"),
    2: ("⛅", "переменная облачность"),
    3: ("☁️", "пасмурно"),
    45: ("🌫", "туман"),
    48: ("🌫", "изморозь, туман"),
    51: ("🌦", "лёгкая морось"),
    53: ("🌦", "морось"),
    55: ("🌧", "сильная морось"),
    56: ("🌧", "ледяная морось"),
    57: ("🌧", "ледяная морось"),
    61: ("🌦", "небольшой дождь"),
    63: ("🌧", "дождь"),
    65: ("🌧", "сильный дождь"),
    66: ("🌧", "ледяной дождь"),
    67: ("🌧", "сильный ледяной дождь"),
    71: ("🌨", "небольшой снег"),
    73: ("🌨", "снег"),
    75: ("❄️", "сильный снег"),
    77: ("🌨", "снежная крупа"),
    80: ("🌦", "ливень"),
    81: ("🌧", "сильный ливень"),
    82: ("⛈", "очень сильный ливень"),
    85: ("🌨", "снегопад"),
    86: ("❄️", "сильный снегопад"),
    95: ("⛈", "гроза"),
    96: ("⛈", "гроза с градом"),
    99: ("⛈", "сильная гроза с градом"),
}


@dataclass(frozen=True)
class CityWeather:
    city: str
    temp_now: float
    temp_min: float
    temp_max: float
    code: int
    precip_prob: int | None
    wind_max: float


def describe_code(code: int) -> tuple[str, str]:
    return WMO_CODES.get(code, ("🌡", "без описания"))


def signed(value: float) -> str:
    rounded = round(value)
    return f"+{rounded}" if rounded > 0 else str(rounded)


def parse_weather(city: City, data: dict) -> CityWeather:
    daily = data["daily"]
    precip = daily.get("precipitation_probability_max", [None])[0]
    return CityWeather(
        city=city.name,
        temp_now=data["current"]["temperature_2m"],
        temp_min=daily["temperature_2m_min"][0],
        temp_max=daily["temperature_2m_max"][0],
        code=int(daily["weather_code"][0]),
        precip_prob=int(precip) if precip is not None else None,
        wind_max=daily["wind_speed_10m_max"][0],
    )


async def fetch_weather(client: httpx.AsyncClient, city: City, tz_name: str) -> CityWeather:
    params = {
        "latitude": city.lat,
        "longitude": city.lon,
        "current": "temperature_2m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max,wind_speed_10m_max",
        "timezone": tz_name,
        "forecast_days": 1,
    }
    response = await client.get(FORECAST_URL, params=params)
    response.raise_for_status()
    return parse_weather(city, response.json())


def format_weather_line(w: CityWeather) -> str:
    emoji, text = describe_code(w.code)
    parts = [
        f"{emoji} <b>{html.escape(w.city)}</b>: {signed(w.temp_min)}…{signed(w.temp_max)}°, {text}",
    ]
    details = [f"сейчас {signed(w.temp_now)}°"]
    if w.precip_prob is not None and w.precip_prob >= 20:
        details.append(f"осадки {w.precip_prob}%")
    details.append(f"ветер до {round(w.wind_max)} км/ч")
    parts.append("   " + ", ".join(details))
    return "\n".join(parts)
