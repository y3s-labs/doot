"""Gmail API client using saved OAuth credentials."""

from __future__ import annotations

import base64
import os
from email.mime.text import MIMEText

from googleapiclient.discovery import build

from src.agents.gmail.auth import get_credentials


def get_gmail_service():
    """Build Gmail API v1 service with current credentials."""
    creds = get_credentials()
    return build("gmail", "v1", credentials=creds)


def watch(topic_name: str, user_id: str = "me", label_ids: list[str] | None = None):
    """
    Register Gmail push notifications to a Pub/Sub topic.
    Returns dict with historyId and expiration (epoch ms). Renew before expiration (e.g. daily).
    """
    service = get_gmail_service()
    body = {"topicName": topic_name}
    if label_ids is not None:
        body["labelIds"] = label_ids
        body["labelFilterBehavior"] = "INCLUDE"
    return service.users().watch(userId=user_id, body=body).execute()


def list_messages(
    *,
    user_id: str = "me",
    max_results: int = 10,
    q: str | None = None,
    label_ids: list[str] | None = None,
):
    """List message IDs (and threadIds) in the user's mailbox."""
    service = get_gmail_service()
    params = {"userId": user_id, "maxResults": max_results}
    if q:
        params["q"] = q
    if label_ids:
        params["labelIds"] = label_ids
    response = service.users().messages().list(**params).execute()
    return response.get("messages", []), response.get("nextPageToken")


def get_message(user_id: str, msg_id: str, *, format: str = "metadata"):
    """
    Get a single message. format: 'minimal' | 'full' | 'metadata' | 'raw'.
    With 'metadata', headers (Subject, From, Date) and snippet are included.
    """
    service = get_gmail_service()
    return (
        service.users()
        .messages()
        .get(userId=user_id, id=msg_id, format=format)
        .execute()
    )


def trash_message(user_id: str, msg_id: str) -> dict:
    """Move a message to Trash. Requires gmail.modify scope."""
    service = get_gmail_service()
    return service.users().messages().trash(userId=user_id, id=msg_id).execute()


def send_message(
    *,
    user_id: str = "me",
    to_email: str,
    subject: str,
    body: str,
    from_email: str | None = None,
) -> dict:
    """
    Send an email. Uses gmail.modify (or gmail.send) scope.
    from_email defaults to the authenticated user's address (from profile) or USER_EMAIL env.
    """
    service = get_gmail_service()
    if not from_email:
        from_email = (
            os.getenv("USER_EMAIL")
            or service.users().getProfile(userId=user_id).execute().get("emailAddress", "")
            or "noreply@localhost"
        )
    message = MIMEText(body, "plain", "utf-8")
    message["to"] = to_email
    message["from"] = from_email
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return service.users().messages().send(userId=user_id, body={"raw": raw}).execute()


def message_to_summary(msg: dict) -> dict:
    """Extract subject, from, date, snippet, id from a Gmail message (metadata format)."""
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    return {
        "id": msg["id"],
        "threadId": msg.get("threadId"),
        "snippet": msg.get("snippet", ""),
        "subject": headers.get("subject", ""),
        "from": headers.get("from", ""),
        "date": headers.get("date", ""),
    }
