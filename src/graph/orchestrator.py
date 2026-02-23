"""Orchestrator: routes user messages to the right agent."""

from __future__ import annotations

import logging
import os
from typing import TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from src.agents.gmail.agent import create_gmail_agent

log = logging.getLogger("doot.orchestrator")


def _anthropic_api_key() -> str | None:
    """ANTHROPIC_API_KEY from env, stripped so .env newlines/spaces don't break auth."""
    raw = os.getenv("ANTHROPIC_API_KEY")
    return (raw.strip() if raw else None) or None


ROUTER_SYSTEM = SystemMessage(
    content=(
        "You are a routing assistant. Given the user's message, decide which agent should handle it.\n"
        "Available agents:\n"
        "  - gmail: anything about emails, inbox, messages, mail\n"
        "  - none: if you can answer directly without any agent\n\n"
        "Respond with ONLY the agent name (gmail or none) and nothing else."
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
    route = "gmail" if "gmail" in raw_route else "none"
    log.info("Router: raw=%r → route=%s", raw_route, route)
    return {**state, "route": route}


def gmail_node(state: OrchestratorState) -> OrchestratorState:
    """Run the Gmail agent on the user's messages."""
    log.info("Gmail agent: running...")
    agent = create_gmail_agent()
    result = agent.invoke({"messages": state["messages"]})
    log.info("Gmail agent: done, %d messages in result", len(result["messages"]))
    return {**state, "messages": result["messages"]}


def direct_node(state: OrchestratorState) -> OrchestratorState:
    """Answer directly without an agent."""
    log.info("Direct node: answering without agent...")
    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        anthropic_api_key=_anthropic_api_key(),
        max_tokens=4096,
    )
    response = llm.invoke(state["messages"])
    return {**state, "messages": state["messages"] + [response]}


def pick_agent(state: OrchestratorState) -> str:
    """Conditional edge: route to the chosen agent node."""
    return state["route"]


def build_orchestrator() -> StateGraph:
    """Build and compile the orchestrator graph."""
    graph = StateGraph(OrchestratorState)

    graph.add_node("router", route_node)
    graph.add_node("gmail", gmail_node)
    graph.add_node("direct", direct_node)

    graph.set_entry_point("router")
    graph.add_conditional_edges("router", pick_agent, {"gmail": "gmail", "none": "direct"})
    graph.add_edge("gmail", END)
    graph.add_edge("direct", END)

    return graph.compile()
