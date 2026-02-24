"""LangChain tools that wrap the Google Calendar API client."""

from __future__ import annotations

from langchain_core.tools import tool

from src.agents.calendar.client import (
    delete_event,
    event_to_summary,
    get_event,
    insert_event,
    list_events,
)


@tool
def calendar_list_events(
    calendar_id: str = "primary",
    max_results: int = 10,
    time_min: str | None = None,
    time_max: str | None = None,
) -> str:
    """List upcoming events on a calendar.
    calendar_id: use 'primary' for the user's main calendar.
    time_min/time_max: optional RFC3339 datetime strings (e.g. 2025-02-23T00:00:00Z) to filter the range."""
    items, _ = list_events(
        calendar_id=calendar_id,
        max_results=max_results,
        time_min=time_min,
        time_max=time_max,
    )
    if not items:
        return "No events found in the given range."
    lines = []
    for ev in items:
        s = event_to_summary(ev)
        loc = f" @ {s['location']}" if s.get("location") else ""
        lines.append(
            f"• id={s['id']} {s['summary']}{loc}\n  {s['start']} – {s['end']}"
        )
    return "\n\n".join(lines)


@tool
def calendar_get_event(event_id: str, calendar_id: str = "primary") -> str:
    """Get full details of a single calendar event by its ID.
    Use the id from calendar_list_events (e.g. a long string like 'abc123...')."""
    event_id = event_id.strip()
    ev = get_event(calendar_id, event_id)
    s = event_to_summary(ev)
    lines = [
        f"Summary: {s['summary']}",
        f"Start: {s['start']}",
        f"End: {s['end']}",
    ]
    if s.get("location"):
        lines.append(f"Location: {s['location']}")
    if ev.get("description"):
        lines.append(f"Description: {ev['description']}")
    if s.get("htmlLink"):
        lines.append(f"Link: {s['htmlLink']}")
    return "\n".join(lines)


@tool
def calendar_create_event(
    summary: str,
    start_datetime: str,
    end_datetime: str,
    calendar_id: str = "primary",
    description: str | None = None,
    location: str | None = None,
) -> str:
    """Create a new calendar event.
    summary: title of the event.
    start_datetime and end_datetime: RFC3339 format (e.g. 2025-02-24T14:00:00Z or 2025-02-24T14:00:00-08:00).
    Optionally provide description and location."""
    created = insert_event(
        calendar_id,
        summary=summary,
        start={"dateTime": start_datetime},
        end={"dateTime": end_datetime},
        description=description,
        location=location,
    )
    s = event_to_summary(created)
    return f"Created event: {s['summary']} ({s['start']} – {s['end']}). id={s['id']}"


@tool
def calendar_delete_event(event_id: str, calendar_id: str = "primary") -> str:
    """Delete a calendar event by its ID. Use the id from calendar_list_events."""
    event_id = event_id.strip()
    delete_event(calendar_id, event_id)
    return f"Deleted event id={event_id}."


ALL_TOOLS = [
    calendar_list_events,
    calendar_get_event,
    calendar_create_event,
    calendar_delete_event,
]
