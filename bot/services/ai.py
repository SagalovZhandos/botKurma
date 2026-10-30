"""AI-ответы через OpenAI-совместимые API: сначала Groq (бесплатный ключ), потом Pollinations (запасной)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

POLLINATIONS_CHAT_URL = "https://gen.pollinations.ai/v1/chat/completions"
# Без ключа: старый анонимный endpoint, сильно ограничен по частоте — только на крайний случай.
POLLINATIONS_ANON_URL = "https://text.pollinations.ai/openai"
POLLINATIONS_MODEL = "openai"
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)

SYSTEM_PROMPT = (
    "Ты — весёлый и полезный бот в Telegram-чате друзей из Казахстана (Алматы, Астана, Актобе). "
    "Отвечай на языке вопроса (русский или казахский), дружелюбно, по делу и коротко — "
    "обычно до 5–6 предложений, если не просят подробнее. "
    "Не используй Markdown-разметку (звёздочки, решётки), пиши обычным текстом, эмодзи можно. "
    "Если не знаешь точного ответа или он зависит от свежих данных — честно скажи об этом."
)


class AIError(RuntimeError):
    """Ни один AI-провайдер не ответил."""


@dataclass(frozen=True)
class Provider:
    name: str
    url: str
    model: str
    api_key: str | None = None


@dataclass(frozen=True)
class Message:
    role: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


def build_providers(
    ai_url: str, ai_model: str, ai_api_key: str | None, pollinations_token: str | None = None
) -> tuple[Provider, ...]:
    if pollinations_token:
        fallback = Provider("pollinations", POLLINATIONS_CHAT_URL, POLLINATIONS_MODEL, pollinations_token)
    else:
        fallback = Provider("pollinations-anon", POLLINATIONS_ANON_URL, POLLINATIONS_MODEL)
    if not ai_api_key:
        return (fallback,)
    return (Provider("primary", ai_url, ai_model, ai_api_key), fallback)


def clean_answer(text: str) -> str:
    return THINK_BLOCK.sub("", text).strip()


class AIClient:
    def __init__(self, client: httpx.AsyncClient, providers: tuple[Provider, ...]):
        self._client = client
        self._providers = providers

    async def _ask(self, provider: Provider, messages: tuple[Message, ...], max_tokens: int) -> str:
        headers = {"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {}
        payload = {
            "model": provider.model,
            "messages": [m.as_dict() for m in messages],
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }
        response = await self._client.post(provider.url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        answer = clean_answer(response.json()["choices"][0]["message"]["content"] or "")
        if not answer:
            raise AIError(f"{provider.name}: пустой ответ")
        return answer

    async def complete(self, messages: tuple[Message, ...], max_tokens: int = 800) -> str:
        for provider in self._providers:
            try:
                return await self._ask(provider, messages, max_tokens)
            except (httpx.HTTPError, KeyError, IndexError, ValueError, AIError) as exc:
                logger.warning("AI-провайдер %s не ответил: %s", provider.name, exc)
        raise AIError("Все AI-провайдеры недоступны")

    async def chat(self, history: tuple[Message, ...], question: str) -> str:
        messages = (Message("system", SYSTEM_PROMPT), *history, Message("user", question))
        return await self.complete(messages)

    async def to_image_prompt(self, request: str) -> str:
        """Переводит запрос на английский и слегка уточняет — так генератор картинок понимает лучше."""
        messages = (
            Message(
                "system",
                "Convert the user's request into a concise English prompt for an image generator. "
                "Keep the meaning, add helpful visual details, max 60 words. Output only the prompt.",
            ),
            Message("user", request),
        )
        try:
            return (await self.complete(messages, max_tokens=150)).strip().strip('"')
        except AIError:
            return request
