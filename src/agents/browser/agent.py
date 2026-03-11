"""Browser agent: ReAct loop with Playwright tools, all in one thread (Playwright sync API is thread-bound)."""

from __future__ import annotations

import logging
import os

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage

from src.agents.browser.client import start_browser
from src.agents.browser.tools import make_browser_tools

log = logging.getLogger("doot.browser.agent")


def _log_tool_call(name: str, args: dict) -> None:
    """One-line progress: what the browser agent is doing."""
    if name == "browser_navigate":
        url = (args.get("url") or "").strip() or "(empty)"
        log.info("Browser: navigating to %s", url)
    elif name == "browser_snapshot":
        log.info("Browser: taking snapshot of page")
    elif name == "browser_click":
        sel = args.get("selector") or "(no selector)"
        log.info("Browser: clicking %s", sel[:80] + "..." if len(sel) > 80 else sel)
    elif name == "browser_fill":
        sel = args.get("selector") or "?"
        text = (args.get("text") or "")[:40]
        if len((args.get("text") or "")) > 40:
            text += "..."
        log.info("Browser: filling %s with %s", sel[:50], text)
    elif name == "browser_type":
        log.info("Browser: typing into %s", (args.get("selector") or "?")[:50])
    elif name in ("browser_scroll_down", "browser_scroll_up"):
        log.info("Browser: %s", name.replace("browser_", ""))
    else:
        log.info("Browser: calling %s", name)


def _log_tool_result(name: str, out: str | None) -> None:
    """One-line result for key actions (optional, avoid noise)."""
    if not out:
        return
    out_str = str(out).strip()
    if name == "browser_navigate" and out_str.startswith("Navigated"):
        log.info("Browser: %s", out_str[:100])
    elif name == "browser_snapshot":
        log.info("Browser: snapshot done (%d chars)", len(out_str))
    elif name == "browser_click" and "Clicked" in out_str:
        log.info("Browser: %s", out_str[:80])
    elif name == "browser_fill" and "Filled" in out_str:
        log.info("Browser: %s", out_str[:80])


BROWSER_SYSTEM_PROMPT = SystemMessage(
    content="""You are a browser automation assistant. You can navigate to URLs, read the page (snapshot), click links and buttons, fill forms, and scroll.

Workflow:
1. Use browser_navigate to go to a URL when the user asks to open a site.
2. Use browser_snapshot to see the current page (URL, title, body text, links, and buttons with selectors).
3. Use browser_click(selector) to click elements—use the selectors from the snapshot (e.g. 'a >> text=Home', 'button >> nth=0').
4. Use browser_fill(selector, text) for search boxes and form fields (e.g. 'input[name="q"]', 'input[type="search"]').
5. After each navigation or click, take a snapshot to see the new state before deciding the next step.

Be concise. When you have the information the user asked for, summarize it clearly. If a site requires login or blocks automation, say so."""
)


def _run_react_loop_same_thread(
    llm: ChatAnthropic,
    tools: list,
    messages: list[BaseMessage],
    system_message: SystemMessage,
    max_turns: int = 15,
) -> list[BaseMessage]:
    """Run ReAct in the current thread so Playwright (greenlet-bound) stays on one thread."""
    tools_by_name = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)
    current = [system_message] + list(messages)

    for _ in range(max_turns):
        response = llm_with_tools.invoke(current)
        current.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break

        for tc in tool_calls:
            name = tc.get("name")
            args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
            tid = tc.get("id") or ""
            if not name:
                current.append(ToolMessage(content="Error: tool call missing name", tool_call_id=tid))
                continue
            tool = tools_by_name.get(name)
            if not tool:
                current.append(ToolMessage(content=f"Error: unknown tool {name!r}", tool_call_id=tid))
                continue
            # Progress log: what the bot is doing
            _log_tool_call(name, args)
            try:
                out = tool.invoke(args)
                current.append(ToolMessage(content=str(out) if out is not None else "", tool_call_id=tid))
                _log_tool_result(name, out)
            except Exception as e:
                log.exception("Tool %s failed", name)
                current.append(ToolMessage(content=f"Error: {e}", tool_call_id=tid))
                log.warning("Browser: %s failed → %s", name, e)

    return current


def create_browser_agent(headless: bool | None = None):
    """
    Create a browser agent that uses Playwright for one run.
    Returns an object with .invoke({"messages": [...]}) that starts a browser, runs a same-thread ReAct loop, then closes the browser.
    """
    if headless is None:
        env_val = os.getenv("DOOT_BROWSER_HEADLESS", "").strip().lower()
        if env_val in ("1", "true", "yes"):
            headless = True
        elif env_val in ("0", "false", "no"):
            headless = False
        else:
            # No explicit setting: auto-detect — force headless if no display is available
            headless = not bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))

    class _BrowserAgent:
        def invoke(self, state: dict) -> dict:
            playwright = None
            xvfb_proc = None
            try:
                log.info("Browser: starting (headless=%s)", headless)
                playwright, page, xvfb_proc = start_browser(headless=headless)
                tools = make_browser_tools(page)
                llm = ChatAnthropic(
                    model="claude-sonnet-4-20250514",
                    anthropic_api_key=(os.getenv("ANTHROPIC_API_KEY") or "").strip() or None,
                    max_tokens=4096,
                )
                messages = list(state.get("messages") or [])
                result_messages = _run_react_loop_same_thread(
                    llm, tools, messages, BROWSER_SYSTEM_PROMPT
                )
                log.info("Browser: finished (%d messages)", len(result_messages))
                return {"messages": result_messages}
            finally:
                if playwright:
                    try:
                        playwright.stop()
                    except Exception as e:
                        log.warning("Error stopping Playwright: %s", e)
                if xvfb_proc:
                    try:
                        xvfb_proc.terminate()
                        log.info("Xvfb stopped")
                    except Exception as e:
                        log.warning("Error stopping Xvfb: %s", e)

    return _BrowserAgent()
