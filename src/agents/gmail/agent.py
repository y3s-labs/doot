"""Gmail agent: an LLM with Gmail tools bound to it."""

from __future__ import annotations

import os

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from src.agents.gmail.tools import ALL_TOOLS

SYSTEM_PROMPT = SystemMessage(
    content=(
        "You are a helpful Gmail assistant. You can list inbox messages, search emails, "
        "and read full email contents for the user. Be concise and clear in your responses. "
        "When listing emails, format them in a readable way.\n\n"
        "IMPORTANT WORKFLOW: To read an email, you MUST first call gmail_list_inbox or "
        "gmail_search to obtain the message ID (a hex string like '18b2f3a1c4d5e6f7'), "
        "then pass that ID to gmail_get_email. Never pass an email address as a message ID.\n\n"
        f"The user's email is {os.getenv('USER_EMAIL', 'unknown')}."
    )
)


def create_gmail_agent():
    """Create a ReAct agent with Gmail tools."""
    raw = (os.getenv("ANTHROPIC_API_KEY") or "").strip() or None
    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        anthropic_api_key=raw,
        max_tokens=4096,
    )
    return create_react_agent(
        llm,
        tools=ALL_TOOLS,
        prompt=SYSTEM_PROMPT,
    )
