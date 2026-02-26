"""Agent memory service: read/write identity, skills, failures, working memory as Markdown files."""

from __future__ import annotations

import os
from pathlib import Path

# Base directory for all agent memory (project root or DOOT_AGENT_MEMORY_DIR)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _memory_base() -> Path:
    explicit = os.environ.get("DOOT_AGENT_MEMORY_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    return _PROJECT_ROOT / "agent_memory"


class AgentMemoryService:
    """Read/write per-agent identity, skills, failures, and working memory as Markdown."""

    def __init__(self, base: Path | None = None):
        self.base = base if base is not None else _memory_base()

    # --- Identity ---
    def get_identity(self, agent_type: str) -> str:
        path = self.base / agent_type / "identity.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    # --- Skills ---
    def get_skills(self, agent_type: str) -> str:
        skills_dir = self.base / agent_type / "skills"
        if not skills_dir.exists():
            return ""
        files = sorted(skills_dir.glob("*.md"))
        return "\n\n---\n\n".join(f.read_text(encoding="utf-8") for f in files)

    def get_failures(self, agent_type: str) -> str:
        failures_dir = self.base / agent_type / "failures"
        if not failures_dir.exists():
            return ""
        files = sorted(failures_dir.glob("*.md"))
        return "\n\n---\n\n".join(f.read_text(encoding="utf-8") for f in files)

    def save_skill(self, agent_type: str, title: str, content: str) -> Path:
        skills_dir = self.base / agent_type / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        existing = list(skills_dir.glob("*.md"))
        index = str(len(existing) + 1).zfill(3)
        slug = title.lower().replace(" ", "_").replace("/", "_")
        path = skills_dir / f"{index}_{slug}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def save_failure(self, agent_type: str, title: str, content: str) -> Path:
        failures_dir = self.base / agent_type / "failures"
        failures_dir.mkdir(parents=True, exist_ok=True)
        existing = list(failures_dir.glob("*.md"))
        index = str(len(existing) + 1).zfill(3)
        slug = title.lower().replace(" ", "_").replace("/", "_")
        path = failures_dir / f"{index}_{slug}.md"
        path.write_text(content, encoding="utf-8")
        return path

    # --- Working Memory ---
    def get_working_memory(self, task_id: str, agent_type: str) -> str:
        path = self.base / "working" / task_id / f"{agent_type}.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def update_working_memory(self, task_id: str, agent_type: str, content: str) -> Path:
        working_dir = self.base / "working" / task_id
        working_dir.mkdir(parents=True, exist_ok=True)
        path = working_dir / f"{agent_type}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def clear_working_memory(self, task_id: str) -> None:
        working_dir = self.base / "working" / task_id
        if working_dir.exists():
            for f in working_dir.glob("*.md"):
                f.unlink()
            try:
                working_dir.rmdir()
            except OSError:
                pass
