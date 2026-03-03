"""Webhook server for Telegram bot and heartbeat (email/calendar checked on schedule)."""

import asyncio
import base64
import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse

from src.lifecycle import lifespan
from src.memory.claw_store import get_memory_root
from src.session import load_session, save_session, session_path, trim_messages_to_window
from src.utils.telegram_format import format_orchestrator_reply_for_telegram

log = logging.getLogger("doot.webhook")

# Heartbeat interval in seconds (default 30 minutes); override with DOOT_HEARTBEAT_INTERVAL_SEC
HEARTBEAT_INTERVAL_SEC = int(os.getenv("DOOT_HEARTBEAT_INTERVAL_SEC", str(30 * 60)))
# Sentinel: if the agent replies with this (or starts with it), we do not send to Telegram
HEARTBEAT_OK = "HEARTBEAT_OK"

# Default checklist when HEARTBEAT.md is missing
_DEFAULT_HEARTBEAT_CHECKLIST = (
    "Check email and calendar for anything needing attention. "
    "If nothing requires the user's attention, reply with exactly HEARTBEAT_OK."
)

# Schedule: timezone and path for scheduled tasks (e.g. daily report at 7am)
DOOT_SCHEDULE_TZ = os.getenv("DOOT_SCHEDULE_TZ", "America/New_York")
DOOT_SCHEDULE_PATH_ENV = os.getenv("DOOT_SCHEDULE_PATH")

# Report prompt default when REPORT_PROMPT.md is missing
_DEFAULT_REPORT_PROMPT = (
    "Search the web for current weather in {location} and recent police or public safety activity or incidents in {location}. "
    "Compile a brief daily report with dates and sources. Use a neutral tone."
)


# File to store last Telegram chat_id so heartbeat/report summaries can be sent to the same chat
def _telegram_chat_id_path() -> Path:
    return session_path().parent / "telegram_chat_id.txt"


def _get_telegram_summary_chat_id() -> int | None:
    """Chat ID to send heartbeat/report summaries to: TELEGRAM_CHAT_ID env, or last user who messaged the bot."""
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
    """Remember chat_id so we can send heartbeat/report summaries to this chat."""
    path = _telegram_chat_id_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(chat_id))


