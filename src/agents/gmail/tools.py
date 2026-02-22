"""LangChain tools that wrap the Gmail API client."""

from __future__ import annotations

from langchain_core.tools import tool

from src.agents.gmail.client import get_message, list_messages, message_to_summary


@tool
def gmail_list_inbox(max_results: int = 10) -> str:
    """List the most recent emails in the inbox. Returns subject, from, date, and snippet for each."""
    msgs, _ = list_messages(max_results=max_results, label_ids=["INBOX"])
    if not msgs:
        return "No messages found in inbox."
    summaries = []
    for stub in msgs:
        msg = get_message("me", stub["id"], format="metadata")
        summaries.append(message_to_summary(msg))
    lines = []
    for s in summaries:
        lines.append(f"• [{s['date']}] From: {s['from']}\n  Subject: {s['subject']}\n  {s['snippet'][:120]}")
    return "\n\n".join(lines)


@tool
def gmail_search(query: str, max_results: int = 10) -> str:
    """Search Gmail with a query string (same syntax as the Gmail search box). Returns matching emails."""
    msgs, _ = list_messages(max_results=max_results, q=query)
    if not msgs:
        return f"No messages found for query: {query}"
    summaries = []
    for stub in msgs:
        msg = get_message("me", stub["id"], format="metadata")
        summaries.append(message_to_summary(msg))
    lines = []
    for s in summaries:
        lines.append(f"• [{s['date']}] From: {s['from']}\n  Subject: {s['subject']}\n  {s['snippet'][:120]}")
    return "\n\n".join(lines)


@tool
def gmail_get_email(message_id: str) -> str:
    """Get the full content of a specific email by its message ID."""
    msg = get_message("me", message_id, format="full")
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    parts_text = _extract_text(msg.get("payload", {}))
    return (
        f"From: {headers.get('from', '?')}\n"
        f"To: {headers.get('to', '?')}\n"
        f"Date: {headers.get('date', '?')}\n"
        f"Subject: {headers.get('subject', '?')}\n\n"
        f"{parts_text or msg.get('snippet', '')}"
    )


def _extract_text(payload: dict) -> str:
    """Recursively extract text/plain from a Gmail message payload."""
    import base64

    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    parts = payload.get("parts", [])
    for part in parts:
        text = _extract_text(part)
        if text:
            return text
    return ""


ALL_TOOLS = [gmail_list_inbox, gmail_search, gmail_get_email]
