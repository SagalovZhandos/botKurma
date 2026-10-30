"""Точка входа: сборка приложения и запуск."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import httpx
from telegram import LinkPreviewOptions, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, ApplicationBuilder, ContextTypes, Defaults

from bot.config import ConfigError, Settings, load_settings
from bot.context import SERVICES_KEY, Services
from bot.friends import load_friends
from bot.handlers import chat, daily, games, images, info
from bot.health import start_health_server
from bot.services.ai import AIClient, build_providers

logger = logging.getLogger(__name__)

USER_AGENT = "friends-chat-bot/1.0 (Telegram bot; https://core.telegram.org/bots)"
HEALTH_KEY = "health_server"


def read_env_file(path: Path) -> dict[str, str]:
    """Простой .env-парсер для локального запуска (на хостинге переменные задаются в панели)."""
    if not path.exists():
        return {}
    pairs = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        pairs[key.strip()] = value.strip().strip('"').strip("'")
    return pairs


def build_services(settings: Settings) -> Services:
    http = httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    providers = build_providers(settings.ai_url, settings.ai_model, settings.ai_api_key, settings.pollinations_token)
    ai = AIClient(http, providers)
    return Services(settings, http, ai, load_friends(settings.friends_file))


async def on_startup(app: Application) -> None:
    services: Services = app.bot_data[SERVICES_KEY]
    # Порт открываем первым: хостинг ждёт его, иначе считает запуск неудачным и перезапускает.
    if services.settings.port:
        app.bot_data[HEALTH_KEY] = await start_health_server(services.settings.port)
    try:
        await app.bot.set_my_commands(list(info.COMMANDS))
    except TelegramError as exc:
        logger.warning("Не удалось обновить меню команд: %s", exc)
    if not services.settings.chat_ids:
        logger.warning("CHAT_IDS пуст: добавьте бота в группу, отправьте /chatid и пропишите ID в настройки")
    logger.info("Бот @%s запущен. Друзей в списке: %d", app.bot.username, len(services.friends))


async def on_shutdown(app: Application) -> None:
    server = app.bot_data.get(HEALTH_KEY)
    if server is not None:
        server.close()
        await server.wait_closed()
    await app.bot_data[SERVICES_KEY].http.aclose()


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Ошибка при обработке обновления", exc_info=context.error)


def build_application(settings: Settings) -> Application:
    defaults = Defaults(
        parse_mode=ParseMode.HTML,
        tzinfo=settings.timezone,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    app = (
        ApplicationBuilder()
        .token(settings.bot_token)
        .defaults(defaults)
        # Иначе одна долгая картинка (до пары минут) блокирует ответы всем остальным.
        .concurrent_updates(True)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )
    services = build_services(settings)
    app.bot_data[SERVICES_KEY] = services
    info.register(app)
    daily.register(app, services)
    images.register(app)
    games.register(app)
    chat.register(app)  # последним: ловит обычный текст
    app.add_error_handler(on_error)
    return app


def main() -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    # httpx пишет в лог URL запросов, а в них токен бота — не светим его.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        settings = load_settings({**read_env_file(Path(".env")), **os.environ})
    except ConfigError as exc:
        logger.error("Ошибка настроек: %s", exc)
        sys.exit(1)
    # Только новые сообщения: правка старого сообщения не должна заново запускать /img, /poll или AI.
    build_application(settings).run_polling(allowed_updates=[Update.MESSAGE], drop_pending_updates=True)


if __name__ == "__main__":
    main()
