"""AI-собеседник: /ask, упоминание бота, ответ на его сообщение, личка."""

from __future__ import annotations

import re

from telegram import Message as TgMessage
from telegram import Update
from telegram.constants import ChatAction, ChatType
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from bot.context import get_services
from bot.handlers.access import cooldown_left, restricted
from bot.handlers.images import draw
from bot.services.ai import AIError, Message

HISTORY_KEY = "ai_history"
HISTORY_LIMIT = 12
TELEGRAM_TEXT_LIMIT = 4000
AI_COOLDOWN = 3
DRAW_INTENT = re.compile(
    r"^\s*(нарисуй|сгенерируй картинку|сгенерируй фото|создай картинку|сделай картинку|салып бер|сурет сал)\b[\s,:]*",
    re.IGNORECASE,
)


def split_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> tuple[str, ...]:
    chunks = tuple(text[i:i + limit] for i in range(0, len(text), limit))
    return chunks or ("…",)


def strip_mention(text: str, username: str) -> str:
    return re.sub(rf"@{re.escape(username)}\b", "", text, flags=re.IGNORECASE).strip(" ,:")


def is_addressed_to_bot(message: TgMessage, bot_id: int, username: str) -> bool:
    if message.chat.type == ChatType.PRIVATE:
        return True
    reply = message.reply_to_message
    if reply and reply.from_user and reply.from_user.id == bot_id:
        return True
    return f"@{username}".lower() in (message.text or "").lower()


def remember(context: ContextTypes.DEFAULT_TYPE, *messages: Message) -> None:
    history: tuple[Message, ...] = context.chat_data.get(HISTORY_KEY, ())
    context.chat_data[HISTORY_KEY] = (*history, *messages)[-HISTORY_LIMIT:]


async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> None:
    message = update.effective_message
    draw_match = DRAW_INTENT.match(question)
    if draw_match:
        await draw(update, context, question[draw_match.end():] or question)
        return
    wait = cooldown_left(context, "ai_last", AI_COOLDOWN)
    if wait:
        await message.reply_text(f"Секунду, я ещё думаю над прошлым вопросом ⏳ ({wait:.0f} c)")
        return

    user = update.effective_user
    author = user.first_name if user else "Кто-то"
    user_text = f"{author}: {question}"
    await context.bot.send_chat_action(message.chat_id, ChatAction.TYPING)
    try:
        reply = await get_services(context).ai.chat(context.chat_data.get(HISTORY_KEY, ()), user_text)
    except AIError:
        await message.reply_text("AI сейчас недоступен 😔 Попробуй чуть позже.")
        return
    remember(context, Message("user", user_text), Message("assistant", reply))
    for chunk in split_text(reply):
        await message.reply_text(chunk, parse_mode=None)


@restricted
async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    question = " ".join(context.args or [])
    reply = update.effective_message.reply_to_message
    if not question and reply and (reply.text or reply.caption):
        question = reply.text or reply.caption
    if not question:
        await update.effective_message.reply_text("Напиши вопрос: /ask почему небо голубое?")
        return
    await answer(update, context, question)


@restricted
async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    username = context.bot.username
    if not message or not message.text or not is_addressed_to_bot(message, context.bot.id, username):
        return
    question = strip_mention(message.text, username)
    if question:
        await answer(update, context, question)


@restricted
async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data[HISTORY_KEY] = ()
    await update.effective_message.reply_text("Забыл весь разговор 🧹")


def register(app: Application) -> None:
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
