"""«Умный друг»: читает весь чат, отвечает, когда зовут, и иногда сам вставляет реплику."""

from __future__ import annotations

import html
import logging
import re
import time
from datetime import datetime

from telegram import Message as TgMessage
from telegram import Update
from telegram.constants import ChatAction, ChatType
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from bot import conversation
from bot.context import get_services
from bot.conversation import AmbientMode, AmbientState, LogEntry
from bot.handlers.access import cooldown_left, is_allowed, restricted
from bot.handlers.images import draw
from bot.services.ai import AIError

logger = logging.getLogger(__name__)

LOG_KEY = "chat_log"
AMBIENT_KEY = "ambient_state"
MODE_KEY = "ambient_mode"
BOT_AUTHOR = "бот"
TELEGRAM_TEXT_LIMIT = 4000
AI_COOLDOWN = 3
# Решение «встревать ли» тонкое: даём модели подумать подольше (medium) — иначе лезет в личные разговоры.
AMBIENT_MAX_TOKENS = 1500
AMBIENT_REASONING = "medium"
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


def message_text(message: TgMessage) -> str | None:
    if message.text:
        return message.text
    if message.caption:
        return f"[фото] {message.caption}"
    return None


def log_entry_for(message: TgMessage, bot_id: int) -> LogEntry | None:
    text, user = message_text(message), message.from_user
    if not text or text.startswith("/") or user is None or user.is_bot:
        return None
    reply = message.reply_to_message
    if reply and reply.from_user and reply.from_user.id != user.id:
        target = "тебе" if reply.from_user.id == bot_id else reply.from_user.first_name
        text = f"(в ответ {target}) {text}"
    return LogEntry(user.first_name, text)


def remember(context: ContextTypes.DEFAULT_TYPE, *entries: LogEntry) -> None:
    context.chat_data[LOG_KEY] = conversation.append(context.chat_data.get(LOG_KEY, ()), *entries)


def current_mode(context: ContextTypes.DEFAULT_TYPE) -> AmbientMode:
    key = context.chat_data.get(MODE_KEY) or get_services(context).settings.ambient_mode
    return conversation.MODES[key]


def mark_bot_spoke(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    remember(context, LogEntry(BOT_AUTHOR, text, from_bot=True))
    state: AmbientState = context.chat_data.get(AMBIENT_KEY, AmbientState())
    context.chat_data[AMBIENT_KEY] = state.with_reply(time.monotonic())


def extra_system(context: ContextTypes.DEFAULT_TYPE) -> str:
    services = get_services(context)
    return conversation.now_line(datetime.now(services.settings.timezone))


# ---------- чтение всех сообщений ----------

async def log_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запоминаем каждое сообщение (только в памяти), чтобы бот понимал контекст разговора."""
    message = update.effective_message
    if message is None or context.chat_data is None:
        return
    entry = log_entry_for(message, context.bot.id)
    if entry and await is_allowed(update, context):
        remember(context, entry)


# ---------- ответ, когда зовут ----------

async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str, logged: bool) -> None:
    message = update.effective_message
    draw_match = DRAW_INTENT.match(question)
    if draw_match:
        await draw(update, context, question[draw_match.end():] or question)
        return
    wait = cooldown_left(context, "ai_last", AI_COOLDOWN)
    if wait:
        await message.reply_text(f"Секунду, я ещё думаю над прошлым вопросом ⏳ ({wait:.0f} c)")
        return
    if not logged:
        user = update.effective_user
        remember(context, LogEntry(user.first_name if user else "Кто-то", question))

    await context.bot.send_chat_action(message.chat_id, ChatAction.TYPING)
    log = context.chat_data.get(LOG_KEY, ())
    try:
        reply = await get_services(context).ai.chat(conversation.to_messages(log), extra_system(context))
    except AIError:
        await message.reply_text("AI сейчас недоступен 😔 Попробуй чуть позже.")
        return
    mark_bot_spoke(context, reply)
    for chunk in split_text(reply):
        await message.reply_text(chunk, parse_mode=None)


@restricted
async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    question = " ".join(context.args or [])
    reply = update.effective_message.reply_to_message
    if not question and reply and (reply.text or reply.caption):
        question = reply.text or reply.caption or ""
    if not question:
        await update.effective_message.reply_text("Напиши вопрос: /ask почему небо голубое?")
        return
    await answer(update, context, question, logged=False)


# ---------- самостоятельные реплики ----------

def schedule_ambient(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Ждём паузу в разговоре: каждое новое сообщение переносит проверку."""
    mode = current_mode(context)
    if mode.checks_per_hour <= 0 or context.job_queue is None:
        return
    name = f"ambient-{chat_id}"
    for job in context.job_queue.get_jobs_by_name(name):
        job.schedule_removal()
    context.job_queue.run_once(ambient_job, mode.delay, chat_id=chat_id, name=name)


async def ambient_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = context.job.chat_id
    state: AmbientState = context.chat_data.get(AMBIENT_KEY, AmbientState())
    log: tuple[LogEntry, ...] = context.chat_data.get(LOG_KEY, ())
    now = time.monotonic()
    if not log or log[-1].from_bot or not conversation.should_check(state, current_mode(context), now):
        return
    context.chat_data[AMBIENT_KEY] = state.with_check(now)
    prompt = f"{extra_system(context)}\n{conversation.AMBIENT_PROMPT}"
    try:
        raw = await get_services(context).ai.chat(
            conversation.to_messages(log),
            prompt,
            max_tokens=AMBIENT_MAX_TOKENS,
            primary_only=True,
            reasoning=AMBIENT_REASONING,
        )
    except AIError:
        return  # лимит или сбой — просто промолчим
    reply = conversation.parse_ambient_reply(raw)
    if reply is None:
        return
    try:
        await context.bot.send_message(chat_id, reply, parse_mode=None)
    except TelegramError as exc:
        logger.warning("Не удалось отправить реплику в %s: %s", chat_id, exc)
        return
    mark_bot_spoke(context, reply)


@restricted
async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    username = context.bot.username
    if not message or not message.text:
        return
    if is_addressed_to_bot(message, context.bot.id, username):
        question = strip_mention(message.text, username)
        if question:
            await answer(update, context, question, logged=True)
    elif message.chat.type != ChatType.PRIVATE:
        schedule_ambient(context, message.chat_id)


# ---------- управление ----------

@restricted
async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(context.args or [])
    mode = conversation.resolve_mode(raw) if raw else None
    if mode is None:
        options = "\n".join(f"• {html.escape(m.title)}" for m in conversation.MODES.values())
        await update.effective_message.reply_text(
            f"Сейчас: <b>{html.escape(current_mode(context).title)}</b>\n\n"
            f"Как часто мне вступать в разговор самому:\n{options}\n\n"
            "Пример: /mode тихо (или выкл, обычно, активно)"
        )
        return
    context.chat_data[MODE_KEY] = mode.key
    await update.effective_message.reply_text(f"Ок 👌 Режим: <b>{html.escape(mode.title)}</b>")


@restricted
async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data[LOG_KEY] = ()
    await update.effective_message.reply_text("Забыл весь разговор 🧹")


def register(app: Application) -> None:
    # Группа -1 срабатывает раньше остальных: сначала запоминаем сообщение, потом отвечаем.
    app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, log_message), group=-1)
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("mode", mode_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
