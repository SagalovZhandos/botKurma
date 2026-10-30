"""«Умный друг»: журнал чата, режимы болтливости и решение, когда вмешаться (без Telegram)."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime

from bot.days import human_date, kazakh_day
from bot.services.ai import Message

LOG_LIMIT = 40
ENTRY_CHAR_LIMIT = 500
CONTEXT_CHAR_LIMIT = 6000
HOUR = 3600.0
SKIP_WORD = "SKIP"

AMBIENT_PROMPT = (
    "Сейчас тебя никто не звал — ты просто читаешь чат как один из друзей. Реши, стоит ли вставить реплику. "
    "Пиши, если: кто-то задал вопрос, на который ты знаешь полезный ответ; просят совета или спорят о факте; "
    "есть удачный повод для короткой шутки или поддержки. "
    "Не пиши, если: кто-то делится переживаниями или проблемами и ему уже отвечает другой человек; "
    "двое договариваются или говорят о личном между собой; это обычная болтовня, где тебе нечего добавить; "
    "последнее сообщение в чате — твоё. В сомнительных случаях лучше промолчать. "
    "Пиши на том же языке, на котором написаны последние сообщения, и внимательно смотри, кто что сказал. "
    f"Если вмешиваться не нужно — ответь ровно одним словом {SKIP_WORD}. "
    "Если нужно — напиши короткую реплику (1–3 предложения) как друг в чате, без своего имени в начале."
)


@dataclass(frozen=True)
class LogEntry:
    author: str
    text: str
    from_bot: bool = False


@dataclass(frozen=True)
class AmbientMode:
    key: str
    title: str
    delay: float  # ждём паузу в разговоре, чтобы не дёргать AI на каждое сообщение
    cooldown: float  # минимум между самостоятельными репликами
    checks_per_hour: int  # ограничение расхода бесплатного лимита Groq


MODES: dict[str, AmbientMode] = {
    "off": AmbientMode("off", "выкл — отвечаю только когда зовут", 0, 0, 0),
    "quiet": AmbientMode("quiet", "тихо — изредка, только по делу", 45, 20 * 60, 6),
    "normal": AmbientMode("normal", "обычно — иногда вставляю реплику", 25, 5 * 60, 15),
    "active": AmbientMode("active", "активно — участвую в разговоре", 12, 60, 40),
}
MODE_ALIASES = {
    "выкл": "off", "off": "off", "тихо": "quiet", "quiet": "quiet",
    "обычно": "normal", "normal": "normal", "активно": "active", "active": "active",
}


@dataclass(frozen=True)
class AmbientState:
    last_reply: float = float("-inf")
    checks: tuple[float, ...] = ()

    def recent_checks(self, now: float) -> tuple[float, ...]:
        return tuple(t for t in self.checks if now - t < HOUR)

    def with_check(self, now: float) -> AmbientState:
        return replace(self, checks=(*self.recent_checks(now), now))

    def with_reply(self, now: float) -> AmbientState:
        return replace(self, last_reply=now)


def resolve_mode(raw: str) -> AmbientMode | None:
    key = MODE_ALIASES.get(raw.strip().lower())
    return MODES[key] if key else None


def should_check(state: AmbientState, mode: AmbientMode, now: float) -> bool:
    if mode.checks_per_hour <= 0:
        return False
    if now - state.last_reply < mode.cooldown:
        return False
    return len(state.recent_checks(now)) < mode.checks_per_hour


def append(log: tuple[LogEntry, ...], *entries: LogEntry) -> tuple[LogEntry, ...]:
    trimmed = tuple(replace(e, text=e.text[:ENTRY_CHAR_LIMIT]) for e in entries)
    return (*log, *trimmed)[-LOG_LIMIT:]


def to_messages(log: tuple[LogEntry, ...], max_chars: int = CONTEXT_CHAR_LIMIT) -> tuple[Message, ...]:
    """Последние сообщения чата в формате для AI, не длиннее max_chars (свежие важнее)."""
    picked: list[LogEntry] = []
    total = 0
    for entry in reversed(log):
        total += len(entry.text) + len(entry.author) + 2
        if picked and total > max_chars:
            break
        picked.append(entry)
    return tuple(
        Message("assistant", e.text) if e.from_bot else Message("user", f"{e.author}: {e.text}")
        for e in reversed(picked)
    )


def now_line(moment: datetime) -> str:
    return f"Сейчас {kazakh_day(moment.date())}, {human_date(moment.date())} {moment.year}, {moment:%H:%M} (Алматы)."


def parse_ambient_reply(text: str) -> str | None:
    """None, если бот решил промолчать."""
    cleaned = re.sub(r"^\s*(бот|bot|я)\s*:\s*", "", text.strip(), flags=re.IGNORECASE).strip()
    if not cleaned or cleaned.upper().strip(" .!\"'«»") == SKIP_WORD or cleaned.upper().startswith(SKIP_WORD):
        return None
    return cleaned
