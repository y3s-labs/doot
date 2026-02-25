"""CLI for Doot."""

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root so it works regardless of cwd (e.g. python -m src.cli)
_load_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_load_env_path)

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.markdown import Markdown

from src.agents.gmail.auth import get_credentials
from src.session import load_session, save_session

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(message)s",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
)
# Reduce noise from google-genai (e.g. "AFC is enabled with max remote calls: 10")
logging.getLogger("google_genai.models").setLevel(logging.WARNING)
log = logging.getLogger("doot")

app = typer.Typer(no_args_is_help=True)
console = Console()


def _run_webhook() -> None:
    """Start the webhook server (used by start and default no-arg)."""
    from src.webhook import run_webhook_server

    run_webhook_server()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Doot: your personal AI envoy. Run with no command to start the webhook server."""
    if ctx.invoked_subcommand is None:
        _run_webhook()


def _pid_path() -> Path:
    """Path for the background process PID file."""
    path = os.getenv("DOOT_PID_PATH")
    if path:
        return Path(path).expanduser()
    # Same base dir as tokens (e.g. ~/.doot)
    base = os.getenv("DOOT_TOKENS_PATH", "~/.doot/tokens.json")
    return Path(base).expanduser().parent / "doot.pid"


def _log_path() -> Path:
    """Path for background process log file."""
    path = os.getenv("DOOT_LOG_PATH")
    if path:
        return Path(path).expanduser()
    return _pid_path().parent / "doot.log"


@app.command()
def start(
    background: bool = typer.Option(False, "--background", "-d", help="Run webhook server in background (writes PID file)."),
) -> None:
    """Start Doot: webhook server + interactive chat. Use --background for webhook-only (no chat)."""
    if not background:
        thread = threading.Thread(target=_run_webhook, daemon=True)
        thread.start()
        time.sleep(0.5)  # let webhook bind before starting chat
        _run_chat_interactive()
        return

    pid_file = _pid_path()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    if pid_file.exists():
        try:
            existing = int(pid_file.read_text().strip())
            os.kill(existing, 0)  # check if process exists (raises ProcessLookupError if not)
            typer.echo(f"Doot already running (PID {existing}). Use 'doot stop' first.", err=True)
            raise typer.Exit(1)
        except (ProcessLookupError, ValueError, OSError):
            pass
        pid_file.unlink(missing_ok=True)

    log_file = _log_path()
    with open(log_file, "a") as fh:
        proc = subprocess.Popen(
            [sys.executable, "-m", "src.cli", "webhook"],
            cwd=os.getcwd(),
            stdout=fh,
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
            start_new_session=True,
        )
    pid_file.write_text(str(proc.pid))
    typer.echo(f"Doot started in background (PID {proc.pid}). Logs: {log_file}")


@app.command()
def stop() -> None:
    """Stop the Doot webhook server running in the background."""
    pid_file = _pid_path()
    if not pid_file.exists():
        typer.echo("No PID file found; Doot is not running in background.", err=True)
        raise typer.Exit(0)

    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        pid_file.unlink(missing_ok=True)
        typer.echo("Invalid PID file; removed.", err=True)
        raise typer.Exit(0)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        typer.echo(f"Process {pid} not running; removing PID file.")
        pid_file.unlink(missing_ok=True)
        raise typer.Exit(0)

    os.kill(pid, signal.SIGTERM)
    for _ in range(25):
        time.sleep(0.2)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pid_file.unlink(missing_ok=True)
            typer.echo("Doot stopped.")
            return
    os.kill(pid, signal.SIGKILL)
    pid_file.unlink(missing_ok=True)
    typer.echo("Doot stopped (SIGKILL).")


@app.command()
def auth() -> None:
    """Obtain or refresh Google OAuth2 credentials (Gmail + Calendar)."""
    get_credentials()
    typer.echo("Credentials saved.")


@app.command()
def check_env() -> None:
    """Verify ANTHROPIC_API_KEY by making one minimal API call. Use this to confirm the key is valid."""
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        typer.echo("ANTHROPIC_API_KEY is not set or empty. Add it to .env and try again.", err=True)
        raise typer.Exit(1)
    try:
        from anthropic import Anthropic
        from anthropic import AuthenticationError
    except ImportError:
        typer.echo("anthropic package not installed.", err=True)
        raise typer.Exit(1)
    try:
        client = Anthropic(api_key=key)
        client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1,
            messages=[{"role": "user", "content": "Hi"}],
        )
        typer.echo("ANTHROPIC_API_KEY is valid.")
    except AuthenticationError as e:
        typer.echo(
            "ANTHROPIC_API_KEY was rejected (401). Create a new key at https://console.anthropic.com/ "
            "and set it in .env.",
            err=True,
        )
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Unexpected error: {e}", err=True)
        raise typer.Exit(1)


def _run_chat_interactive() -> None:
    """Load session, run interactive chat loop (read input, invoke, save, print)."""
    from langchain_core.messages import HumanMessage

    from src.graph.orchestrator import build_orchestrator

    messages = load_session()
    orchestrator = build_orchestrator()
    console.print("[bold green]Doot[/] interactive mode. Type [bold]quit[/] or [bold]exit[/] to leave.\n")
    while True:
        try:
            user_input = console.input("[bold cyan]You:[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nBye!")
            break
        if not user_input or user_input.lower() in ("quit", "exit"):
            console.print("Bye!")
            break
        messages = messages + [HumanMessage(content=user_input)]
        result_messages = _invoke_and_print(orchestrator, messages)
        save_session(result_messages)
        messages = result_messages


@app.command()
def chat(message: str | None = typer.Argument(None, help="One-shot message. Omit for interactive mode.")) -> None:
    """Talk to the Doot orchestrator (routes to Gmail agent, etc). Session is loaded/saved to file."""
    from langchain_core.messages import HumanMessage

    from src.graph.orchestrator import build_orchestrator

    orchestrator = build_orchestrator()

    if message:
        messages = load_session()
        result_messages = _run_once(orchestrator, message, messages)
        save_session(result_messages)
        return

    _run_chat_interactive()


def _print_last_ai(messages) -> None:
    """Print the last AI message from a message list (for console output)."""
    from langchain_core.messages import AIMessage

    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            content = msg.content
            if isinstance(content, list):
                content = "\n".join(
                    block.get("text", str(block)) if isinstance(block, dict) else str(block) for block in content
                )
            console.print()
            console.print(Markdown(content))
            console.print()
            return


def _invoke_and_print(orchestrator, messages):
    """Invoke orchestrator with messages, print last AI reply, return result['messages']."""
    log.info("Sending (session has %d messages)", len(messages))
    result = orchestrator.invoke({"messages": messages, "route": ""})
    log.info("Route chosen: %s", result.get("route", "?"))
    _print_last_ai(result["messages"])
    return result["messages"]


def _run_once(orchestrator, message: str, initial_messages=None):
    """Run one turn: optional prior messages + new user message; print AI reply; return result messages."""
    from langchain_core.messages import HumanMessage

    messages = list(initial_messages or []) + [HumanMessage(content=message)]
    return _invoke_and_print(orchestrator, messages)


@app.command()
def webhook() -> None:
    """Run the webhook server (Gmail Pub/Sub push). Alias for 'start'. Point subscription to {WEBHOOK_URL}/webhook/gmail."""
    _run_webhook()


@app.command()
def telegram_poll() -> None:
    """Run the Telegram bot in polling mode (no public URL needed). Uses the same global session as CLI and webhook."""
    import asyncio

    from telegram import Update
    from telegram.ext import Application, MessageHandler, filters

    from src.webhook import process_telegram_message

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        typer.echo("Set TELEGRAM_BOT_TOKEN in .env", err=True)
        raise typer.Exit(1)

    async def handle(update: Update, context) -> None:
        if update.message and update.message.text:
            process_telegram_message(update.effective_chat.id, update.message.text)

    application = Application.builder().token(token).build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    typer.echo("Telegram polling started. Send a message to your bot.")
    asyncio.run(application.run_polling(allowed_updates=Update.ALL_TYPES))


@app.command()
def watch_gmail() -> None:
    """Register Gmail to push to your Pub/Sub topic. Run after webhook is reachable; renew before expiration."""
    import os

    from src.agents.gmail.client import watch

    topic = os.getenv("PUBSUB_TOPIC")
    if not topic:
        typer.echo("Set PUBSUB_TOPIC in .env (e.g. projects/doot-488123/topics/doot-gmail)", err=True)
        raise typer.Exit(1)
    result = watch(topic_name=topic, label_ids=["INBOX"])
    typer.echo(f"Watch registered: historyId={result.get('historyId')} expiration={result.get('expiration')}")
    typer.echo("Send yourself a test email; you should see a POST on your webhook.")


@app.command(name="check-gemini")
def check_gemini() -> None:
    """Verify GEMINI_API_KEY is set and accepted by the Gemini API (for web search)."""
    raw = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    key = raw.strip().strip('"').strip("'")
    if not key:
        typer.echo("GEMINI_API_KEY (or GOOGLE_API_KEY) is not set. Add it to .env from https://aistudio.google.com/apikey", err=True)
        raise typer.Exit(1)
    typer.echo(f"Key is set (length {len(key)}). Calling Gemini API...")
    try:
        from src.agents.websearch.client import _get_client
        from google.genai import types
        client = _get_client()
        # Minimal call without search to validate the key (same model as websearch agent)
        response = client.models.generate_content(
            model="gemini-flash-lite-latest",
            contents="Reply with exactly: OK",
            config=types.GenerateContentConfig(max_output_tokens=10),
        )
        text = (response.text or "").strip()
        typer.echo("Gemini API key is valid." if text else "Got empty response (key may still work).")
    except Exception as e:
        typer.echo(f"Gemini API error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show version."""
    typer.echo("0.1.0")


if __name__ == "__main__":
    app()
