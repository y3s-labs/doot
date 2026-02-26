"""OpenClaw-style memory store: single workspace with MEMORY.md + memory/YYYY-MM-DD.md."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

log = __import__("logging").getLogger("doot.memory.claw_store")

# Allowed relative paths: MEMORY.md or memory/YYYY-MM-DD.md (date pattern)
_ALLOWED_PATH = re.compile(r"^(MEMORY\.md|memory/\d{4}-\d{2}-\d{2}\.md)$", re.IGNORECASE)


def _memory_root() -> Path:
    """Root directory for OpenClaw-style memory. Same location as session by default."""
    explicit = os.environ.get("DOOT_MEMORY_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (Path.cwd() / ".doot").resolve()


def _resolve(path: str) -> Path | None:
    """Resolve path relative to memory root. Returns None if path is not allowed."""
    path = path.strip().replace("\\", "/")
    if not _ALLOWED_PATH.match(path):
        return None
    root = _memory_root()
    full = (root / path).resolve()
    try:
        full.relative_to(root)
    except ValueError:
        return None
    return full


def get_memory_root() -> Path:
    """Return the memory workspace root (for CLI/tests)."""
    return _memory_root()


def read_memory_file(
    path: str,
    start_line: int | None = None,
    num_lines: int | None = None,
) -> dict:
    """
    Read a memory file. Path must be MEMORY.md or memory/YYYY-MM-DD.md.
    Returns {"text": content, "path": path} or {"text": "", "path": path} if missing.
    """
    resolved = _resolve(path)
    if not resolved:
        return {"text": "", "path": path}
    if not resolved.exists():
        return {"text": "", "path": path}
    try:
        content = resolved.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("Could not read %s: %s", path, e)
        return {"text": "", "path": path}
    lines = content.splitlines()
    if start_line is not None and num_lines is not None:
        # 1-based line range, clamp
        start = max(0, start_line - 1)
        end = min(len(lines), start + num_lines)
        lines = lines[start:end]
        content = "\n".join(lines)
    elif start_line is not None:
        start = max(0, start_line - 1)
        lines = lines[start:]
        content = "\n".join(lines)
    elif num_lines is not None:
        lines = lines[: num_lines]
        content = "\n".join(lines)
    return {"text": content, "path": path}


def append_memory_file(path: str, content: str) -> dict:
    """
    Append content to a memory file. Creates file if missing.
    Path must be MEMORY.md or memory/YYYY-MM-DD.md.
    Returns {"ok": True, "path": path} or {"ok": False, "error": "..."}.
    """
    resolved = _resolve(path)
    if not resolved:
        return {"ok": False, "error": f"Path not allowed: {path}"}
    resolved.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = resolved.read_text(encoding="utf-8") if resolved.exists() else ""
        new_content = existing.rstrip() + ("\n\n" if existing.strip() else "") + content.strip() + "\n"
        resolved.write_text(new_content, encoding="utf-8")
    except OSError as e:
        log.warning("Could not append to %s: %s", path, e)
        return {"ok": False, "error": str(e)}
    return {"ok": True, "path": path}


def list_memory_dates() -> list[str]:
    """Return sorted list of memory/YYYY-MM-DD.md dates (filenames without .md)."""
    root = _memory_root()
    memory_dir = root / "memory"
    if not memory_dir.exists():
        return []
    dates = []
    for f in memory_dir.iterdir():
        if f.suffix.lower() == ".md" and re.match(r"^\d{4}-\d{2}-\d{2}$", f.stem):
            dates.append(f.stem)
    return sorted(dates)


def get_today_yesterday_paths() -> tuple[str, str]:
    """Return (today_path, yesterday_path) for memory/YYYY-MM-DD.md."""
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    return f"memory/{today}.md", f"memory/{yesterday}.md"


def memory_keyword_search(query: str, max_results: int = 10) -> list[dict]:
    """
    Keyword search over MEMORY.md and memory/*.md.
    Returns list of {"path": str, "start_line": int, "end_line": int, "snippet": str}.
    """
    if not query or not query.strip():
        return []
    root = _memory_root()
    q = query.strip().lower()
    results = []

    def search_file(rel_path: str) -> None:
        resolved = root / rel_path
        if not resolved.exists():
            return
        try:
            content = resolved.read_text(encoding="utf-8")
        except OSError:
            return
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if q in line.lower():
                start = max(0, i - 2)
                end = min(len(lines), i + 3)
                snippet = "\n".join(lines[start:end])
                results.append({
                    "path": rel_path,
                    "start_line": start + 1,
                    "end_line": end,
                    "snippet": snippet,
                })
                if len(results) >= max_results:
                    return

    if (root / "MEMORY.md").exists():
        search_file("MEMORY.md")
    if len(results) >= max_results:
        return results[:max_results]
    memory_dir = root / "memory"
    if memory_dir.exists():
        for f in sorted(memory_dir.iterdir(), reverse=True):
            if f.suffix.lower() == ".md" and re.match(r"^\d{4}-\d{2}-\d{2}$", f.stem):
                search_file(f"memory/{f.name}")
                if len(results) >= max_results:
                    break
    return results[:max_results]


def load_memory_for_context() -> str:
    """
    Load MEMORY.md + today + yesterday into one string for injection at session start.
    Format: ## Long-term memory\\n{...}\\n\\n## Recent (today / yesterday)\\n{...}
    """
    root = _memory_root()
    parts = []

    # Long-term
    mem_path = root / "MEMORY.md"
    long_term = mem_path.read_text(encoding="utf-8").strip() if mem_path.exists() else ""
    parts.append("## Long-term memory\n" + (long_term or "(none)"))

    # Today / yesterday
    today_path, yesterday_path = get_today_yesterday_paths()
    today_content = read_memory_file(today_path)["text"].strip()
    yesterday_content = read_memory_file(yesterday_path)["text"].strip()
    recent = []
    today_label = Path(today_path).stem
    yesterday_label = Path(yesterday_path).stem
    if today_content:
        recent.append(f"### Today ({today_label})\n{today_content}")
    if yesterday_content:
        recent.append(f"### Yesterday ({yesterday_label})\n{yesterday_content}")
    parts.append("## Recent (today / yesterday)\n" + (("\n\n".join(recent)) if recent else "(nothing recorded yet)"))

    return "\n\n".join(parts)
