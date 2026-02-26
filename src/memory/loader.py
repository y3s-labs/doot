"""Load combined agent memory (identity, skills, failures, working) for injection into context."""

from __future__ import annotations

from langchain_core.messages import SystemMessage

from src.memory.service import AgentMemoryService


def make_memory_modifier(
    agent_type: str,
    task_id: str = "session",
    service: AgentMemoryService | None = None,
):
    """
    Return a pre_model_hook callable that prepends agent memory to the LLM input.
    Use with create_react_agent(..., pre_model_hook=make_memory_modifier("gmail", task_id)).
    """
    if service is None:
        service = AgentMemoryService()

    def modifier(state: dict) -> dict:
        memory_context = load_agent_memory(service, agent_type, task_id)
        messages = list(state.get("messages") or [])
        llm_input = [SystemMessage(content=memory_context)] + messages
        return {"llm_input_messages": llm_input}

    return modifier


def load_agent_memory(
    service: AgentMemoryService,
    agent_type: str,
    task_id: str,
) -> str:
    """Build a single markdown block with identity, skills, failures, and working memory."""
    identity = service.get_identity(agent_type)
    skills = service.get_skills(agent_type)
    failures = service.get_failures(agent_type)
    working = service.get_working_memory(task_id, agent_type)

    return f"""
## IDENTITY & FACTS
{identity or "No identity file found."}

## SKILLS LEARNED FROM PAST TASKS
{skills or "No skills stored yet."}

## KNOWN FAILURE PATTERNS TO AVOID
{failures or "No failures recorded yet."}

## WHAT YOU'VE DONE SO FAR THIS TASK
{working or "Nothing yet — this is the start of the task."}
"""
