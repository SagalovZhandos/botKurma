"""Общие зависимости бота, доступные из любого обработчика."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import httpx
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.digest import DigestDeps
from bot.friends import Friend
from bot.services.ai import AIClient

SERVICES_KEY = "services"


@dataclass(frozen=True)
class Services:
    settings: Settings
    http: httpx.AsyncClient
    ai: AIClient
    friends: tuple[Friend, ...]

    @property
    def digest_deps(self) -> DigestDeps:
        return DigestDeps(self.http, self.settings.cities, self.settings.timezone.key)

    def today(self) -> date:
        return datetime.now(self.settings.timezone).date()


def get_services(context: ContextTypes.DEFAULT_TYPE) -> Services:
    return context.application.bot_data[SERVICES_KEY]
