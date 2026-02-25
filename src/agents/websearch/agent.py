"""Web search agent: Gemini with Google Search grounding, invoked like other agents."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.websearch.client import (
    format_response_with_sources,
    search_grounded_response,
)


def create_websearch_agent():
    """
    Return an object that matches the orchestrator's agent interface:
    .invoke({"messages": [...]}) -> {"messages": [...]}
    """
    class _WebSearchAgent:
        def invoke(self, state: dict) -> dict:
            messages = state.get("messages") or []
            last_user = None
            for msg in reversed(messages):
                if isinstance(msg, HumanMessage):
                    last_user = msg
                    break
            if not last_user or not getattr(last_user, "content", "").strip():
                return {"messages": messages}
            query = (
                last_user.content.strip()
                if isinstance(last_user.content, str)
                else str(last_user.content)
            )
            try:
                text, sources = search_grounded_response(query, include_sources=True)
                reply = format_response_with_sources(text, sources)
            except Exception as e:
                err = str(e)
                if "API_KEY_INVALID" in err or "API key not valid" in err or "INVALID_ARGUMENT" in err:
                    reply = (
                        "Web search failed: the Gemini API key was rejected. "
                        "Use a key from Google AI Studio (https://aistudio.google.com/apikey), "
                        "not the OAuth client ID/secret from Cloud Console. Set it as GEMINI_API_KEY in .env."
                    )
                else:
                    reply = f"Web search failed: {e}. Check that GEMINI_API_KEY (or GOOGLE_API_KEY) is set and valid."
            return {"messages": messages + [AIMessage(content=reply)]}

    return _WebSearchAgent()
