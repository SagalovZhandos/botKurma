"""Ежедневные задачи (название группы, утренняя сводка, дни рождения) и команды по запросу."""

from __future__ import annotations

import logging
from datetime import time

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from bot import birthdays, digest
from bot.context import Services, get_services
from bot.days import build_title, human_date, kazakh_day
from bot.handlers.access import is_admin, restricted
from bot.services import holidays

logger = logging.getLogger(__name__)


# ---------- задачи по расписанию ----------

async def update_titles(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    title = build_title(services.settings.title_template, services.today())
    for chat_id in services.settings.chat_ids:
        try:
            chat = await context.bot.get_chat(chat_id)
            if chat.title != title:
                await context.bot.set_chat_title(chat_id, title)
                logger.info("Название чата %s -> %s", chat_id, title)
        except TelegramError as exc:
            logger.error("Не удалось сменить название чата %s (бот админ с правом «изменять профиль»?): %s",
                         chat_id, exc)


async def send_to_chats(context: ContextTypes.DEFAULT_TYPE, services: Services, text: str) -> None:
    for chat_id in services.settings.chat_ids:
        try:
            await context.bot.send_message(chat_id, text)
        except TelegramError as exc:
            logger.error("Не удалось отправить сообщение в %s: %s", chat_id, exc)


async def morning_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    today = services.today()
    await send_to_chats(context, services, await digest.build_digest(services.digest_deps, today))
    await birthdays_job(context)


async def birthdays_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    today = services.today()
    for friend in birthdays.birthdays_on(services.friends, today):
        await send_to_chats(context, services, await birthdays.build_greeting(friend, today, services.ai))
    reminder = birthdays.reminder_text(services.friends, today, services.settings.birthday_remind_days)
    if reminder:
        await send_to_chats(context, services, reminder)


async def delete_title_service_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Убираем «бот изменил название группы», чтобы не засорять чат."""
    message = update.effective_message
    if message and message.from_user and message.from_user.id == context.bot.id:
        try:
            await message.delete()
        except TelegramError as exc:
            logger.debug("Не удалось удалить служебное сообщение: %s", exc)


# ---------- команды ----------

@restricted
async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = await digest.weather_section(get_services(context).digest_deps)
    await update.effective_message.reply_text(text or "Погода сейчас недоступна 😕")


@restricted
async def air_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = await digest.air_section(get_services(context).digest_deps)
    await update.effective_message.reply_text(text or "Данные о воздухе сейчас недоступны 😕")


@restricted
async def rates_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    text = await digest.rates_section(services.digest_deps, services.today())
    await update.effective_message.reply_text(text or "Курсы сейчас недоступны 😕")


@restricted
async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    day = services.today()
    history = await digest.history_section(services.digest_deps, day)
    holiday = holidays.holiday_on(day) or "особых праздников нет"
    parts = [f"📅 Сегодня {kazakh_day(day)}, {human_date(day)} — {holiday}", history]
    await update.effective_message.reply_text("\n\n".join(p for p in parts if p))


@restricted
async def quote_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(digest.quote_section(get_services(context).today()))


@restricted
async def digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    await update.effective_message.reply_text(await digest.build_digest(services.digest_deps, services.today()))


@restricted
async def birthdays_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context)
    if not services.friends:
        await update.effective_message.reply_text("Список друзей пуст — заполните friends.json")
        return
    await update.effective_message.reply_text(birthdays.upcoming_text(services.friends, services.today()))


@restricted
async def settitle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update, context):
        await update.effective_message.reply_text("Только для админов бота")
        return
    await update_titles(context)
    await update.effective_message.reply_text("Готово ✅ (если не сменилось — проверьте права бота)")


def register(app: Application, services: Services) -> None:
    settings = services.settings
    tz = settings.timezone
    app.add_handler(CommandHandler("weather", weather_command))
    app.add_handler(CommandHandler("air", air_command))
    app.add_handler(CommandHandler("rates", rates_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("quote", quote_command))
    app.add_handler(CommandHandler("digest", digest_command))
    app.add_handler(CommandHandler("birthdays", birthdays_command))
    app.add_handler(CommandHandler("settitle", settitle_command))
    if settings.delete_title_service_msg:
        app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_TITLE, delete_title_service_message))

    jobs = app.job_queue
    jobs.run_daily(update_titles, time(0, 0, 5, tzinfo=tz), name="titles")
    jobs.run_daily(morning_job, settings.morning_time.replace(tzinfo=tz), name="morning")
    # После перезапуска (бесплатный хостинг иногда перезапускает) сразу выставим правильное название.
    jobs.run_once(update_titles, 10, name="titles-on-start")
