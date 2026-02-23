"""Gmail API client using saved OAuth credentials."""

from __future__ import annotations

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
