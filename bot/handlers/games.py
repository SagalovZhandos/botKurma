"""Опросы и мини-игры."""

from __future__ import annotations

import html
import random

from telegram import InputPollOption, Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from bot import games_logic
from bot.context import get_services
from bot.games_logic import GameInputError
from bot.handlers.access import restricted

SEEN_KEY = "seen_users"
DICE_EMOJI = {"🎲", "🎯", "🏀", "⚽", "🎳", "🎰"}


def raw_args(update: Update) -> str:
    """Текст после команды, с сохранением переносов строк и «|»."""
    parts = (update.effective_message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


@restricted
async def poll_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        spec = games_logic.parse_poll(raw_args(update))
    except GameInputError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    # parse_mode=None: иначе «&» или «<» в вопросе ломают HTML-разбор по умолчанию.
    options = [InputPollOption(o, text_parse_mode=None) for o in spec.options]
    try:
        await context.bot.send_poll(
            update.effective_chat.id, spec.question, options, is_anonymous=False, question_parse_mode=None
        )
    except TelegramError as exc:
        await update.effective_message.reply_text(f"Telegram не принял опрос: {html.escape(str(exc))}")


@restricted
async def who_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    friends = [f.mention for f in get_services(context).friends]
    seen = list(context.chat_data.get(SEEN_KEY, {}).values())
    candidates = sorted(set(friends) | set(seen))
    if not candidates:
        await update.effective_message.reply_text("Я пока никого не знаю 🙈 Заполните friends.json")
        return
    what = raw_args(update) or "самый везучий"
    await update.effective_message.reply_text(
        f"🎯 Сегодня {html.escape(what)} — <b>{html.escape(random.choice(candidates))}</b>!"
    )


@restricted
async def coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(games_logic.coin())


@restricted
async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    emoji = (context.args or ["🎲"])[0]
    await context.bot.send_dice(update.effective_chat.id, emoji=emoji if emoji in DICE_EMOJI else "🎲")


@restricted
async def random_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        low, high = games_logic.parse_range(context.args or [])
    except GameInputError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await update.effective_message.reply_text(f"🎰 {random.randint(low, high)} (от {low} до {high})")


@restricted
async def choose_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        options = games_logic.parse_choices(raw_args(update))
    except GameInputError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await update.effective_message.reply_text(f"🤔 Выбираю… <b>{html.escape(random.choice(options))}</b>!")


@restricted
async def shar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(f"🔮 {games_logic.magic_answer()}")


async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запоминаем, кто пишет в чат — пригодится для /who, если friends.json пуст."""
    user = update.effective_user
    if user is None or user.is_bot or context.chat_data is None:
        return
    seen = context.chat_data.get(SEEN_KEY, {})
    name = f"@{user.username}" if user.username else user.first_name
    if seen.get(user.id) != name:
        context.chat_data[SEEN_KEY] = {**seen, user.id: name}


def register(app: Application) -> None:
    app.add_handler(CommandHandler("poll", poll_command))
    app.add_handler(CommandHandler("who", who_command))
    app.add_handler(CommandHandler("coin", coin_command))
    app.add_handler(CommandHandler("dice", dice_command))
    app.add_handler(CommandHandler("random", random_command))
    app.add_handler(CommandHandler("choose", choose_command))
    app.add_handler(CommandHandler(["shar", "8ball"], shar_command))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, track_user), group=1)
