"""Google Gemini with Google Search grounding: real-time web-grounded answers."""

from __future__ import annotations

import os
from typing import Any

from google import genai
from google.genai import types


def _get_client() -> genai.Client:
    """Build Gemini client; uses GEMINI_API_KEY or GOOGLE_API_KEY from env."""
    raw = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    api_key = raw.strip().strip('"').strip("'")
    if not api_key:
        raise ValueError(
            "Set GEMINI_API_KEY or GOOGLE_API_KEY for the web search (Gemini) agent. "
            "Get a key from https://aistudio.google.com/apikey (not the OAuth client secret from Cloud Console)."
        )
    return genai.Client(api_key=api_key)


def _looks_like_meta_search_request(text: str) -> bool:
    """True if the user is asking to search or why we can't search, without a concrete query."""
    t = text.lower().strip()
    if not t or len(t) < 20:
        return True
    meta_phrases = (
        "search the internet",
        "search the web",
        "why can't you search",
        "why can you not search",
        "can you search",
        "search for me",
    )
    return any(p in t for p in meta_phrases) and " for " not in t and " about " not in t


# Instruct the model to use Google Search so it doesn't reply "I can't browse the web".
WEBSEARCH_SYSTEM_INSTRUCTION = (
    "You have Google Search grounding enabled. You MUST use it to answer. "
    "When the user asks to search the internet, wants current information, or asks why you can't search, "
    "perform a web search and return a grounded answer with sources. "
    "Do not say you cannot browse the web or lack real-time access—you do have it via Google Search."
)


def search_grounded_response(
    query: str,
    *,
    model: str = "gemini-flash-lite-latest",
    include_sources: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Ask Gemini with Google Search grounding. Returns (answer_text, sources).
    sources is a list of {"uri": str, "title": str} from grounding_chunks.
    """
    client = _get_client()
    tools = [types.Tool(google_search=types.GoogleSearch())]
    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        tools=tools,
        max_output_tokens=8192,
        system_instruction=WEBSEARCH_SYSTEM_INSTRUCTION,
    )
    # If the user only asked to "search" without a concrete query, give the model a clear search task
    content = query.strip()
    if not content or _looks_like_meta_search_request(content):
        content = (
            "Search the web for: what this assistant can do and current capabilities of AI assistants with web search. "
            "Then answer the user based on the search results. User said: " + (content or "search the internet")
        )
    response = client.models.generate_content(
        model=model,
        contents=content,
        config=config,
    )
    text = (response.text or "").strip()
    sources: list[dict[str, Any]] = []

    if include_sources and response.candidates:
        cand = response.candidates[0]
        meta = getattr(cand, "grounding_metadata", None)
        if meta:
            chunks = getattr(meta, "grounding_chunks", None) or []
            for ch in chunks:
                web = getattr(ch, "web", None)
                if web:
                    uri = getattr(web, "uri", None) or ""
                    title = getattr(web, "title", None) or ""
                    if uri:
                        sources.append({"uri": uri, "title": title})

    return text, sources


def format_response_with_sources(text: str, sources: list[dict[str, Any]]) -> str:
    """Append a 'Sources:' block with Markdown links so they render clickable (e.g. in Rich)."""
    if not sources:
        return text
    lines = [text]
    lines.append("")
    lines.append("Sources:")
    for i, s in enumerate(sources, 1):
        title = s.get("title") or "Link"
        uri = (s.get("uri") or "").strip()
        # Markdown link so terminals/IDEs can make it clickable; avoids long URL wrapping
        if uri:
            lines.append(f"  [{i}] [{title}]({uri})")
        else:
            lines.append(f"  [{i}] {title}")
    return "\n".join(lines)
