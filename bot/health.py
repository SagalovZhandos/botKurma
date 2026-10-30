"""Мини HTTP-сервер «я жив» — нужен бесплатным хостингам (Render, Koyeb) и пингеру, чтобы бот не засыпал."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

RESPONSE = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"Content-Length: 2\r\n"
    b"Connection: close\r\n\r\n"
    b"ok"
)


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        await asyncio.wait_for(reader.read(1024), timeout=5)
        writer.write(RESPONSE)
        await writer.drain()
    except (asyncio.TimeoutError, ConnectionError) as exc:
        logger.debug("health: %s", exc)
    finally:
        writer.close()


async def start_health_server(port: int) -> asyncio.base_events.Server:
    server = await asyncio.start_server(_handle, host="0.0.0.0", port=port)
    logger.info("Health-сервер слушает порт %s", port)
    return server
