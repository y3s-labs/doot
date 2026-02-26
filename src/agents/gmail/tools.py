"""LangChain tools that wrap the Gmail API client."""

from __future__ import annotations

from googleapiclient.errors import HttpError
from langchain_core.tools import tool

from src.agents.gmail.client import get_message, list_messages, message_to_summary, trash_message

# Message shown when Gmail returns 404 (message deleted, trashed, or ID from old conversation)
_MSG_NOT_FOUND = (
    "That message was not found. It may have been deleted or moved, or the ID may be from an earlier conversation. "
    "Use gmail_list_inbox or gmail_search now to get current message IDs, then retry."
)


@tool
def gmail_list_inbox(max_results: int = 10) -> str:
    """List the most recent emails in the inbox. Returns subject, from, date, and snippet for each."""
    msgs, _ = list_messages(max_results=max_results, label_ids=["INBOX"])
    if not msgs:
        return "No messages found in inbox."
    summaries = []
    for stub in msgs:
        try:
            msg = get_message("me", stub["id"], format="metadata")
            summaries.append(message_to_summary(msg))
        except HttpError as e:
            if e.resp.status == 404:
                continue  # skip deleted/moved message
            raise
    if not summaries:
        return "No messages found in inbox (or listed messages were deleted)."
    lines = []
    for s in summaries:
        lines.append(
            f"• id={s['id']} [{s['date']}] From: {s['from']}\n  Subject: {s['subject']}\n  {s['snippet'][:120]}"
        )
    return "\n\n".join(lines)


@tool
def gmail_search(query: str, max_results: int = 10) -> str:
    """Search Gmail with a query string (same syntax as the Gmail search box). Returns matching emails."""
    msgs, _ = list_messages(max_results=max_results, q=query)
    if not msgs:
        return f"No messages found for query: {query}"
    summaries = []
    for stub in msgs:
        try:
            msg = get_message("me", stub["id"], format="metadata")
            summaries.append(message_to_summary(msg))
        except HttpError as e:
            if e.resp.status == 404:
                continue
            raise
    if not summaries:
        return f"No messages found for query: {query} (or they were deleted)."
    lines = []
    for s in summaries:
        lines.append(
            f"• id={s['id']} [{s['date']}] From: {s['from']}\n  Subject: {s['subject']}\n  {s['snippet'][:120]}"
        )
    return "\n\n".join(lines)


@tool
def gmail_get_email(message_id: str) -> str:
    """Get the full content of a specific email by its Gmail message ID.
    The message_id must be the 'id' value from gmail_list_inbox or gmail_search (e.g. '18b2f3a1c4d5e6f7').
    Do not use an email address or any other value—only the id field from the list results."""
    message_id = message_id.strip()
    if "@" in message_id or " " in message_id:
        return (
            f"Invalid message_id: {message_id!r}. "
            "Use the exact 'id' value from gmail_list_inbox or gmail_search (e.g. id=18b2f3a1c4d5e6f7), not an email address."
        )
    try:
        msg = get_message("me", message_id, format="full")
    except HttpError as e:
        if e.resp.status == 404:
            return _MSG_NOT_FOUND
        return f"Gmail API error ({e.resp.status}): {e}"
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    parts_text = _extract_text(msg.get("payload", {}))
    return (
        f"From: {headers.get('from', '?')}\n"
        f"To: {headers.get('to', '?')}\n"
        f"Date: {headers.get('date', '?')}\n"
        f"Subject: {headers.get('subject', '?')}\n\n"
        f"{parts_text or msg.get('snippet', '')}"
    )


@tool
def gmail_trash_email(message_id: str) -> str:
    """Move an email to Trash (delete from inbox). The message_id must be the 'id' from gmail_list_inbox or gmail_search (e.g. '18b2f3a1c4d5e6f7').
    Use this when the user asks to delete, remove, or trash an email. Do not use an email address—only the id from list/search results."""
    message_id = message_id.strip()
    if "@" in message_id or " " in message_id:
        return (
            f"Invalid message_id: {message_id!r}. "
            "Use the exact 'id' value from gmail_list_inbox or gmail_search (e.g. id=18b2f3a1c4d5e6f7), not an email address."
        )
    try:
        trash_message("me", message_id)
        return f"Email {message_id} moved to Trash."
    except HttpError as e:
        if e.resp.status == 404:
            return _MSG_NOT_FOUND
        return f"Gmail API error ({e.resp.status}): {e}"
    except Exception as e:
        return f"Failed to trash email: {e}"


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


ALL_TOOLS = [gmail_list_inbox, gmail_search, gmail_get_email, gmail_trash_email]
