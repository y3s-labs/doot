"""CLI for Doot."""

import logging
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
def version() -> None:
    """Show version."""
    typer.echo("0.1.0")


if __name__ == "__main__":
    app()
