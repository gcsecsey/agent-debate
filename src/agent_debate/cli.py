"""CLI entry point for agent-debate."""

from __future__ import annotations

import anyio
import click
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from .config import build_config
from .orchestrator import Orchestrator
from .providers import discover_available
from .types import AgentResponse, DebateEvent, EventType

console = Console()

AGENT_PREVIEW_LINES = 30


class LiveDebateDisplay:
    """Manages a Rich Live display with per-agent streaming panels."""

    def __init__(self) -> None:
        self._agent_buffers: dict[str, str] = {}
        self._agent_status: dict[str, str] = {}
        self._live: Live | None = None

    def start(self) -> Live:
        self._live = Live(
            self._render(),
            console=console,
            refresh_per_second=4,
            vertical_overflow="visible",
        )
        return self._live

    def set_phase(self, text: str, style: str = "blue") -> None:
        self._flush_static(Panel(f"[bold]{text}[/bold]", style=style))

    def agent_started(self, agent_id: str) -> None:
        self._agent_buffers[agent_id] = ""
        self._agent_status[agent_id] = "streaming"
        self._update()

    def agent_chunk(self, agent_id: str, chunk: str) -> None:
        if agent_id in self._agent_buffers:
            self._agent_buffers[agent_id] += chunk
            self._update()

    def agent_completed(self, agent_id: str) -> None:
        self._agent_status[agent_id] = "done"
        self._update()

    def clear_agents(self) -> None:
        self._agent_buffers.clear()
        self._agent_status.clear()
        self._update()

    def add_static(self, panel: Panel) -> None:
        self._flush_static(panel)

    def _flush_static(self, panel: Panel) -> None:
        if self._live is not None:
            self._live.console.print(panel)

    def _render(self) -> Group:
        renderables = []
        for agent_id, buffer in self._agent_buffers.items():
            status = self._agent_status.get(agent_id, "streaming")
            lines = buffer.strip().split("\n")
            total_lines = len(lines)

            if status == "streaming":
                border = "cyan"
                suffix = f" [dim]streaming... ({total_lines} lines)[/dim]"
            else:
                border = "green"
                suffix = f" [dim]({total_lines} lines)[/dim]"

            if total_lines > AGENT_PREVIEW_LINES:
                visible = (
                    lines[:15]
                    + [f"\n  [dim]... {total_lines - 25} lines hidden ...[/dim]\n"]
                    + lines[-10:]
                )
                display_text = "\n".join(visible)
            else:
                display_text = buffer.strip()

            title = f"[bold]{agent_id}[/bold]{suffix}"
            renderables.append(Panel(display_text, title=title, border_style=border))

        return Group(*renderables)

    def _update(self) -> None:
        if self._live is not None:
            self._live.update(self._render())


def _handle_event(display: LiveDebateDisplay, event: DebateEvent) -> None:
    """Route a DebateEvent to the appropriate display action."""
    match event.type:
        case EventType.ROUND_START:
            display.set_phase(
                f"Round {event.round_number}: Independent Analysis",
                style="blue",
            )
        case EventType.AGENT_STARTED:
            display.agent_started(event.agent_id or "unknown")
        case EventType.AGENT_CHUNK:
            display.agent_chunk(event.agent_id or "unknown", event.content)
        case EventType.AGENT_COMPLETED:
            display.agent_completed(event.agent_id or "unknown")
        case EventType.DISAGREEMENT_FOUND:
            positions = event.metadata.get("positions", {})
            pos_text = "\n".join(
                f"  {key}: {value}" for key, value in positions.items()
            )
            display.add_static(
                Panel(
                    f"[bold]{event.content}[/bold]\n{pos_text}",
                    title="[bold yellow]Disagreement[/bold yellow]",
                    border_style="yellow",
                )
            )
        case EventType.DEBATE_ROUND_START:
            display.clear_agents()
            display.set_phase(
                f"Debate Round {event.round_number}",
                style="cyan",
            )
        case EventType.CONSENSUS_REACHED:
            display.add_static(
                Panel(
                    f"[bold green]Consensus reached after round {event.round_number}[/bold green]",
                    style="green",
                )
            )
        case EventType.DEADLOCK_RESOLVED:
            display.clear_agents()
            display.add_static(
                Panel(
                    Markdown(event.content),
                    title=f"[bold red]Judge Resolution (round {event.round_number})[/bold red]",
                    border_style="red",
                )
            )
        case EventType.SYNTHESIS_START:
            display.clear_agents()
            display.add_static(
                Panel("[bold]Synthesizing results...[/bold]", style="magenta")
            )
        case EventType.SYNTHESIS_COMPLETE:
            display.add_static(
                Panel(
                    Markdown(event.content),
                    title="[bold magenta]Final Synthesis[/bold magenta]",
                    border_style="magenta",
                )
            )
        case EventType.ERROR:
            display.add_static(
                Panel(
                    f"[bold red]{event.content}[/bold red]",
                    title=f"Error ({event.agent_id or 'unknown'})",
                    border_style="red",
                )
            )


async def _run(
    prompt: str,
    providers: str,
    max_rounds: int,
    cwd: str,
    orchestrator_model: str,
    opening_only: bool = False,
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
    display = LiveDebateDisplay()
    opening_responses: list[AgentResponse] = []

    # Phase 1: Opening arguments
    with display.start():
        async for event in orchestrator.run_opening(prompt):
            if event.type == EventType.OPENING_COMPLETE:
                opening_responses = event.metadata["responses"]
                continue
            _handle_event(display, event)

    # Print full opening arguments now that streaming is done
    console.print()
    console.print(
        Panel("[bold]Opening Arguments[/bold]", style="blue")
    )
    for response in opening_responses:
        label = response.persona or response.agent_id
        console.print(
            Panel(
                Markdown(response.content),
                title=f"[bold]{response.agent_id}[/bold] ({label})",
                border_style="green",
            )
        )

    # If opening-only mode, stop here
    if opening_only:
        return

    # Checkpoint: ask human whether to proceed
    if not click.confirm("\nProceed with debate?", default=True):
        console.print("[dim]Debate skipped.[/dim]")
        return

    # Phase 2: Debate rounds + synthesis
    display = LiveDebateDisplay()
    with display.start():
        async for event in orchestrator.run_debate(prompt, opening_responses):
            _handle_event(display, event)


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
@click.option(
    "--opening-only",
    is_flag=True,
    default=False,
    help="Run only the opening arguments phase (no debate or checkpoint prompt)",
)
def run(
    prompt: str,
    providers: str,
    max_rounds: int,
    cwd: str,
    orchestrator_model: str,
    opening_only: bool,
) -> None:
    """Run a multi-agent debate.

    PROMPT is the question or task to debate.

    Examples:

        agent-debate run "Review the auth module for security issues"

        agent-debate run -p claude:opus,codex,gemini "Should we use REST or gRPC?"

        agent-debate run -r 2 -d ./my-project "Plan the database migration"
    """
    anyio.run(_run, prompt, providers, max_rounds, cwd, orchestrator_model, opening_only)


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
