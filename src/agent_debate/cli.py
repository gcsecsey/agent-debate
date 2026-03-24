"""CLI entry point for agent-debate."""

from __future__ import annotations

import anyio
import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from .config import build_config
from .orchestrator import Orchestrator
from .providers import discover_available
from .types import DebateEvent, EventType

console = Console()


def _format_event(event: DebateEvent) -> Panel | Text | None:
    """Format a debate event for rich console output."""
    match event.type:
        case EventType.ROUND_START:
            return Panel(
                f"[bold]Round {event.round_number}: Independent Analysis[/bold]",
                style="blue",
            )
        case EventType.AGENT_COMPLETED:
            label = f"[bold green]{event.agent_id}[/bold green] (round {event.round_number})"
            return Panel(event.content, title=label, border_style="green")
        case EventType.DISAGREEMENT_FOUND:
            positions = event.metadata.get("positions", {})
            pos_text = "\n".join(f"  {k}: {v}" for k, v in positions.items())
            return Panel(
                f"[bold]{event.content}[/bold]\n{pos_text}",
                title="[bold yellow]Disagreement[/bold yellow]",
                border_style="yellow",
            )
        case EventType.DEBATE_ROUND_START:
            return Panel(
                f"[bold]Debate Round {event.round_number}[/bold]",
                style="cyan",
            )
        case EventType.CONSENSUS_REACHED:
            return Panel(
                f"[bold green]Consensus reached after round {event.round_number}[/bold green]",
                style="green",
            )
        case EventType.DEADLOCK_RESOLVED:
            return Panel(
                Markdown(event.content),
                title=f"[bold red]Judge Resolution (round {event.round_number})[/bold red]",
                border_style="red",
            )
        case EventType.SYNTHESIS_START:
            return Panel("[bold]Synthesizing results...[/bold]", style="magenta")
        case EventType.SYNTHESIS_COMPLETE:
            return Panel(
                Markdown(event.content),
                title="[bold magenta]Final Synthesis[/bold magenta]",
                border_style="magenta",
            )
        case EventType.ERROR:
            return Panel(
                f"[bold red]{event.content}[/bold red]",
                title="Error",
                border_style="red",
            )
    return None


async def _run(
    prompt: str,
    providers: str,
    max_rounds: int,
    cwd: str,
    orchestrator_model: str,
) -> None:
    """Async entry point for the debate."""
    config = build_config(
        providers=providers,
        max_rounds=max_rounds,
        cwd=cwd,
        orchestrator_model=orchestrator_model,
    )

    console.print(
        Panel(
            f"[bold]Prompt:[/bold] {prompt}\n"
            f"[bold]Agents:[/bold] {', '.join(c.agent_id for c in config.providers)}\n"
            f"[bold]Max rounds:[/bold] {max_rounds}",
            title="[bold]Agent Debate[/bold]",
            border_style="bright_blue",
        )
    )

    orchestrator = Orchestrator(config)

    async for event in orchestrator.run(prompt):
        rendered = _format_event(event)
        if rendered is not None:
            console.print(rendered)


@click.group()
def main() -> None:
    """Multi-agent debate system.

    Fan out prompts to AI coding agents, let them debate, synthesize results.
    """


@main.command()
@click.argument("prompt")
@click.option(
    "--providers",
    "-p",
    default="claude:opus,claude:sonnet,claude:haiku",
    help="Comma-separated provider specs (e.g. claude:opus,codex,gemini)",
)
@click.option(
    "--max-rounds",
    "-r",
    default=3,
    type=int,
    help="Maximum number of debate rounds",
)
@click.option(
    "--cwd",
    "-d",
    default=".",
    help="Working directory for agents",
)
@click.option(
    "--orchestrator-model",
    "-m",
    default="sonnet",
    help="Model for the orchestrator (disagreement detection, synthesis)",
)
def run(
    prompt: str,
    providers: str,
    max_rounds: int,
    cwd: str,
    orchestrator_model: str,
) -> None:
    """Run a multi-agent debate.

    PROMPT is the question or task to debate.

    Examples:

        agent-debate run "Review the auth module for security issues"

        agent-debate run -p claude:opus,codex,gemini "Should we use REST or gRPC?"

        agent-debate run -r 2 -d ./my-project "Plan the database migration"
    """
    anyio.run(_run, prompt, providers, max_rounds, cwd, orchestrator_model)


@main.command()
def discover() -> None:
    """Show which providers are available on this system."""
    availability = discover_available()
    console.print(Panel("[bold]Provider Discovery[/bold]", style="bright_blue"))
    for name, available in sorted(availability.items()):
        icon = "[green]available[/green]" if available else "[red]not found[/red]"
        console.print(f"  {name}: {icon}")


if __name__ == "__main__":
    main()
