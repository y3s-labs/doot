"""CLI for Doot."""

import logging
import os
import signal
import subprocess
import sys
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


@app.command()
def start(
    background: bool = typer.Option(False, "--background", "-d", help="Run webhook server in background (writes PID file)."),
) -> None:
    """Start Doot (webhook server for Gmail Pub/Sub). Same as running 'doot' with no command."""
    if not background:
        _run_webhook()
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
            [sys.executable, "-m", "src.cli", "start"],
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
def chat(message: str | None = typer.Argument(None, help="One-shot message. Omit for interactive mode.")) -> None:
    """Talk to the Doot orchestrator (routes to Gmail agent, etc)."""
    from langchain_core.messages import AIMessage, HumanMessage

    from src.graph.orchestrator import build_orchestrator

    orchestrator = build_orchestrator()

    if message:
        _run_once(orchestrator, message)
        return

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
        _run_once(orchestrator, user_input)


def _run_once(orchestrator, message: str):
    from langchain_core.messages import AIMessage, HumanMessage

    log.info("Sending: %s", message)
    result = orchestrator.invoke({"messages": [HumanMessage(content=message)], "route": ""})
    log.info("Route chosen: %s", result.get("route", "?"))
    log.debug("Full result keys: %s", list(result.keys()))

    for msg in result["messages"]:
        if isinstance(msg, AIMessage) and msg.content:
            content = msg.content
            # Anthropic can return content as a list of blocks
            if isinstance(content, list):
                content = "\n".join(
                    block.get("text", str(block)) if isinstance(block, dict) else str(block)
                    for block in content
                )
            log.debug("AI message type=%s content_type=%s", type(msg).__name__, type(msg.content).__name__)
            console.print()
            console.print(Markdown(content))
            console.print()


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
