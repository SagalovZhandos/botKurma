"""Официальные курсы Нацбанка РК (RSS, без ключа)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date

import httpx

RATES_URL = "https://nationalbank.kz/rss/get_rates.cfm"
DEFAULT_CODES = ("USD", "EUR", "RUB", "CNY")
FLAGS = {"USD": "🇺🇸", "EUR": "🇪🇺", "RUB": "🇷🇺", "CNY": "🇨🇳", "KGS": "🇰🇬", "UZS": "🇺🇿", "TRY": "🇹🇷"}


@dataclass(frozen=True)
class Rate:
    code: str
    value: float
    quant: int
    change: float


def parse_rates(xml_text: str, codes: tuple[str, ...] = DEFAULT_CODES) -> tuple[Rate, ...]:
    root = ET.fromstring(xml_text)
    found: dict[str, Rate] = {}
    for item in root.iter("item"):
        code = (item.findtext("title") or "").strip()
        if code not in codes:
            continue
        found[code] = Rate(
            code=code,
            value=float(item.findtext("description") or 0),
            quant=int(item.findtext("quant") or 1),
            change=float(item.findtext("change") or 0),
        )
    return tuple(found[c] for c in codes if c in found)


async def fetch_rates(client: httpx.AsyncClient, day: date) -> tuple[Rate, ...]:
    response = await client.get(RATES_URL, params={"fdate": day.strftime("%d.%m.%Y")})
    response.raise_for_status()
    return parse_rates(response.text)


def format_rate_line(r: Rate) -> str:
    flag = FLAGS.get(r.code, "💵")
    unit = f"{r.quant} {r.code}" if r.quant != 1 else r.code
    if r.change > 0:
        trend = f" ▲{r.change:.2f}"
    elif r.change < 0:
        trend = f" ▼{abs(r.change):.2f}"
    else:
        trend = ""
    return f"{flag} {unit} = <b>{r.value:.2f} ₸</b>{trend}"
