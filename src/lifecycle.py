"""FastAPI lifespan: startup and shutdown. Use instead of deprecated on_event("startup")."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger("doot.lifecycle")


@asynccontextmanager
async def lifespan(app: "FastAPI"):
    """Startup: check Anthropic key, register Telegram webhook, start heartbeat loop. Shutdown: cancel heartbeat."""
    # Late import to avoid circular dependency (webhook imports lifespan; we need webhook loaded first)
    from src.webhook import (
        HEARTBEAT_INTERVAL_SEC,
        _check_anthropic_key,
        _heartbeat_loop,
        _register_telegram_webhook,
    )

    _check_anthropic_key()
    _register_telegram_webhook()
    heartbeat_task = None
    if HEARTBEAT_INTERVAL_SEC > 0:
        heartbeat_task = asyncio.create_task(_heartbeat_loop())
        log.info("Heartbeat enabled every %s seconds", HEARTBEAT_INTERVAL_SEC)

    yield

    if heartbeat_task is not None:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
