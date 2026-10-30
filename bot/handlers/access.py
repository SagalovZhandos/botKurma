"""Кто может пользоваться ботом: чаты из CHAT_IDS и их участники в личке."""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, Coroutine

from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from bot.context import get_services

logger = logging.getLogger(__name__)

MEMBER_CACHE_KEY = "member_cache"
MEMBER_CACHE_TTL = 3600
ACTIVE_STATUSES = {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER}

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]


async def is_group_member(context: ContextTypes.DEFAULT_TYPE, chat_ids: tuple[int, ...], user_id: int) -> bool:
    cache: dict[int, tuple[bool, float]] = context.application.bot_data.setdefault(MEMBER_CACHE_KEY, {})
    cached = cache.get(user_id)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    result, reliable = False, True
    for chat_id in chat_ids:
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
        except BadRequest as exc:  # пользователя в чате нет — это надёжный ответ
            logger.debug("get_chat_member %s/%s: %s", chat_id, user_id, exc)
            continue
        except TelegramError as exc:  # сеть/таймаут — не кэшируем, чтобы не запереть своего на час
            logger.warning("Не удалось проверить участника %s: %s", user_id, exc)
            reliable = False
            continue
        if is_active_member(member):
            result = True
            break
    if result or reliable:
        cache[user_id] = (result, time.monotonic() + MEMBER_CACHE_TTL)
    return result


def is_active_member(member: object) -> bool:
    status = getattr(member, "status", None)
    if status in ACTIVE_STATUSES:
        return True
    # «Ограниченный» (например, в муте) — всё равно участник группы.
    return status == ChatMemberStatus.RESTRICTED and bool(getattr(member, "is_member", False))


async def is_allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = get_services(context).settings
    chat, user = update.effective_chat, update.effective_user
    if chat is None:
        return False
    if chat.id in settings.chat_ids:
        return True
    if chat.type != ChatType.PRIVATE or user is None:
        return False
    return user.id in settings.admin_ids or await is_group_member(context, settings.chat_ids, user.id)


def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    admins = get_services(context).settings.admin_ids
    return user is not None and (not admins or user.id in admins)


def restricted(handler: Handler) -> Handler:
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await is_allowed(update, context):
            await handler(update, context)
            return
        chat = update.effective_chat
        if chat is not None and chat.type == ChatType.PRIVATE and update.effective_message:
            await update.effective_message.reply_text(
                "Я работаю только для своего чата друзей 🙂 Если ты оттуда — сначала вступи в группу."
            )

    return wrapper


def cooldown_left(context: ContextTypes.DEFAULT_TYPE, key: str, seconds: float) -> float:
    """Сколько секунд ещё ждать пользователю. 0 — можно, и отметка обновляется."""
    now = time.monotonic()
    last = context.user_data.get(key, 0.0) if context.user_data is not None else 0.0
    left = seconds - (now - last)
    if left > 0:
        return left
    if context.user_data is not None:
        context.user_data[key] = now
    return 0.0
