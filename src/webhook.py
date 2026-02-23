"""Webhook server for Gmail Pub/Sub push notifications."""

import base64
import json
import logging
import os

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("doot.webhook")

app = FastAPI(title="Doot webhook", version="0.1.0")


def on_gmail_push(payload: dict) -> None:
    """
    Trigger the orchestrator (which routes to Gmail agent or others): summarize the new email and suggest actions.
    Flow: Gmail Pub/Sub webhook → Orchestrator → Gmail Agent (or other agents if needed).
    payload: decoded Gmail notification {"emailAddress": "...", "historyId": "..."}
    """
    from langchain_core.messages import AIMessage, HumanMessage

    from src.graph.orchestrator import build_orchestrator

    prompt = (
        "A new email just arrived. Get the most recent email from my inbox, "
        "summarize it clearly, and suggest specific actions I can take "
        "(e.g. reply, archive, add to calendar, follow up later)."
    )
    try:
        orchestrator = build_orchestrator()
        result = orchestrator.invoke({"messages": [HumanMessage(content=prompt)], "route": ""})
        route = result.get("route", "?")
        log.info("Orchestrator route on Gmail push: %s", route)
        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage) and msg.content:
                content = msg.content
                if isinstance(content, list):
                    text_blocks = [
                        block.get("text") for block in content
                        if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
                    ]
                    content = "\n".join(text_blocks) if text_blocks else ""
                if content:
                    log.info("Orchestrator reply: %s", content)
                    break
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


def run_webhook_server(host: str = "0.0.0.0", port: int | None = None) -> None:
    """Run the webhook server (for use by CLI)."""
    import uvicorn

    port = port or int(os.getenv("PORT", "8000"))
    log.info("Webhook server starting on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port)
