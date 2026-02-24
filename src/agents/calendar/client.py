"""Google Calendar API client using shared OAuth credentials."""

from __future__ import annotations

from datetime import datetime

from googleapiclient.discovery import build

from src.agents.gmail.auth import get_credentials


def get_calendar_service():
    """Build Calendar API v3 service with current credentials."""
    creds = get_credentials()
    return build("calendar", "v3", credentials=creds)


def list_events(
    *,
    calendar_id: str = "primary",
    time_min: datetime | str | None = None,
    time_max: datetime | str | None = None,
    max_results: int = 10,
    single_events: bool = True,
    order_by: str = "startTime",
):
    """List events on the given calendar. Returns (items, next_page_token)."""
    service = get_calendar_service()
    params = {
        "calendarId": calendar_id,
        "maxResults": max_results,
        "singleEvents": single_events,
        "orderBy": order_by,
    }
    if time_min is not None:
        params["timeMin"] = (
            time_min.isoformat() + "Z" if isinstance(time_min, datetime) else time_min
        )
    if time_max is not None:
        params["timeMax"] = (
            time_max.isoformat() + "Z" if isinstance(time_max, datetime) else time_max
        )
    response = service.events().list(**params).execute()
    return response.get("items", []), response.get("nextPageToken")


def get_event(calendar_id: str, event_id: str):
    """Get a single event by ID."""
    service = get_calendar_service()
    return service.events().get(calendarId=calendar_id, eventId=event_id).execute()


def insert_event(
    calendar_id: str,
    *,
    summary: str,
    start: dict,
    end: dict,
    description: str | None = None,
    location: str | None = None,
):
    """Create a new event. start/end are dicts with 'dateTime' (RFC3339) and optional 'timeZone', or 'date' (YYYY-MM-DD) for all-day."""
    service = get_calendar_service()
    body = {"summary": summary, "start": start, "end": end}
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    return service.events().insert(calendarId=calendar_id, body=body).execute()


def delete_event(calendar_id: str, event_id: str):
    """Delete an event."""
    service = get_calendar_service()
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()


def event_to_summary(event: dict) -> dict:
    """Extract id, summary, start, end, location, htmlLink from a Calendar event."""
    start = event.get("start", {}) or {}
    end = event.get("end", {}) or {}
    start_str = start.get("dateTime") or start.get("date") or "?"
    end_str = end.get("dateTime") or end.get("date") or "?"
    return {
        "id": event.get("id"),
        "summary": event.get("summary", "(No title)"),
        "start": start_str,
        "end": end_str,
        "location": event.get("location"),
        "htmlLink": event.get("htmlLink"),
    }
