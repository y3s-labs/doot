"""Global chat session: load/save for CLI and Telegram (single shared conversation)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("doot.session")


def session_path() -> Path:
    """Path for persisted chat session (JSON)."""
    base = os.getenv("DOOT_TOKENS_PATH", "~/.doot/tokens.json")
    return Path(base).expanduser().parent / "chat_session.json"


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
            rows.append({"role": "human", "content": msg.content if isinstance(msg.content, str) else str(msg.content)})
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
