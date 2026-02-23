"""Webhook server for Gmail Pub/Sub push notifications and Telegram bot."""

import asyncio
import base64
import json
import logging
import os
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse

from src.session import load_session, save_session, session_path

log = logging.getLogger("doot.webhook")

# File to store last Telegram chat_id so Gmail push summaries can be sent to the same chat
def _telegram_chat_id_path() -> Path:
    return session_path().parent / "telegram_chat_id.txt"


def _get_gmail_push_chat_id() -> int | None:
    """Chat ID to send Gmail push summaries to: TELEGRAM_CHAT_ID env, or last user who messaged the bot."""
    env_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if env_id:
        try:
            return int(env_id)
        except ValueError:
            pass
    path = _telegram_chat_id_path()
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return None


def _set_last_telegram_chat_id(chat_id: int) -> None:
    """Remember chat_id so we can send Gmail push summaries to this chat."""
    path = _telegram_chat_id_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(chat_id))


def _send_telegram_text(chat_id: int, text: str) -> None:
    """Send a text message to a Telegram chat. Truncates to TELEGRAM_MAX_MESSAGE_LENGTH."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        log.warning("TELEGRAM_BOT_TOKEN not set; skipping send")
        return
    if len(text) > TELEGRAM_MAX_MESSAGE_LENGTH:
        text = text[: TELEGRAM_MAX_MESSAGE_LENGTH - 3] + "..."
    async def _send() -> None:
        from telegram import Bot
        bot = Bot(token=token)
        await bot.send_message(chat_id=chat_id, text=text)
    asyncio.run(_send())

app = FastAPI(title="Doot webhook", version="0.1.0")

# Telegram message limit
TELEGRAM_MAX_MESSAGE_LENGTH = 4096


def _register_telegram_webhook() -> None:
    """If TELEGRAM_BOT_TOKEN and a base URL are set, set the bot webhook. Uses TELEGRAM_WEBHOOK_BASE_URL or falls back to WEBHOOK_URL (base only)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    base_url = (os.getenv("TELEGRAM_WEBHOOK_BASE_URL") or os.getenv("WEBHOOK_URL") or "").strip().rstrip("/")
    # If WEBHOOK_URL had a path (e.g. .../webhook/gmail), keep only the origin
    if base_url and "/" in base_url[8:]:  # after https://
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
    if not token or not base_url:
        return
    url = f"{base_url}/webhook/telegram"
    try:
        set_webhook_api = f"https://api.telegram.org/bot{token}/setWebhook?url={urllib.parse.quote(url)}"
        req = urllib.request.Request(set_webhook_api, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if data.get("ok"):
            log.info("Telegram webhook registered: %s", url)
        else:
            log.warning("Telegram setWebhook failed: %s", data)
    except Exception as e:
        log.warning("Could not register Telegram webhook: %s", e)


def _check_anthropic_key() -> None:
    """Fail fast at startup if Anthropic API key is missing (avoids opaque 401 later)."""
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        log.warning(
            "ANTHROPIC_API_KEY is not set or empty. Set it in .env to use the router and agents; "
            "otherwise you will get 401 invalid x-api-key from Anthropic."
        )
    else:
        prefix = key[:16] + "..." if len(key) > 16 else key
        log.info("ANTHROPIC_API_KEY loaded (prefix %r, length %d)", prefix, len(key))


@app.on_event("startup")
def _startup() -> None:
    _check_anthropic_key()
    _register_telegram_webhook()


def on_gmail_push(payload: dict) -> None:
    """
    Trigger the orchestrator (which routes to Gmail agent or others): summarize the new email and suggest actions.
    Flow: Gmail Pub/Sub webhook → Orchestrator → Gmail Agent (or other agents if needed).
    payload: decoded Gmail notification {"emailAddress": "...", "historyId": "..."}
    """
    from langchain_core.messages import HumanMessage

    from src.orchestrator_runner import invoke_orchestrator

    prompt = (
        "A new email just arrived. Get the most recent email from my inbox, "
        "summarize it clearly, and suggest specific actions I can take "
        "(e.g. reply, archive, add to calendar, follow up later)."
    )
    try:
        result, last_ai_text = invoke_orchestrator([HumanMessage(content=prompt)])
        log.info("Orchestrator route on Gmail push: %s", result.get("route", "?"))
        if last_ai_text:
            log.info("Orchestrator reply: %s", last_ai_text)
            chat_id = _get_gmail_push_chat_id()
            if chat_id:
                try:
                    _send_telegram_text(chat_id, last_ai_text.strip())
                    log.info("Gmail summary sent to Telegram chat_id=%s", chat_id)
                except Exception as send_err:
                    log.exception("Failed to send Gmail summary to Telegram: %s", send_err)
            else:
                log.debug("No TELEGRAM_CHAT_ID or stored chat_id; Gmail summary not sent to Telegram")
    except Exception as e:
        log.exception("Orchestrator failed on Gmail push: %s", e)


def _decode_gmail_notification(data: str) -> dict | None:
    """Decode Pub/Sub message.data (base64url) to Gmail notification dict."""
    if not data:
        return None
    try:
        # base64url may omit padding
        pad = 4 - len(data) % 4
        if pad != 4:
            data += "=" * pad
        raw = base64.urlsafe_b64decode(data)
        return json.loads(raw)
    except Exception as e:
        log.warning("Failed to decode notification data: %s", e)
        return None


@app.post("/webhook/gmail")
async def gmail_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receive Gmail Pub/Sub push notifications.
    Body: { "message": { "data": "<base64url>", "messageId": "...", ... }, "subscription": "..." }
    Decoded data: { "emailAddress": "...", "historyId": "..." }
    """
    try:
        body = await request.json()
    except Exception as e:
        log.warning("Invalid JSON body: %s", e)
        return JSONResponse(status_code=400, content={"error": "invalid json"})

    message = body.get("message") or {}
    raw_data = message.get("data")
    subscription = body.get("subscription", "")
    message_id = message.get("messageId") or message.get("message_id")

    payload = _decode_gmail_notification(raw_data) if raw_data else None
    if payload:
        log.info(
            "Gmail push: email=%s historyId=%s subscription=%s messageId=%s",
            payload.get("emailAddress"),
            payload.get("historyId"),
            subscription,
            message_id,
        )
    else:
        log.info(
            "Gmail push (raw): subscription=%s messageId=%s data_len=%s",
            subscription,
            message_id,
            len(raw_data) if raw_data else 0,
        )

    if payload:
        background_tasks.add_task(on_gmail_push, payload)

    # 200 = acknowledge so Pub/Sub does not retry
    return JSONResponse(
        status_code=200,
        content={"ok": True, "emailAddress": (payload or {}).get("emailAddress"), "historyId": (payload or {}).get("historyId")},
    )


def process_telegram_message(chat_id: int, text: str) -> None:
    """
    Load global session, append user message, invoke orchestrator, save session, send reply to Telegram.
    Used by both webhook and polling. Sends a short error message to the user on failure.
    """
    from langchain_core.messages import HumanMessage

    from src.orchestrator_runner import invoke_orchestrator

    try:
        messages = load_session()
        messages.append(HumanMessage(content=text))
        result, last_ai_text = invoke_orchestrator(messages)
        save_session(result.get("messages", []))

        reply = (last_ai_text or "No reply generated.").strip()
        _send_telegram_text(chat_id, reply)
    except Exception as e:
        log.exception("Telegram message failed: %s", e)
        try:
            _send_telegram_text(chat_id, "Something went wrong. Please try again later.")
        except Exception as send_err:
            log.exception("Failed to send error message to Telegram: %s", send_err)


def _on_telegram_update(update_dict: dict) -> None:
    """
    Process one Telegram update: parse chat_id and text, then process_telegram_message.
    Runs in a background task. Saves chat_id so Gmail push summaries can be sent to this chat.
    """
    message = (update_dict or {}).get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if not text or chat_id is None:
        return
    _set_last_telegram_chat_id(chat_id)
    process_telegram_message(chat_id, text)


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receive Telegram Bot API updates (webhook mode).
    Body: Telegram Update JSON. Returns 200 quickly; processing runs in background.
    """
    try:
        body = await request.json()
    except Exception as e:
        log.warning("Invalid JSON body for Telegram webhook: %s", e)
        return JSONResponse(status_code=400, content={"error": "invalid json"})

    background_tasks.add_task(_on_telegram_update, body)
    return JSONResponse(status_code=200, content={"ok": True})


def run_webhook_server(host: str = "0.0.0.0", port: int | None = None) -> None:
    """Run the webhook server (for use by CLI)."""
    import uvicorn

    port = port or int(os.getenv("PORT", "8000"))
    log.info("Webhook server starting on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port)
