"""Shared orchestrator invocation: invoke graph and return result plus last AI reply text."""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage

from src.graph.orchestrator import build_orchestrator


def _extract_last_ai_text(messages: list) -> str:
    """Extract text from the last AIMessage (text blocks only). Returns empty string if none."""
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


def invoke_orchestrator(messages: list[BaseMessage]) -> tuple[dict, str]:
    """
    Invoke the orchestrator with the given messages.
    Returns (result, last_ai_text) where result is the full orchestrator result dict
    and last_ai_text is the last AI reply as a single string (text only).
    """
    orchestrator = build_orchestrator()
    result = orchestrator.invoke({"messages": messages, "route": ""})
    last_ai_text = _extract_last_ai_text(result.get("messages", []))
    return result, last_ai_text
