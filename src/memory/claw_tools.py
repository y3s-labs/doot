"""LangChain tools for OpenClaw-style memory: memory_get, memory_search, memory_append."""

from __future__ import annotations

from langchain_core.tools import tool

from src.memory.claw_store import (
    append_memory_file,
    memory_keyword_search,
    read_memory_file,
)


@tool
def memory_get(
    path: str,
    start_line: int | None = None,
    num_lines: int | None = None,
) -> str:
    """
    Read a memory file. Use path MEMORY.md for long-term memory, or memory/YYYY-MM-DD.md for a daily log (e.g. memory/2026-02-26.md).
    Optionally give start_line (1-based) and num_lines to read a range. Returns file content, or empty if the file does not exist yet.
    """
    out = read_memory_file(path, start_line=start_line, num_lines=num_lines)
    if not out["text"] and out["path"]:
        return f"(No content yet for {path})"
    return out["text"] or "(empty)"


@tool
def memory_search(query: str, max_results: int = 10) -> str:
    """
    Search memory by keyword over MEMORY.md and all daily logs. Returns matching snippets with file path and line numbers.
    Use this to find what was recorded about a topic, e.g. preferences, decisions, or past events.
    """
    results = memory_keyword_search(query, max_results=max_results)
    if not results:
        return f"No matches for: {query}"
    lines = []
    for r in results:
        lines.append(f"--- {r['path']} (lines {r['start_line']}-{r['end_line']}) ---\n{r['snippet']}")
    return "\n\n".join(lines)


@tool
def memory_append(path: str, content: str) -> str:
    """
    Append content to a memory file. Use MEMORY.md for long-term facts and preferences, or memory/YYYY-MM-DD.md for today's log (e.g. memory/2026-02-26.md).
    Creates the file if it does not exist. Only MEMORY.md and memory/YYYY-MM-DD.md paths are allowed.
    """
    out = append_memory_file(path, content)
    if out.get("ok"):
        return f"Appended to {path}."
    return f"Failed: {out.get('error', 'unknown')}"


# All tools for the direct agent
CLAW_MEMORY_TOOLS = [memory_get, memory_search, memory_append]
