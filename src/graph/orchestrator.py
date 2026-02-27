"""Orchestrator: plans and runs multi-step tasks by calling agents (gmail, calendar, websearch, direct) with different queries until done."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import create_react_agent

from src.agents.calendar.agent import create_calendar_agent
from src.agents.gmail.agent import create_gmail_agent
from src.agents.websearch.agent import create_websearch_agent
from src.memory import AgentMemoryService, save_agent_memory
from src.memory.claw_store import load_memory_for_context
from src.memory.claw_tools import CLAW_MEMORY_TOOLS

log = logging.getLogger("doot.orchestrator")


def _extract_last_ai_text(messages: list) -> str:
    """Extract text from the last AIMessage. Returns empty string if none."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            content = msg.content
            if isinstance(content, list):
                text_blocks = [
                    block.get("text")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
                ]
                return "\n".join(text_blocks) if text_blocks else ""
            return content if isinstance(content, str) else str(content)
    return ""


def _agent_messages(query: str) -> list[BaseMessage]:
    """Build message list with global context + single user query for agent invocation."""
    return [_global_context_message(), HumanMessage(content=query)]

# Shared per-agent memory service (identity, skills, failures, working)
_memory_service = AgentMemoryService()
# Task ID for working memory; no explicit tasks in chat flow, so one session-scoped working memory.
# Call memory_service.clear_working_memory(_MEMORY_TASK_ID) when a task fully completes (e.g. from CLI).
_MEMORY_TASK_ID = "session"

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
    """System message with agent_context.md + OpenClaw-style memory (MEMORY.md + today/yesterday)."""
    context = _load_agent_context()
    claw_memory = load_memory_for_context()
    parts = [context] if context else []
    parts.append(claw_memory)
    return SystemMessage(content="\n\n".join(parts))


def _anthropic_api_key() -> str | None:
    """ANTHROPIC_API_KEY from env, stripped so .env newlines/spaces don't break auth."""
    raw = os.getenv("ANTHROPIC_API_KEY")
    return (raw.strip() if raw else None) or None


class OrchestratorState(TypedDict):
    messages: list[BaseMessage]
    route: str


def inject_global_context(state: OrchestratorState) -> OrchestratorState:
    """Prepend global agent context (agent_context.md + OpenClaw memory) to every conversation."""
    messages = list(state["messages"])
    # Always prepend so that OpenClaw memory (MEMORY.md + today/yesterday) is fresh each turn
    return {**state, "messages": [_global_context_message()] + messages}


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


def _build_direct_agent():
    """ReAct agent for direct replies with memory tools (memory_get, memory_search, memory_append)."""
    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        anthropic_api_key=_anthropic_api_key(),
        max_tokens=4096,
    )
    return create_react_agent(
        llm,
        tools=CLAW_MEMORY_TOOLS,
        prompt=_direct_system_message(),
    )


# --- Agent tools for multi-step ReAct orchestrator (plan then call agents with different queries) ---

@tool
def websearch(query: str) -> str:
    """Search the web for current information. Use for weather, news, police activity, or any up-to-date facts. Pass a clear search query (e.g. 'current weather Providence RI' or 'recent police activity Providence RI')."""
    agent = create_websearch_agent()
    messages = _agent_messages(query)
    result = agent.invoke({"messages": messages})
    return _extract_last_ai_text(result.get("messages", []))


@tool
def gmail(instruction: str) -> str:
    """Use Gmail: list inbox, search emails, read an email, or move to trash. Pass a clear instruction (e.g. 'list my last 5 emails' or 'search for emails from X')."""
    agent = create_gmail_agent(task_id=_MEMORY_TASK_ID, memory_service=_memory_service)
    messages = _agent_messages(instruction)
    result = agent.invoke({"messages": messages})
    save_agent_memory(_memory_service, "gmail", _MEMORY_TASK_ID, result)
    return _extract_last_ai_text(result.get("messages", []))


@tool
def calendar(instruction: str) -> str:
    """Use Google Calendar: list upcoming events, view details, create or delete events. Pass a clear instruction (e.g. 'list events in the next 2 hours')."""
    agent = create_calendar_agent(task_id=_MEMORY_TASK_ID, memory_service=_memory_service)
    messages = _agent_messages(instruction)
    result = agent.invoke({"messages": messages})
    save_agent_memory(_memory_service, "calendar", _MEMORY_TASK_ID, result)
    return _extract_last_ai_text(result.get("messages", []))


@tool
def direct(instruction: str) -> str:
    """Answer using memory (MEMORY.md and daily logs). Use for facts the user has stored, or to read/append memory. Pass a short instruction or question."""
    agent = _build_direct_agent()
    messages = _agent_messages(instruction)
    result = agent.invoke({"messages": messages})
    return _extract_last_ai_text(result.get("messages", []))


ORCHESTRATOR_AGENT_TOOLS = [websearch, gmail, calendar, direct]

REACT_SYSTEM = SystemMessage(
    content=(
        "You are an assistant that completes tasks by using tools. You have: websearch(query), gmail(instruction), calendar(instruction), direct(instruction). "
        "Use them as needed. For multi-step tasks (e.g. compile a report on weather and police activity), call websearch multiple times with different search queries, "
        "then synthesize the results into a final answer. When you have enough information, provide the complete response to the user. Be concise and accurate."
    )
)


def _build_react_orchestrator_agent():
    """ReAct agent that can call gmail, calendar, websearch, direct multiple times until task is complete."""
    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        anthropic_api_key=_anthropic_api_key(),
        max_tokens=4096,
    )
    return create_react_agent(
        llm,
        tools=ORCHESTRATOR_AGENT_TOOLS,
        prompt=REACT_SYSTEM,
    )


def react_orchestrator_node(state: OrchestratorState) -> OrchestratorState:
    """Run the ReAct orchestrator (plan and multi-step agent calls) on the current messages."""
    log.info("ReAct orchestrator: running (multi-step)...")
    agent = _build_react_orchestrator_agent()
    result = agent.invoke({"messages": state["messages"]})
    log.info("ReAct orchestrator: done, %d messages in result", len(result["messages"]))
    return {**state, "messages": result["messages"]}


def build_orchestrator() -> StateGraph:
    """Build and compile the orchestrator graph. Uses ReAct agent with agent-tools for planning and multi-step execution (multiple websearch/gmail/calendar/direct calls until task complete)."""
    graph = StateGraph(OrchestratorState)

    graph.add_node("inject_context", inject_global_context)
    graph.add_node("react_orchestrator", react_orchestrator_node)

    graph.set_entry_point("inject_context")
    graph.add_edge("inject_context", "react_orchestrator")
    graph.add_edge("react_orchestrator", END)

    return graph.compile()
