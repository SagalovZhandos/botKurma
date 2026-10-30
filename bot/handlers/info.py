"""/start, /help, /chatid."""

from __future__ import annotations

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes

HELP_TEXT = """👋 <b>Сәлем! Я бот вашего чата.</b>

<b>Каждый день сам:</b>
• в полночь меняю название группы на день недели (Дүйсенбі, Сейсенбі…)
• утром присылаю погоду, качество воздуха, курс валют, праздники, «в этот день» и мысль дня
• поздравляю с днями рождения и напоминаю заранее

<b>Спросить меня:</b> упомяните меня, ответьте на моё сообщение или /ask вопрос
<b>Нарисовать:</b> /img кот-космонавт на коне — или «нарисуй …» в обращении ко мне

<b>По запросу:</b> /weather /air /rates /today /quote /digest /birthdays
<b>Игры:</b> /poll /who /coin /dice /random /choose /shar
<b>Служебное:</b> /chatid /settitle"""

COMMANDS = (
    BotCommand("ask", "Задать вопрос AI"),
    BotCommand("img", "Нарисовать картинку"),
    BotCommand("weather", "Погода сейчас"),
    BotCommand("air", "Качество воздуха"),
    BotCommand("rates", "Курс валют"),
    BotCommand("today", "Праздники и события дня"),
    BotCommand("quote", "Мысль дня"),
    BotCommand("digest", "Утренняя сводка целиком"),
    BotCommand("birthdays", "Ближайшие дни рождения"),
    BotCommand("poll", "Опрос: вопрос | вариант | вариант"),
    BotCommand("who", "Кто сегодня…?"),
    BotCommand("coin", "Подбросить монетку"),
    BotCommand("dice", "Бросить кубик"),
    BotCommand("random", "Случайное число"),
    BotCommand("choose", "Выбрать из вариантов"),
    BotCommand("shar", "Шар судьбы"),
    BotCommand("help", "Что я умею"),
)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_TEXT)


async def chat_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat, user = update.effective_chat, update.effective_user
    await update.effective_message.reply_text(
        f"ID этого чата: <code>{chat.id}</code>\nТвой ID: <code>{user.id if user else '—'}</code>"
    )


def register(app: Application) -> None:
    app.add_handler(CommandHandler(["start", "help"], help_command))
    app.add_handler(CommandHandler("chatid", chat_id_command))
