"""Orchestrator: routes user messages to the right agent."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from src.agents.calendar.agent import create_calendar_agent
from src.agents.gmail.agent import create_gmail_agent
from src.agents.websearch.agent import create_websearch_agent

log = logging.getLogger("doot.orchestrator")

# Path to agent_context/ (not committed; see .gitignore)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
AGENT_CONTEXT_PATH = _PROJECT_ROOT / "agent_context" / "agent_context.md"


def _load_agent_context() -> str:
    """Load global agent context from agent_context.md. Content after '---' is used as the context."""
    if not AGENT_CONTEXT_PATH.exists():
        log.warning("agent_context.md not found at %s; using empty context", AGENT_CONTEXT_PATH)
        return ""
    raw = AGENT_CONTEXT_PATH.read_text(encoding="utf-8").strip()
    if "---" in raw:
        _, _, body = raw.partition("---")
        return body.strip()
    return raw


def _global_context_message() -> SystemMessage:
    """System message with current agent context (loaded from file)."""
    return SystemMessage(content=_load_agent_context())


def _anthropic_api_key() -> str | None:
    """ANTHROPIC_API_KEY from env, stripped so .env newlines/spaces don't break auth."""
    raw = os.getenv("ANTHROPIC_API_KEY")
    return (raw.strip() if raw else None) or None


ROUTER_SYSTEM = SystemMessage(
    content=(
        "You are a routing assistant. Given the user's message, decide which agent should handle it.\n"
        "Available agents:\n"
        "  - gmail: anything about emails, inbox, messages, mail\n"
        "  - calendar: anything about calendar, events, meetings, schedule, appointments\n"
        "  - websearch: look up current info, search the web, recent events, facts, \"what is\", \"who won\", news\n"
        "  - none: if you can answer directly without any agent\n\n"
        "Respond with ONLY the agent name (gmail, calendar, websearch, or none) and nothing else."
    )
)


class OrchestratorState(TypedDict):
    messages: list[BaseMessage]
    route: str


def _build_router_llm():
    return ChatAnthropic(
        model="claude-sonnet-4-20250514",
        anthropic_api_key=_anthropic_api_key(),
        max_tokens=50,
    )


def inject_global_context(state: OrchestratorState) -> OrchestratorState:
    """Prepend global agent context to every conversation (from agent_context.md)."""
    context = _load_agent_context()
    messages = list(state["messages"])
    if context and messages and isinstance(messages[0], SystemMessage) and messages[0].content == context:
        return state
    if not context:
        return state
    return {**state, "messages": [_global_context_message()] + messages}


def route_node(state: OrchestratorState) -> OrchestratorState:
    """Classify the user's message and pick an agent."""
    log.info("Router: classifying message...")
    llm = _build_router_llm()
    last_user_msg = None
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            last_user_msg = msg
            break
    if not last_user_msg:
        log.info("Router: no user message found, defaulting to 'none'")
        return {**state, "route": "none"}
    response = llm.invoke([ROUTER_SYSTEM, last_user_msg])
    raw_route = response.content.strip().lower() if isinstance(response.content, str) else str(response.content)
    if "gmail" in raw_route:
        route = "gmail"
    elif "calendar" in raw_route:
        route = "calendar"
    elif "websearch" in raw_route or "web_search" in raw_route:
        route = "websearch"
    else:
        route = "none"
    log.info("Router: raw=%r → route=%s", raw_route, route)
    return {**state, "route": route}


def gmail_node(state: OrchestratorState) -> OrchestratorState:
    """Run the Gmail agent on the user's messages."""
    log.info("Gmail agent: running...")
    agent = create_gmail_agent()
    result = agent.invoke({"messages": state["messages"]})
    log.info("Gmail agent: done, %d messages in result", len(result["messages"]))
    return {**state, "messages": result["messages"]}


def calendar_node(state: OrchestratorState) -> OrchestratorState:
    """Run the Calendar agent on the user's messages."""
    log.info("Calendar agent: running...")
    agent = create_calendar_agent()
    result = agent.invoke({"messages": state["messages"]})
    log.info("Calendar agent: done, %d messages in result", len(result["messages"]))
    return {**state, "messages": result["messages"]}


def websearch_node(state: OrchestratorState) -> OrchestratorState:
    """Run the Web Search (Gemini grounding) agent on the user's messages."""
    log.info("Web search agent: running...")
    agent = create_websearch_agent()
    result = agent.invoke({"messages": state["messages"]})
    log.info("Web search agent: done, %d messages in result", len(result["messages"]))
    return {**state, "messages": result["messages"]}


def _direct_system_message() -> SystemMessage:
    """System message with current date/time so the model can answer 'what is today?' etc."""
    now = datetime.now(timezone.utc)
    today_iso = now.strftime("%Y-%m-%d")
    today_readable = now.strftime("%A, %B %d, %Y")
    time_utc = now.strftime("%H:%M UTC")
    return SystemMessage(
        content=(
            f"Current date and time: {today_readable}. "
            f"Date in ISO form: {today_iso}. Time: {time_utc}. "
            "Use this when the user asks about today, the current date, or the current time."
        )
    )


def direct_node(state: OrchestratorState) -> OrchestratorState:
    """Answer directly without an agent."""
    log.info("Direct node: answering without agent...")
    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        anthropic_api_key=_anthropic_api_key(),
        max_tokens=4096,
    )
    messages = [_direct_system_message()] + list(state["messages"])
    response = llm.invoke(messages)
    return {**state, "messages": state["messages"] + [response]}


def pick_agent(state: OrchestratorState) -> str:
    """Conditional edge: route to the chosen agent node."""
    return state["route"]


def build_orchestrator() -> StateGraph:
    """Build and compile the orchestrator graph."""
    graph = StateGraph(OrchestratorState)

    graph.add_node("inject_context", inject_global_context)
    graph.add_node("router", route_node)
    graph.add_node("gmail", gmail_node)
    graph.add_node("calendar", calendar_node)
    graph.add_node("websearch", websearch_node)
    graph.add_node("direct", direct_node)

    graph.set_entry_point("inject_context")
    graph.add_edge("inject_context", "router")
    graph.add_conditional_edges(
        "router",
        pick_agent,
        {"gmail": "gmail", "calendar": "calendar", "websearch": "websearch", "none": "direct"},
    )
    graph.add_edge("gmail", END)
    graph.add_edge("calendar", END)
    graph.add_edge("websearch", END)
    graph.add_edge("direct", END)

    return graph.compile()