def _download_telegram_photo(file_id: str) -> bytes | None:
    """
    Download photo bytes from Telegram by file_id. Uses getFile then GET file URL.
    Returns None on failure. Runs synchronously for use in background task.
    """
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        return None
    try:
        get_url = f"https://api.telegram.org/bot{token}/getFile?file_id={urllib.parse.quote(file_id)}"
        with urllib.request.urlopen(get_url, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        ok = data.get("ok")
        result = data.get("result") or {}
        file_path = result.get("file_path")
        if not ok or not file_path:
            log.warning("Telegram getFile failed or no file_path: %s", data)
            return None
        download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        with urllib.request.urlopen(download_url, timeout=30) as resp:
            return resp.read()
    except Exception as e:
        log.warning("Failed to download Telegram photo: %s", e)
        return None


def _heartbeat_md_path() -> Path:
    """Path for HEARTBEAT.md (same root as MEMORY.md and session)."""
    return get_memory_root() / "HEARTBEAT.md"


def _load_heartbeat_checklist() -> str:
    """Load checklist from HEARTBEAT.md or return default."""
    path = _heartbeat_md_path()
    if path.exists():
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as e:
            log.warning("Could not read HEARTBEAT.md at %s: %s", path, e)
    return _DEFAULT_HEARTBEAT_CHECKLIST


def _schedule_path() -> Path:
    """Path for schedule file (JSON or markdown)."""
    if DOOT_SCHEDULE_PATH_ENV:
        return Path(DOOT_SCHEDULE_PATH_ENV).expanduser()
    return get_memory_root() / "schedule.json"


def _last_run_path() -> Path:
    """Path for last-run state (task_id -> date string)."""
    return get_memory_root() / "schedule_last_run.json"


def _load_schedule() -> list[dict]:
    """Load schedule: list of {time, task_id, recurrence, delivery}. Returns [] if missing or invalid."""
    path = _schedule_path()
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if path.suffix.lower() == ".json":
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        # SCHEDULE.md: lines like "07:00 report daily email"
        lines = []
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 4:
                lines.append({
                    "time": parts[0],
                    "task_id": parts[1],
                    "recurrence": parts[2],
                    "delivery": parts[3],
                })
        return lines
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Could not load schedule from %s: %s", path, e)
        return []


def _load_last_run() -> dict[str, str]:
    """Load last-run state: {task_id: "YYYY-MM-DD"}."""
    path = _last_run_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_last_run(task_id: str, date_str: str) -> None:
    """Record that task_id was run on date_str."""
    path = _last_run_path()
    state = _load_last_run()
    state[task_id] = date_str
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _get_due_tasks() -> list[dict]:
    """Return list of schedule entries that are due (scheduled time passed today and not yet run today)."""
    tz = ZoneInfo(DOOT_SCHEDULE_TZ)
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    last_run = _load_last_run()
    schedule = _load_schedule()
    due = []
    for entry in schedule:
        task_id = entry.get("task_id")
        if not task_id:
            continue
        if last_run.get(task_id) == today:
            continue
        time_str = entry.get("time") or "00:00"
        try:
            hour, minute = map(int, time_str.split(":")[:2])
        except (ValueError, AttributeError):
            continue
        # scheduled time today in same TZ
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now >= scheduled:
            due.append(entry)
    return due


def _report_prompt_path() -> Path:
    """Path for REPORT_PROMPT.md."""
    path_env = os.getenv("DOOT_REPORT_PROMPT_PATH")
    if path_env:
        return Path(path_env).expanduser()
    return get_memory_root() / "REPORT_PROMPT.md"


def _load_report_prompt() -> str:
    """Load report prompt from REPORT_PROMPT.md or return default with location placeholder filled."""
    path = _report_prompt_path()
    location = os.getenv("DOOT_REPORT_LOCATION", "Providence, RI")
    if path.exists():
        try:
            return path.read_text(encoding="utf-8").strip().replace("[location]", location).replace("{location}", location)
        except OSError as e:
            log.warning("Could not read REPORT_PROMPT.md at %s: %s", path, e)
    return _DEFAULT_REPORT_PROMPT.format(location=location)


def _run_report_turn() -> str | None:
    """
    Run one report turn: load report prompt, invoke orchestrator (no session), return last_ai_text or None.
    Called from async via asyncio.to_thread.
    """
    from langchain_core.messages import HumanMessage

    from src.orchestrator_runner import invoke_orchestrator

    prompt = _load_report_prompt()
    try:
        result, last_ai_text = invoke_orchestrator([HumanMessage(content=prompt)])
        return last_ai_text or None
    except Exception as e:
        log.exception("Report turn failed: %s", e)
        return None


def _run_scheduled_task_sync(task_id: str, delivery: str) -> str | None:
    """Run the scheduled task (e.g. report) and return result text for delivery. Returns None on failure."""
    if task_id != "report":
        log.warning("Unknown scheduled task_id=%s", task_id)
        return None
    return _run_report_turn()


async def _run_scheduled_task_async(entry: dict) -> None:
    """Run a due scheduled task in the background: run turn, save report file, send email, update last-run."""
    task_id = entry.get("task_id", "")
    delivery = entry.get("delivery", "email")
    tz = ZoneInfo(DOOT_SCHEDULE_TZ)
    today = datetime.now(tz).strftime("%Y-%m-%d")
    try:
        result_text = await asyncio.to_thread(_run_scheduled_task_sync, task_id, delivery)
        if result_text is None or not result_text.strip():
            log.warning("Scheduled task %s produced no output", task_id)
            return
        # Save to .doot/reports/YYYY-MM-DD.md
        reports_dir = get_memory_root() / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_file = reports_dir / f"{today}.md"
        report_file.write_text(result_text.strip(), encoding="utf-8")
        log.info("Report saved to %s", report_file)
        # Send email
        to_email = os.getenv("DOOT_REPORT_TO_EMAIL") or os.getenv("USER_EMAIL")
        if to_email and delivery == "email":
            try:
                from src.agents.gmail.client import send_message
                send_message(
                    to_email=to_email.strip(),
                    subject=f"Doot daily report – {today}",
                    body=result_text.strip(),
                )
                log.info("Report email sent to %s", to_email)
            except Exception as e:
                log.exception("Failed to send report email: %s", e)
        # Optional Telegram summary
        chat_id = _get_telegram_summary_chat_id()
        if chat_id:
            try:
                _send_telegram_text(
                    chat_id,
                    f"Daily report sent to your email and saved to .doot/reports/{today}.md.",
                )
            except Exception as e:
                log.warning("Failed to send report summary to Telegram: %s", e)
        _save_last_run(task_id, today)
    except Exception as e:
        log.exception("Scheduled task %s failed: %s", task_id, e)


def _send_telegram_typing(chat_id: int) -> None:
    """Send the typing chat action to a Telegram chat (shows \"typing...\" for ~5 seconds)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return
    async def _send() -> None:
        from telegram import Bot
        from telegram.constants import ChatAction
        bot = Bot(token=token)
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        asyncio.run(_send())
    except Exception as e:
        log.debug("Telegram typing action failed: %s", e)


async def _send_telegram_text_async(
    chat_id: int, text: str, *, already_formatted_for_telegram: bool = False
) -> None:
    """
    Send a text message to a Telegram chat (async). Use from async code (e.g. heartbeat loop).
    If already_formatted_for_telegram is True, text is Telegram HTML and is sent with parse_mode=HTML.
    Otherwise text is treated as plain (no HTML). Truncates to TELEGRAM_MAX_MESSAGE_LENGTH.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        log.warning("TELEGRAM_BOT_TOKEN not set; skipping send")
        return
    if len(text) > TELEGRAM_MAX_MESSAGE_LENGTH:
        text = text[: TELEGRAM_MAX_MESSAGE_LENGTH - 3] + "..."
    from telegram import Bot
    from telegram.constants import ParseMode
    bot = Bot(token=token)
    kwargs = {"chat_id": chat_id, "text": text}
    if already_formatted_for_telegram:
        kwargs["parse_mode"] = ParseMode.HTML
    await bot.send_message(**kwargs)


def _send_telegram_text(chat_id: int, text: str, *, already_formatted_for_telegram: bool = False) -> None:
    """
    Send a text message to a Telegram chat (sync). Use from sync code only.
    From async code (e.g. _heartbeat_loop), use await _send_telegram_text_async() instead.
    """
    asyncio.run(_send_telegram_text_async(chat_id, text, already_formatted_for_telegram=already_formatted_for_telegram))

app = FastAPI(title="Doot webhook", version="0.1.0", lifespan=lifespan)

# Telegram message limit
TELEGRAM_MAX_MESSAGE_LENGTH = 4096


def _register_telegram_webhook() -> None:
    """If TELEGRAM_BOT_TOKEN and a base URL are set, set the bot webhook. Uses TELEGRAM_WEBHOOK_BASE_URL or falls back to WEBHOOK_URL (base only)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    base_url = (os.getenv("TELEGRAM_WEBHOOK_BASE_URL") or os.getenv("WEBHOOK_URL") or "").strip().rstrip("/")
    # If WEBHOOK_URL had a path, keep only the origin
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


def _run_heartbeat_turn() -> tuple[str, str] | None:
    """
    Run one heartbeat turn: load session, append heartbeat message (instruction + checklist),
    invoke orchestrator, save session. Returns (last_ai_text, route) or None on failure.
    Called from async loop via asyncio.to_thread so it does not block the event loop.
    """
    from langchain_core.messages import HumanMessage

    from src.orchestrator_runner import invoke_orchestrator

    checklist = _load_heartbeat_checklist()
    instruction = (
        "This is a scheduled heartbeat. Follow the checklist below. "
        "Use your tools (Gmail, Calendar, memory) as needed. "
        "If nothing requires the user's attention, reply with exactly HEARTBEAT_OK and nothing else. "
        "Otherwise briefly summarize what needs attention.\n\n"
    )
    body = instruction + checklist
    try:
        full_messages = load_session()
        to_send = trim_messages_to_window(full_messages)
        to_send.append(HumanMessage(content=body))
        result, last_ai_text = invoke_orchestrator(to_send)
        save_session(full_messages + [HumanMessage(content=body)] + [AIMessage(content=last_ai_text or "")])
        route = result.get("route", "?")
        log.info("Heartbeat turn completed, route=%s", route)
        return (last_ai_text or "", route)
    except Exception as e:
        log.exception("Heartbeat turn failed: %s", e)
        return None


def _is_heartbeat_ok(last_ai_text: str) -> bool:
    """True if the reply indicates nothing to report (do not send to Telegram)."""
    t = last_ai_text.strip()
    if not t:
        return True
    upper = t.upper()
    return upper == HEARTBEAT_OK or upper.startswith(HEARTBEAT_OK)


async def _heartbeat_loop() -> None:
    """Every HEARTBEAT_INTERVAL_SEC, run HEARTBEAT.md checklist; then check schedule and kick off any due tasks."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
        # Run normal heartbeat (email/calendar checklist)
        result = await asyncio.to_thread(_run_heartbeat_turn)
        if result is not None:
            last_ai_text, _route = result
            last_ai_text = (last_ai_text or "").strip()
            if not _is_heartbeat_ok(last_ai_text):
                chat_id = _get_telegram_summary_chat_id()
                if chat_id:
                    try:
                        formatted = format_orchestrator_reply_for_telegram(last_ai_text)
                        await _send_telegram_text_async(chat_id, formatted, already_formatted_for_telegram=True)
                        log.info("Heartbeat reported something, sent to Telegram chat_id=%s", chat_id)
                    except Exception as e:
                        log.warning("Heartbeat Telegram send failed: %s", e)
                        try:
                            await _send_telegram_text_async(chat_id, last_ai_text)
                        except Exception:
                            pass
            else:
                log.info("Heartbeat (nothing to report)")
        # Check current time and kick off any due scheduled tasks (e.g. daily report at 7am)
        for entry in _get_due_tasks():
            task_id = entry.get("task_id")
            if task_id:
                log.info("Kicking off scheduled task: %s", task_id)
                asyncio.create_task(_run_scheduled_task_async(entry))


def process_telegram_message(chat_id: int, content: str | list) -> None:
    """
    Load global session, append user message, invoke orchestrator, save session, send reply to Telegram.
    content: plain text (str) or multimodal list of blocks (e.g. text + image_url for photos).
    Used by both webhook and polling. Sends a short error message to the user on failure.
    Shows typing indicator while processing (repeated every 4s until reply is sent).
    """
    import threading

    from langchain_core.messages import AIMessage, HumanMessage

    from src.orchestrator_runner import invoke_orchestrator

    stop_typing = threading.Event()

    def _typing_loop() -> None:
        _send_telegram_typing(chat_id)
        while not stop_typing.wait(timeout=4):
            _send_telegram_typing(chat_id)

    try:
        _send_telegram_typing(chat_id)
        typing_thread = threading.Thread(target=_typing_loop, daemon=True)
        typing_thread.start()

        try:
            full_messages = load_session()
            to_send = trim_messages_to_window(full_messages)
            to_send.append(HumanMessage(content=content))
            result, last_ai_text = invoke_orchestrator(to_send)
            save_session(full_messages + [HumanMessage(content=content)] + [AIMessage(content=last_ai_text or "")])

            reply = (last_ai_text or "No reply generated.").strip()
            try:
                reply = format_orchestrator_reply_for_telegram(reply)
                _send_telegram_text(chat_id, reply, already_formatted_for_telegram=True)
            except Exception as fmt_err:
                log.warning("Telegram formatting failed, sending plain: %s", fmt_err)
                _send_telegram_text(chat_id, (last_ai_text or "No reply generated.").strip())
        finally:
            stop_typing.set()
            typing_thread.join(timeout=5)
    except Exception as e:
        log.exception("Telegram message failed: %s", e)
        stop_typing.set()
        try:
            _send_telegram_text(chat_id, "Something went wrong. Please try again later.")
        except Exception as send_err:
            log.exception("Failed to send error message to Telegram: %s", send_err)


def _on_telegram_update(update_dict: dict) -> None:
    """
    Process one Telegram update: parse chat_id and text or photo, then process_telegram_message.
    Runs in a background task. Saves chat_id so heartbeat/report summaries can be sent to this chat.
    Supports text messages and photo messages (with optional caption). Photo + caption sent as multimodal.
    """
    message = (update_dict or {}).get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return

    text = (message.get("text") or "").strip()
    photos = message.get("photo") or []

    # Photo (with or without caption): download and send as multimodal content
    if photos:
        file_id = photos[-1].get("file_id")  # largest size
        if not file_id:
            return
        caption = (message.get("caption") or "").strip() or text
        photo_bytes = _download_telegram_photo(file_id)
        if not photo_bytes:
            _set_last_telegram_chat_id(chat_id)
            _send_telegram_text(chat_id, "Couldn't download the photo, please try again.")
            return
        # Infer media type from common Telegram formats; default to jpeg
        media_type = "image/jpeg"
        content_blocks = []
        if caption:
            content_blocks.append({"type": "text", "text": caption})
        else:
            content_blocks.append({"type": "text", "text": "User sent an image."})
        b64 = base64.b64encode(photo_bytes).decode("ascii")
        content_blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{b64}"},
        })
        _set_last_telegram_chat_id(chat_id)
        process_telegram_message(chat_id, content_blocks)
        return

    # Text only
    if not text:
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
