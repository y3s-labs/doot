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

load_dotenv()

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.markdown import Markdown

from src.agents.gmail.auth import get_credentials

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(message)s",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
)
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


def _session_path() -> Path:
    """Path for persisted chat session (JSON)."""
    base = os.getenv("DOOT_TOKENS_PATH", "~/.doot/tokens.json")
    return Path(base).expanduser().parent / "chat_session.json"


def _load_session():
    """Load session messages from file. Returns list of HumanMessage/AIMessage; empty list if missing or invalid."""
    from langchain_core.messages import AIMessage, HumanMessage

    path = _session_path()
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


def _save_session(messages) -> None:
    """Persist message list to session file (JSON array of {role, content})."""
    from langchain_core.messages import AIMessage, HumanMessage

    path = _session_path()
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


def _run_chat_interactive() -> None:
    """Load session, run interactive chat loop (read input, invoke, save, print)."""
    from langchain_core.messages import HumanMessage

    from src.graph.orchestrator import build_orchestrator

    messages = _load_session()
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
        _save_session(result_messages)
        messages = result_messages


@app.command()
def chat(message: str | None = typer.Argument(None, help="One-shot message. Omit for interactive mode.")) -> None:
    """Talk to the Doot orchestrator (routes to Gmail agent, etc). Session is loaded/saved to file."""
    from langchain_core.messages import HumanMessage

    from src.graph.orchestrator import build_orchestrator

    orchestrator = build_orchestrator()

    if message:
        messages = _load_session()
        result_messages = _run_once(orchestrator, message, messages)
        _save_session(result_messages)
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


@app.command()
def version() -> None:
    """Show version."""
    typer.echo("0.1.0")


if __name__ == "__main__":
    app()
