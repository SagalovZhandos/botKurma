"""Качество воздуха по городам (Open-Meteo Air Quality, без ключа)."""

from __future__ import annotations

import html
from dataclasses import dataclass

import httpx

from bot.config import City

AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

# Верхняя граница US AQI -> (эмодзи, оценка)
AQI_LEVELS: tuple[tuple[int, str, str], ...] = (
    (50, "🟢", "хорошо"),
    (100, "🟡", "умеренно"),
    (150, "🟠", "вредно для чувствительных"),
    (200, "🔴", "вредно"),
    (300, "🟣", "очень вредно"),
)
HAZARD = ("🟤", "опасно")
UNHEALTHY_FROM = 151


@dataclass(frozen=True)
class AirQuality:
    city: str
    aqi: int
    pm25: float
    pm10: float


def aqi_level(aqi: int) -> tuple[str, str]:
    for limit, emoji, label in AQI_LEVELS:
        if aqi <= limit:
            return emoji, label
    return HAZARD


def parse_air(city: City, data: dict) -> AirQuality:
    current = data["current"]
    return AirQuality(
        city=city.name,
        aqi=int(round(current["us_aqi"])),
        pm25=float(current["pm2_5"]),
        pm10=float(current["pm10"]),
    )


async def fetch_air(client: httpx.AsyncClient, city: City, tz_name: str) -> AirQuality:
    params = {
        "latitude": city.lat,
        "longitude": city.lon,
        "current": "us_aqi,pm2_5,pm10",
        "timezone": tz_name,
    }
    response = await client.get(AIR_URL, params=params)
    response.raise_for_status()
    return parse_air(city, response.json())


def format_air_line(a: AirQuality) -> str:
    emoji, label = aqi_level(a.aqi)
    return f"{emoji} <b>{html.escape(a.city)}</b>: AQI {a.aqi} — {label} (PM2.5 {a.pm25:.0f})"


def air_advice(items: tuple[AirQuality, ...]) -> str | None:
    bad = [html.escape(a.city) for a in items if a.aqi >= UNHEALTHY_FROM]
    if not bad:
        return None
    return f"😷 {', '.join(bad)}: лучше без долгих прогулок, проветривать осторожно, пригодится маска."
