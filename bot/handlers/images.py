"""Генерация картинок: /img запрос."""

from __future__ import annotations

import html
import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

from bot.context import get_services
from bot.handlers.access import cooldown_left, restricted
from bot.services.images import ImageError, generate_image

logger = logging.getLogger(__name__)

IMAGE_COOLDOWN = 20
CAPTION_LIMIT = 1000
NO_TOKEN_HINT = "\n(Админу: задайте бесплатный POLLINATIONS_TOKEN — без него генератор почти не работает.)"
EXAMPLE_REQUEST = "Что нарисовать? Например: /img кот-космонавт скачет на коне по степи"


async def draw(update: Update, context: ContextTypes.DEFAULT_TYPE, request: str) -> None:
    message = update.effective_message
    wait = cooldown_left(context, "img_last", IMAGE_COOLDOWN)
    if wait:
        await message.reply_text(f"Кисти ещё сохнут 🎨 Подожди {wait:.0f} с.")
        return

    services = get_services(context)
    status = await message.reply_text("🎨 Рисую… обычно 10–40 секунд")
    await context.bot.send_chat_action(message.chat_id, ChatAction.UPLOAD_PHOTO)
    try:
        prompt = await services.ai.to_image_prompt(request)
        image = await generate_image(services.http, prompt, services.settings.pollinations_token)
        await message.reply_photo(image, caption=f"🖼 {html.escape(request[:CAPTION_LIMIT])}")
    except ImageError:
        hint = "" if services.settings.pollinations_token else NO_TOKEN_HINT
        await message.reply_text(f"Не получилось нарисовать 😔 Генератор занят, попробуй через минуту.{hint}")
    except TelegramError as exc:
        logger.error("Не удалось отправить картинку: %s", exc)
        await message.reply_text("Картинка получилась, но Telegram её не принял 😕 Попробуй другой запрос.")
    finally:
        try:
            await status.delete()
        except TelegramError:
            pass


@restricted
async def img_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    request = " ".join(context.args or [])
    reply = update.effective_message.reply_to_message
    if not request and reply and reply.text:
        request = reply.text
    if not request:
        await update.effective_message.reply_text(EXAMPLE_REQUEST)
        return
    await draw(update, context, request)


def register(app: Application) -> None:
    app.add_handler(CommandHandler(["img", "draw"], img_command))
