"""Playwright browser client for the browser agent: navigate, snapshot, click, type."""

from __future__ import annotations

import logging
import os
from typing import Any

from playwright.sync_api import Page, sync_playwright

log = logging.getLogger("doot.browser.client")

# Max chars of body text to return in snapshot (avoid token overflow)
SNAPSHOT_BODY_MAX = 8000
# Max interactive elements to list
SNAPSHOT_LINKS_MAX = 50
SNAPSHOT_BUTTONS_MAX = 30


def _escape_selector_text(s: str) -> str:
    """Escape double quotes and backslashes for use inside a quoted selector."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _build_snapshot(page: Page) -> str:
    """Build a text snapshot of the current page: URL, title, body text, and interactive elements with selectors."""
    try:
        url = page.url
        title = page.title()
    except Exception as e:
        log.warning("Could not get url/title: %s", e)
        url, title = "", ""

    parts = [f"URL: {url}", f"Title: {title}"]

    # Main body text (truncated)
    try:
        body_text = page.locator("body").inner_text()
        if body_text:
            text = body_text.strip().replace("\r\n", "\n")
            if len(text) > SNAPSHOT_BODY_MAX:
                text = text[:SNAPSHOT_BODY_MAX] + "\n... [truncated]"
            parts.append("---\nBody text:\n" + text)
    except Exception as e:
        log.warning("Could not get body text: %s", e)
        parts.append("---\nBody text: [unable to read]")

    # Links with selectors the agent can use
    try:
        links = page.locator("a[href]").evaluate_all(
            """nodes => nodes.map((el, i) => ({
                index: i,
                text: (el.textContent || '').trim().slice(0, 80),
                href: (el.getAttribute('href') || '').slice(0, 120)
            }))"""
        )
        if links:
            lines = ["---\nLinks (use browser_click with selector e.g. a >> text=\"...\" or a >> nth=N):"]
            for item in links[:SNAPSHOT_LINKS_MAX]:
                idx = item["index"]
                text = (item["text"] or "").strip() or "(no text)"
                href = (item["href"] or "").strip()
                sel = f'a >> nth={idx}' if idx > 0 else "a >> first"
                if text and text != "(no text)":
                    sel = f'a >> text="{_escape_selector_text(text[:60])}"' if len(text) < 60 else f'a >> nth={idx}'
                lines.append(f"  [{idx}] \"{text[:60]}\" href={href[:60]} selector={sel}")
            if len(links) > SNAPSHOT_LINKS_MAX:
                lines.append(f"  ... and {len(links) - SNAPSHOT_LINKS_MAX} more links")
            parts.append("\n".join(lines))
    except Exception as e:
        log.warning("Could not get links: %s", e)

    # Buttons
    try:
        buttons = page.locator("button, input[type=submit], input[type=button], [role=button]").evaluate_all(
            """nodes => nodes.map((el, i) => ({
                index: i,
                text: (el.textContent || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 80)
            }))"""
        )
        if buttons:
            lines = ["---\nButtons (use browser_click with selector e.g. button >> text=\"...\" or button >> nth=N):"]
            for item in buttons[:SNAPSHOT_BUTTONS_MAX]:
                idx = item["index"]
                text = (item["text"] or "").strip() or "(no text)"
                lines.append(f"  [{idx}] \"{text[:60]}\" selector=button >> nth={idx} or button >> text=\"...\"")
            if len(buttons) > SNAPSHOT_BUTTONS_MAX:
                lines.append(f"  ... and {len(buttons) - SNAPSHOT_BUTTONS_MAX} more buttons")
            parts.append("\n".join(lines))
    except Exception as e:
        log.warning("Could not get buttons: %s", e)

    return "\n".join(parts)


def _start_xvfb() -> Any | None:
    """Start an Xvfb virtual display and set $DISPLAY. Returns the Popen handle, or None if unavailable/unneeded."""
    import shutil
    import subprocess

    if os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"):
        return None  # real display already present
    if not shutil.which("Xvfb"):
        log.warning("Xvfb not found — headed browser will likely fail (install xvfb or use headless mode)")
        return None
    display = ":99"
    proc = subprocess.Popen(
        ["Xvfb", display, "-screen", "0", "1280x720x24", "-ac", "+extension", "GLX"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.environ["DISPLAY"] = display
    log.info("Xvfb started on %s (pid=%s)", display, proc.pid)
    return proc


def start_browser(headless: bool = True) -> tuple[Any, Page]:
    """Start a Playwright browser and return (playwright, page). Caller must call playwright.stop().
    Tries Chromium first; if the host is missing browser deps, falls back to system Chrome (channel='chrome').
    When headless=False and no display is available, automatically starts Xvfb."""
    xvfb_proc = None if headless else _start_xvfb()

    # Unset NODE_OPTIONS so Playwright's Node driver isn't started under VS Code debugger (missing bootloader in threads)
    node_opts = os.environ.pop("NODE_OPTIONS", None)
    node_debug = os.environ.pop("NODE_DEBUG", None)
    try:
        playwright = sync_playwright().start()
    except Exception:
        if xvfb_proc:
            xvfb_proc.terminate()
        raise
    finally:
        if node_opts is not None:
            os.environ["NODE_OPTIONS"] = node_opts
        if node_debug is not None:
            os.environ["NODE_DEBUG"] = node_debug
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ]
    # Strip --enable-automation from Playwright's default args — it's the primary Kasada/bot-detection trigger
    ignore_default = ["--enable-automation"]
    try:
        browser = playwright.chromium.launch(
            headless=headless, args=launch_args, ignore_default_args=ignore_default
        )
    except Exception as e:
        err = str(e).lower()
        if "missing dependencies" in err or "install-deps" in err:
            log.info("Chromium launch failed (missing deps), trying system Chrome (channel=chrome)")
            try:
                browser = playwright.chromium.launch(
                    headless=headless, channel="chrome", args=launch_args, ignore_default_args=ignore_default
                )
            except Exception as e2:
                raise RuntimeError(
                    "Browser failed to start. Chromium needs system libs; Chrome fallback also failed. "
                    "Try: python -m playwright install-deps  (or sudo playwright install-deps)"
                ) from e2
        else:
            raise
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        # Chrome UA that matches the actual Chromium engine (Firefox UA on Chromium is a red flag)
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="America/New_York",
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
    )
    # Mask automation signals checked by Kasada, PerimeterX, and similar services
    context.add_init_script("""
        // Core webdriver flag — the first thing every bot detector checks
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

        // Plugins: headless Chrome has none; real browsers have several
        Object.defineProperty(navigator, 'plugins', {
            get: () => {
                const arr = [{ name: 'Chrome PDF Plugin' }, { name: 'Chrome PDF Viewer' }, { name: 'Native Client' }];
                arr.__proto__ = PluginArray.prototype;
                return arr;
            }
        });

        // Languages
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

        // window.chrome — absent in headless, present in real Chrome
        window.chrome = {
            app: { isInstalled: false, InstallState: {}, RunningState: {} },
            runtime: { PlatformOs: {}, PlatformArch: {}, PlatformNaclArch: {}, RequestUpdateCheckStatus: {}, OnInstalledReason: {} },
            loadTimes: function() {},
            csi: function() {},
        };

        // Permissions API — headless returns 'denied' for notifications; real Chrome returns 'default'
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) =>
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters);
    """)
    page = context.new_page()
    return playwright, page, xvfb_proc


def navigate(page: Page, url: str, wait_until: str = "domcontentloaded", timeout_ms: int = 30000) -> str:
    """Navigate to URL. Returns a short status message."""
    if not url.strip():
        return "Error: URL is empty."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")
    try:
        page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        return f"Navigated to {page.url} (title: {page.title()})"
    except Exception as e:
        return f"Navigation failed: {e}"


def snapshot(page: Page) -> str:
    """Return a text snapshot of the current page for the LLM."""
    return _build_snapshot(page)


def click(page: Page, selector: str, timeout_ms: int = 10000) -> str:
    """Click an element by Playwright selector (e.g. 'a >> text=Home', 'button >> nth=0')."""
    try:
        page.click(selector, timeout=timeout_ms)
        return f"Clicked: {selector}"
    except Exception as e:
        return f"Click failed: {e}"


def fill(page: Page, selector: str, text: str, timeout_ms: int = 10000) -> str:
    """Fill an input by selector (clears then types). Use for text inputs and textareas."""
    try:
        page.fill(selector, text, timeout=timeout_ms)
        return f"Filled {selector} with {len(text)} characters."
    except Exception as e:
        return f"Fill failed: {e}"


def type_text(page: Page, selector: str, text: str, timeout_ms: int = 10000, delay_ms: int = 0) -> str:
    """Type text into an element character by character (e.g. for autocomplete)."""
    try:
        page.locator(selector).first.click(timeout=timeout_ms)
        page.keyboard.type(text, delay=delay_ms)
        return f"Typed {len(text)} characters into {selector}."
    except Exception as e:
        return f"Type failed: {e}"


def scroll_down(page: Page) -> str:
    """Scroll the page down by one viewport."""
    try:
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        return "Scrolled down."
    except Exception as e:
        return f"Scroll failed: {e}"


def scroll_up(page: Page) -> str:
    """Scroll the page up by one viewport."""
    try:
        page.evaluate("window.scrollBy(0, -window.innerHeight)")
        return "Scrolled up."
    except Exception as e:
        return f"Scroll failed: {e}"
