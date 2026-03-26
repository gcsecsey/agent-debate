"""CLI entry point for agent-debate."""

from __future__ import annotations

import anyio
import click
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from .config import MODEL_GROUPS, build_config
from .orchestrator import Orchestrator
from .providers import discover_available
from .types import AgentResponse, EventType

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


def _print_report_path(report_dir: str | None, orchestrator: Orchestrator) -> None:
    if report_dir and orchestrator._report:
        console.print(
            f"\n[dim]Full report saved to: {orchestrator._report.run_dir}[/dim]"
        )


async def _run(
    prompt: str,
    providers: str,
    max_rounds: int,
    cwd: str,
    orchestrator_model: str,
    report_dir: str | None,
    agent_timeout: int = 300,
    opening_only: bool = False,
) -> None:
    """Async entry point for the analysis."""
    config = build_config(
        providers=providers,
        max_rounds=max_rounds,
        cwd=cwd,
        orchestrator_model=orchestrator_model,
        report_dir=report_dir,
        agent_timeout=agent_timeout,
    )

    console.print(
        Panel(
            f"[bold]Prompt:[/bold] {prompt}\n"
            f"[bold]Agents:[/bold] {', '.join(c.agent_id for c in config.providers)}\n"
            f"[bold]Max debate rounds:[/bold] {max_rounds}",
            title="[bold]Multi-Perspective Analysis[/bold]",
            border_style="bright_blue",
        )
    )

    orchestrator = Orchestrator(config)
    display = LiveDebateDisplay()

    # Phase 1: Opening arguments
    opening_responses: list[AgentResponse] = []
    with display.start():
        async for event in orchestrator.run_opening(prompt):
            if isinstance(event, AgentResponse):
                continue

            match event.type:
                case EventType.ROUND_START:
                    display.set_phase(
                        "Phase 1: Independent Analysis",
                        style="blue",
                    )
                case EventType.AGENT_STARTED:
                    display.agent_started(event.agent_id or "unknown")
                case EventType.AGENT_CHUNK:
                    display.agent_chunk(event.agent_id or "unknown", event.content)
                case EventType.AGENT_COMPLETED:
                    display.agent_completed(event.agent_id or "unknown")
                case EventType.OPENING_COMPLETE:
                    opening_responses = event.metadata["responses"]
                case EventType.ERROR:
                    display.add_static(
                        Panel(
                            f"[bold red]{event.content}[/bold red]",
                            title=f"Error ({event.agent_id or 'unknown'})",
                            border_style="red",
                        )
                    )

    # Checkpoint: ask user whether to proceed
    if opening_only:
        console.print("\n[dim]Opening-only mode — debate skipped.[/dim]")
        _print_report_path(report_dir, orchestrator)
        return

    if not opening_responses:
        console.print("\n[bold red]No agents responded — nothing to debate.[/bold red]")
        _print_report_path(report_dir, orchestrator)
        return

    proceed = click.confirm("\nProceed with debate?", default=True)
    if not proceed:
        console.print("[dim]Debate skipped.[/dim]")
        _print_report_path(report_dir, orchestrator)
        return

    # Phase 2: Debate + synthesis
    display2 = LiveDebateDisplay()
    with display2.start():
        async for event in orchestrator.run_debate(prompt, opening_responses):
            if isinstance(event, AgentResponse):
                continue

            match event.type:
                case EventType.DEDUP_START:
                    display2.set_phase(
                        "Phase 2: Deduplicating Findings",
                        style="yellow",
                    )
                case EventType.DEDUP_COMPLETE:
                    fc = event.metadata.get("findings_count", 0)
                    dc = event.metadata.get("disagreements_count", 0)
                    display2.add_static(
                        Panel(
                            f"[bold]{fc} findings[/bold] extracted, "
                            f"[bold]{dc} stark disagreement(s)[/bold]",
                            title="[bold yellow]Deduplication Complete[/bold yellow]",
                            border_style="yellow",
                        )
                    )
                case EventType.TARGETED_DEBATE_START:
                    display2.clear_agents()
                    display2.set_phase(
                        "Phase 3: Targeted Debate (stark disagreements found)",
                        style="cyan",
                    )
                case EventType.AGENT_STARTED:
                    display2.agent_started(event.agent_id or "unknown")
                case EventType.AGENT_CHUNK:
                    display2.agent_chunk(event.agent_id or "unknown", event.content)
                case EventType.AGENT_COMPLETED:
                    display2.agent_completed(event.agent_id or "unknown")
                case EventType.SYNTHESIS_START:
                    display2.clear_agents()
                    display2.add_static(
                        Panel("[bold]Synthesizing results...[/bold]", style="magenta")
                    )
                case EventType.SYNTHESIS_COMPLETE:
                    display2.add_static(
                        Panel(
                            Markdown(event.content),
                            title="[bold magenta]Final Synthesis[/bold magenta]",
                            border_style="magenta",
                        )
                    )
                case EventType.ERROR:
                    display2.add_static(
                        Panel(
                            f"[bold red]{event.content}[/bold red]",
                            title=f"Error ({event.agent_id or 'unknown'})",
                            border_style="red",
                        )
                    )

    _print_report_path(report_dir, orchestrator)


@click.group()
def main() -> None:
    """Multi-perspective analysis system.

    Fan out prompts to AI coding agents, deduplicate findings, synthesize results.
    """


@main.command()
@click.argument("prompt")
@click.option(
    "--providers",
    "-p",
    default="top",
    help=(
        "Comma-separated provider specs or group name. "
        f"Groups: {', '.join(f'{k} ({v})' for k, v in MODEL_GROUPS.items())}"
    ),
)
@click.option(
    "--max-rounds",
    "-r",
    default=1,
    type=int,
    help="Maximum targeted debate rounds (0 to disable debate entirely)",
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
    help="Model for the orchestrator (deduplication, synthesis)",
)
@click.option(
    "--timeout",
    "-t",
    default=300,
    type=int,
    help="Timeout per agent call in seconds (default: 300)",
)
@click.option(
    "--no-report",
    is_flag=True,
    default=False,
    help="Disable saving the markdown report",
)
@click.option(
    "--opening-only",
    is_flag=True,
    default=False,
    help="Run only the opening arguments phase (skip debate)",
)
def run(
    prompt: str,
    providers: str,
    max_rounds: int,
    cwd: str,
    orchestrator_model: str,
    timeout: int,
    no_report: bool,
    opening_only: bool,
) -> None:
    """Run a multi-perspective analysis.

    PROMPT is the question or task to analyze.

    Examples:

        agent-debate run "Review the auth module for security issues"

        agent-debate run -p top "Should we use REST or gRPC?"

        agent-debate run -p fast "Plan the database migration"

        agent-debate run -p claude:opus,codex,gemini "Design the caching layer"
    """
    report_dir = None if no_report else ".context/debate"
    anyio.run(
        _run, prompt, providers, max_rounds, cwd, orchestrator_model, report_dir, timeout, opening_only
    )


@main.command()
def discover() -> None:
    """Show which providers are available on this system."""
    availability = discover_available()
    console.print(Panel("[bold]Provider Discovery[/bold]", style="bright_blue"))
    for name, available in sorted(availability.items()):
        icon = "[green]available[/green]" if available else "[red]not found[/red]"
        console.print(f"  {name}: {icon}")

    console.print(
        f"\n[dim]Model groups: "
        + ", ".join(f"{k} = {v}" for k, v in MODEL_GROUPS.items())
        + "[/dim]"
    )


if __name__ == "__main__":
    main()
