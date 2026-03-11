"""LangChain tools for the browser agent. Built with a live Playwright page."""

from __future__ import annotations

from langchain_core.tools import tool

from src.agents.browser.client import (
    click,
    fill,
    navigate,
    snapshot,
    type_text,
    scroll_down,
    scroll_up,
)


def make_browser_tools(page):
    """Create tools that use the given Playwright page. Use for the duration of one agent run."""

    @tool
    def browser_navigate(url: str) -> str:
        """Navigate to a URL. Use when the user wants to open a website. Pass the full URL (e.g. https://example.com) or a domain (e.g. example.com)."""
        return navigate(page, url)

    @tool
    def browser_snapshot() -> str:
        """Get a text snapshot of the current page: URL, title, body text, and a list of links and buttons with selectors. Call this after navigating or clicking to see the new state before deciding the next action."""
        return snapshot(page)

    @tool
    def browser_click(selector: str) -> str:
        """Click an element on the page. Use a Playwright selector from the snapshot (e.g. 'a >> text=Home', 'button >> nth=0', 'a >> nth=2'). Get selectors from the Links/Buttons list in browser_snapshot."""
        return click(page, selector)

    @tool
    def browser_fill(selector: str, text: str) -> str:
        """Fill a form field (input or textarea). Clears the field then types the text. Use a selector like 'input[name="q"]' or 'input[type="search"]' for search boxes."""
        return fill(page, selector, text)

    @tool
    def browser_type(selector: str, text: str) -> str:
        """Type text into an element character by character (e.g. for autocomplete). Use when browser_fill is not appropriate."""
        return type_text(page, selector, text)

    @tool
    def browser_scroll_down() -> str:
        """Scroll the page down by one viewport. Use when you need to see more content below."""
        return scroll_down(page)

    @tool
    def browser_scroll_up() -> str:
        """Scroll the page up by one viewport."""
        return scroll_up(page)

    return [
        browser_navigate,
        browser_snapshot,
        browser_click,
        browser_fill,
        browser_type,
        browser_scroll_down,
        browser_scroll_up,
    ]
