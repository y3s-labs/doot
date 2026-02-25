"""Google Calendar agent: an LLM with Calendar tools bound to it."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from src.agents.calendar.tools import ALL_TOOLS


def _build_system_prompt() -> SystemMessage:
    """Build system prompt with current date/time so 'today' is always correct."""
    now = datetime.now(timezone.utc)
    # e.g. 2026-02-25, Wednesday February 25, 2026
    today_iso = now.strftime("%Y-%m-%d")
    today_readable = now.strftime("%A, %B %d, %Y")
    return SystemMessage(
        content=(
            "You are a helpful Google Calendar assistant. You can list upcoming events, "
            "view event details, create new events, and delete events. Use 'primary' as the "
            "calendar unless the user asks for a different one. For create_event, use RFC3339 "
            "datetimes (e.g. 2025-02-24T14:00:00Z or 2025-02-24T14:00:00-08:00). "
            "Be concise and confirm actions clearly.\n\n"
            "IMPORTANT: Use this as the current date when the user says 'today' or 'now': "
            f"{today_iso} ({today_readable}). "
            "Always use this date for relative times like 'today at 4pm EST'.\n\n"
            f"The user's email is {os.getenv('USER_EMAIL', 'unknown')}."
        )
    )


def create_calendar_agent():
    """Create a ReAct agent with Google Calendar tools."""
    raw = (os.getenv("ANTHROPIC_API_KEY") or "").strip() or None
    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        anthropic_api_key=raw,
        max_tokens=4096,
    )
    return create_react_agent(
        llm,
        tools=ALL_TOOLS,
        prompt=_build_system_prompt(),
    )
