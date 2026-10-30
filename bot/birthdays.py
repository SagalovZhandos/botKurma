"""Тексты поздравлений и напоминаний о днях рождения."""

from __future__ import annotations

import html
import random
from datetime import date

from bot.days import human_date
from bot.friends import Friend, age_on, birthdays_on, upcoming_birthdays
from bot.services.ai import AIClient, AIError, Message

TEMPLATE_WISHES = (
    "Пусть этот год будет полон радости, здоровья и крутых приключений!",
    "Желаем, чтобы всё задуманное сбывалось, а рядом всегда были близкие люди!",
    "Туған күніңмен! Бақыт, денсаулық және көп қуаныш тілейміз!",
    "Пусть удача будет на твоей стороне, а поводов улыбаться — каждый день!",
)


def age_suffix(age: int) -> str:
    if age % 10 == 1 and age % 100 != 11:
        return "год"
    if age % 10 in (2, 3, 4) and age % 100 not in (12, 13, 14):
        return "года"
    return "лет"


def greeting_header(friend: Friend, day: date) -> str:
    age = age_on(friend, day)
    age_text = f" Сегодня {age} {age_suffix(age)}!" if age else ""
    return f"🎉🎂 <b>Туған күніңмен, {html.escape(friend.mention)}!</b>{age_text}"


async def ai_wish(ai: AIClient | None, friend: Friend) -> str | None:
    if ai is None:
        return None
    prompt = (
        f"Напиши короткое (2–3 предложения) тёплое и немного весёлое поздравление с днём рождения "
        f"для друга по имени {friend.name} от лица чата друзей. Можно добавить пару слов на казахском. "
        f"Без Markdown."
    )
    try:
        return await ai.complete((Message("user", prompt),), max_tokens=200)
    except AIError:
        return None


async def build_greeting(friend: Friend, day: date, ai: AIClient | None) -> str:
    wish = await ai_wish(ai, friend) or random.choice(TEMPLATE_WISHES)
    return f"{greeting_header(friend, day)}\n\n{html.escape(wish)}"


def reminder_text(friends: tuple[Friend, ...], today: date, days_ahead: int) -> str | None:
    """Напоминание ровно за `days_ahead` дней — чтобы успеть придумать подарок."""
    if days_ahead <= 0:
        return None
    target = date.fromordinal(today.toordinal() + days_ahead)
    soon = birthdays_on(friends, target)
    if not soon:
        return None
    names = ", ".join(html.escape(f.name) for f in soon)
    return f"⏰ Через {days_ahead} дн. ({human_date(target)}) день рождения у: <b>{names}</b>. Готовим поздравление? 🎁"


def upcoming_text(friends: tuple[Friend, ...], today: date, days: int = 60) -> str:
    items = upcoming_birthdays(friends, today, days)
    if not items:
        return f"В ближайшие {days} дней дней рождения нет 🤷"
    lines = ["🎂 <b>Ближайшие дни рождения</b>"]
    for friend, when in items:
        left = (when - today).days
        when_text = "сегодня! 🎉" if left == 0 else f"{human_date(when)} (через {left} дн.)"
        lines.append(f"• {html.escape(friend.name)} — {when_text}")
    return "\n".join(lines)
