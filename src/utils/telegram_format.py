"""Format orchestrator/bot output for Telegram (HTML with links, bold, italic)."""

from __future__ import annotations

import re


def telegram_html_escape(s: str) -> str:
    """Escape for Telegram HTML body: & < >."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def telegram_html_escape_attr(s: str) -> str:
    """Escape for Telegram HTML attribute (e.g. href): & < > \"."""
    return telegram_html_escape(s).replace('"', "&quot;")


def format_orchestrator_reply_for_telegram(text: str) -> str:
    """
    Format the orchestrator's reply (last_ai_text) for Telegram.
    Call this on orchestrator output before sending to Telegram so messages render nicely
    (clickable links, bold/italic, proper escaping). Returns Telegram-safe HTML.
    """
    return _plain_text_to_telegram_html(text)


def _plain_text_to_telegram_html(text: str) -> str:
    """
    Convert bot response text to Telegram-safe HTML so it renders nicely.
    - Escapes & < >
    - Converts [text](url) to clickable <a href="url">text</a>
    - Converts **bold** to <b>bold</b> and *italic* to <i>italic</i>
    - Makes bare https?:// URLs clickable (e.g. Sources lines)
    """
    if not text:
        return ""
    # 1) Extract markdown links and replace with placeholders
    link_placeholder = "\x00LINK\x00"
    links: list[tuple[str, str]] = []

    def link_replacer(m: re.Match) -> str:
        links.append((m.group(1), m.group(2)))
        return f"{link_placeholder}{len(links) - 1}{link_placeholder}"

    text = re.sub(r"\[([^\]]*)\]\(([^)]*)\)", link_replacer, text)
    # 2) Escape HTML
    text = telegram_html_escape(text)
    # 3) Restore links as <a> tags
    for i, (label, url) in enumerate(links):
        if i < 10:  # guard
            safe_url = telegram_html_escape_attr(url)
            safe_label = telegram_html_escape(label)
            text = text.replace(
                f"{link_placeholder}{i}{link_placeholder}",
                f'<a href="{safe_url}">{safe_label}</a>',
            )
    # 4) Bold: **...** (non-greedy)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    # 5) Italic: *...* (single * not **)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    # 6) Lines ending with a bare URL (e.g. "  [1] Title: https://...") -> clickable link
    def line_url_replacer(m: re.Match) -> str:
        prefix, url, suffix = m.group(1), m.group(2), m.group(3)
        return f"{prefix}<a href=\"{telegram_html_escape_attr(url)}\">{telegram_html_escape(url)}</a>{suffix}"

    text = re.sub(
        r"(^.*?:\s*)(https?://\S+)(\s*)$", line_url_replacer, text, flags=re.MULTILINE
    )
    return text
