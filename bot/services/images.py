"""Генерация картинок через Pollinations (бесплатный ключ с enter.pollinations.ai)."""

from __future__ import annotations

import logging
import random
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

GEN_URL = "https://gen.pollinations.ai/image/{prompt}"
# Старый анонимный endpoint: без ключа часто отвечает 402/503, но иногда выручает.
LEGACY_URL = "https://image.pollinations.ai/prompt/{prompt}"
# Z-Image Turbo — не «paid only», списывает копейки из бесплатного дневного баланса.
IMAGE_MODEL = "zimage"
MAX_PROMPT_LENGTH = 800


class ImageError(RuntimeError):
    """Не удалось сгенерировать картинку."""


def build_url(template: str, prompt: str) -> str:
    return template.format(prompt=quote(prompt[:MAX_PROMPT_LENGTH], safe=""))


def attempts(token: str | None) -> tuple[tuple[str, dict[str, str], dict[str, str]], ...]:
    auth = {"Authorization": f"Bearer {token}"} if token else {}
    return (
        (GEN_URL, {"model": IMAGE_MODEL}, auth),
        (LEGACY_URL, {}, {}),
    )


async def generate_image(
    client: httpx.AsyncClient,
    prompt: str,
    token: str | None = None,
    size: int = 1024,
    seed: int | None = None,
) -> bytes:
    base_params: dict[str, str | int] = {
        "width": size,
        "height": size,
        "nologo": "true",
        "seed": seed if seed is not None else random.randint(1, 10**9),
    }
    for template, extra_params, headers in attempts(token):
        try:
            response = await client.get(
                build_url(template, prompt), params={**base_params, **extra_params}, headers=headers, timeout=150
            )
            response.raise_for_status()
            if not response.headers.get("content-type", "").startswith("image/"):
                raise ImageError(f"ответ не картинка: {response.headers.get('content-type')}")
            return response.content
        except (httpx.HTTPError, ImageError) as exc:
            logger.warning("Pollinations %s не сработал: %s", template, exc)
    raise ImageError("Генератор картинок сейчас недоступен")
