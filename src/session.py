"""Global chat session: load/save for CLI and Telegram (single shared conversation)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("doot.session")


# Sliding window: only this many messages are sent to the model each turn; full history is still persisted.
SESSION_SLIDING_WINDOW = 20


def session_path() -> Path:
    """Path for persisted chat session (JSON). Defaults to project .doot/ so it survives container rebuilds."""
    explicit = os.getenv("DOOT_SESSION_PATH")
    if explicit:
        return Path(explicit).expanduser()
    return Path.cwd() / ".doot" / "chat_session.json"


def trim_messages_to_window(messages: list, max_messages: int | None = None) -> list:
    """Return the last max_messages (default SESSION_SLIDING_WINDOW). Full history stays in caller for saving."""
    cap = max_messages if max_messages is not None else SESSION_SLIDING_WINDOW
    if len(messages) <= cap:
        return list(messages)
    return list(messages[-cap:])


def load_session() -> list:
    """Load session messages from file. Returns list of HumanMessage/AIMessage; empty list if missing or invalid."""
    from langchain_core.messages import AIMessage, HumanMessage

    path = session_path()
    if not path.exists():
        return []
    try:
        raw = path.read_text()
        data = json.loads(raw) if raw.strip() else []
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Could not load session from %s: %s", path, e)
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if content is None:
            content = ""
        if role == "human":
            out.append(HumanMessage(content=content))
        elif role == "ai":
            out.append(AIMessage(content=content))
    return out


def save_session(messages: list) -> None:
    """Persist message list to session file (JSON array of {role, content})."""
    from langchain_core.messages import AIMessage, HumanMessage

    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            raw = msg.content
            if isinstance(raw, str):
                content = raw
            else:
                # Multimodal (e.g. text + image): persist text-only plus image count
                parts = []
                image_count = 0
                if isinstance(raw, list):
                    for block in raw:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                parts.append(block.get("text") or "")
                            elif block.get("type") == "image_url":
                                image_count += 1
                content = "\n".join(p for p in parts if p).strip()
                if image_count:
                    content = (content + " " if content else "") + f"[{image_count} image(s)]"
                content = content or "(no text)"
            rows.append({"role": "human", "content": content})
        elif isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, list):
                content = "\n".join(
                    block.get("text", str(block)) if isinstance(block, dict) else str(block) for block in content
                )
            else:
                content = content if isinstance(content, str) else str(content)
            rows.append({"role": "ai", "content": content})
    path.write_text(json.dumps(rows, indent=2))
