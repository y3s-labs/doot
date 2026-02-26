"""Save agent learnings (skills, failures, working memory) after a run."""

from __future__ import annotations

from datetime import datetime

from src.memory.service import AgentMemoryService


def save_agent_memory(
    service: AgentMemoryService,
    agent_type: str,
    task_id: str,
    result: dict,
) -> None:
    """
    Persist skills_learned, failures, and working_memory from an agent result.
    result should contain optional keys: skills_learned, failures, working_memory, task_description.
    """
    # Save skills
    for skill in result.get("skills_learned", []):
        title = skill.get("title", "Untitled skill")
        content = skill.get("content", "")
        skill_content = f"""# Skill: {title}
Date: {datetime.now().strftime('%Y-%m-%d')}
Task: {result.get('task_description', '')}

## What I Learned
{content}

## Applies To
{skill.get('applies_to', 'General')}
"""
        service.save_skill(agent_type, title, skill_content)

    # Save failures
    for failure in result.get("failures", []):
        title = failure.get("title", "Untitled failure")
        content = f"""# Failure Pattern: {title}
Date: {datetime.now().strftime('%Y-%m-%d')}
Site: {failure.get('site', 'Unknown')}

## What Happened
{failure.get('what_happened', '')}

## How To Avoid
{failure.get('how_to_avoid', '')}
"""
        service.save_failure(agent_type, title, content)

    # Update working memory
    if result.get("working_memory"):
        service.update_working_memory(task_id, agent_type, result["working_memory"])
