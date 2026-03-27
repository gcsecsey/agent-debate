"""CLI entry point for agent-debate."""

from __future__ import annotations

import re

import anyio
import click
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from .config import MODEL_GROUPS, build_config
from .orchestrator import Orchestrator
from .providers import discover_available
from .types import AgentResponse, EventType

console = Console()

AGENT_PREVIEW_LINES = 30


class LiveDebateDisplay:
    """Manages a Rich Live display that stays compact and updates in-place.

    During streaming, shows a single panel with one status line per agent
    (agent name, status, line count). This keeps the Live area small so
    Rich can redraw it without terminal scrolling issues.

    Full agent output is printed after the Live context exits.
    """

    def __init__(self) -> None:
        self._agent_buffers: dict[str, str] = {}
        self._agent_status: dict[str, str] = {}
        self._phase: str | None = None
        self._phase_style: str = "blue"
        self._status_panels: list[Panel] = []
        self._live: Live | None = None

    def start(self) -> Live:
        self._live = Live(
            self._render(),
            console=console,
            refresh_per_second=4,
        )
        return self._live

    def set_phase(self, text: str, style: str = "blue") -> None:
        self._phase = text
        self._phase_style = style
        self._update()

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

    def add_status(self, panel: Panel) -> None:
        """Add a status panel (e.g. dedup results) to the live display."""
        self._status_panels.append(panel)
        self._update()

    @staticmethod
    def _extract_tldr(content: str) -> str | None:
        """Extract the TL;DR section body from an agent response."""
        match = re.search(
            r"#{1,4}\s*TL;?DR\s*\n(.*?)(?=\n#{1,4}\s|\Z)",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            # Strip any remaining markdown heading lines from the body
            body = match.group(1).strip()
            lines = [l for l in body.split("\n") if not re.match(r"^#{1,4}\s", l)]
            return "\n".join(lines).strip() or None
        return None

    def print_agent_summaries(self) -> None:
        """Print the TL;DR from each agent, falling back to first few lines."""
        for agent_id, buffer in self._agent_buffers.items():
            if not buffer.strip():
                continue

            tldr = self._extract_tldr(buffer)
            if tldr:
                display_text = tldr
            else:
                # Fallback: first 5 lines
                lines = buffer.strip().split("\n")
                display_text = "\n".join(lines[:5])
                if len(lines) > 5:
                    display_text += "\n[dim]  ...[/dim]"

            console.print(
                Panel(
                    display_text,
                    title=f"[bold]{agent_id}[/bold]",
                    border_style="green",
                )
            )

    def print_agent_full(self, agent_id: str) -> None:
        """Print the full response for a specific agent."""
        buffer = self._agent_buffers.get(agent_id, "")
        if not buffer.strip():
            console.print(f"[dim]No response from {agent_id}[/dim]")
            return
        console.print(
            Panel(
                Markdown(buffer.strip()),
                title=f"[bold]{agent_id}[/bold]",
                border_style="green",
            )
        )

    def print_all_agents_full(self) -> None:
        """Print full responses for all agents."""
        for agent_id in self._agent_buffers:
            self.print_agent_full(agent_id)

    @property
    def agent_ids(self) -> list[str]:
        """Return list of agent IDs that have responses."""
        return [aid for aid, buf in self._agent_buffers.items() if buf.strip()]

    def _render(self) -> RenderableType:
        lines: list[str] = []

        for agent_id in self._agent_buffers:
            status = self._agent_status.get(agent_id, "streaming")
            buffer = self._agent_buffers[agent_id]
            line_count = len(buffer.strip().split("\n")) if buffer.strip() else 0

            if status == "streaming":
                icon = "[cyan]...[/cyan]"
                count = f"[dim]{line_count} lines[/dim]" if line_count else "[dim]waiting[/dim]"
            else:
                icon = "[green]done[/green]"
                count = f"[dim]{line_count} lines[/dim]"

            lines.append(f"  {icon}  [bold]{agent_id}[/bold]  {count}")

        for panel in self._status_panels:
            lines.append("")
            # Extract text content from status panels
            if hasattr(panel, "renderable"):
                lines.append(f"  {panel.renderable}")

        body = "\n".join(lines) if lines else "  [dim]Starting...[/dim]"
        title = f"[bold]{self._phase}[/bold]" if self._phase else "[bold]Working...[/bold]"
        return Panel(body, title=title, border_style=self._phase_style)

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
    max_parallel: int = 5,
    opening_only: bool = False,
    auto_persona: bool = False,
) -> None:
    """Async entry point for the analysis."""
    config = build_config(
        providers=providers,
        max_rounds=max_rounds,
        cwd=cwd,
        orchestrator_model=orchestrator_model,
        report_dir=report_dir,
        agent_timeout=agent_timeout,
        max_parallel=max_parallel,
        auto_persona=auto_persona,
    )

    requested_agents = {c.agent_id for c in config.providers}
    orchestrator = Orchestrator(config)
    active_agents = {c.agent_id for c in config.providers}

    skipped = requested_agents - active_agents
    if skipped:
        console.print(
            Panel(
                f"[bold yellow]Skipped unavailable providers:[/bold yellow] {', '.join(sorted(skipped))}\n"
                f"[dim]Continuing with: {', '.join(sorted(active_agents))}[/dim]",
                border_style="yellow",
            )
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
                    display.add_status(
                        Panel(
                            f"[bold red]{event.content}[/bold red]",
                            title=f"Error ({event.agent_id or 'unknown'})",
                            border_style="red",
                        )
                    )

    # Show short summaries
    display.print_agent_summaries()

    # Checkpoint
    if opening_only:
        console.print("\n[dim]Opening-only mode — debate skipped.[/dim]")
        _print_report_path(report_dir, orchestrator)
        return

    if not opening_responses:
        console.print("\n[bold red]No agents responded — nothing to debate.[/bold red]")
        _print_report_path(report_dir, orchestrator)
        return

    # Interactive menu
    agent_ids = display.agent_ids
    while True:
        console.print()
        console.print("[bold]Options:[/bold]")
        console.print("  [bold]d[/bold] — proceed with [bold]d[/bold]ebate")
        console.print("  [bold]v[/bold] — [bold]v[/bold]iew all full responses")
        for i, aid in enumerate(agent_ids, 1):
            console.print(f"  [bold]{i}[/bold] — expand [bold]{aid}[/bold]")
        console.print("  [bold]q[/bold] — [bold]q[/bold]uit (debate skipped)")

        choice = click.prompt("Choice", default="d").strip().lower()

        if choice == "d":
            break
        elif choice == "v":
            display.print_all_agents_full()
        elif choice == "q":
            console.print("[dim]Debate skipped.[/dim]")
            _print_report_path(report_dir, orchestrator)
            return
        elif choice.isdigit() and 1 <= int(choice) <= len(agent_ids):
            display.print_agent_full(agent_ids[int(choice) - 1])
        else:
            console.print("[red]Invalid choice[/red]")

    # Phase 2: Debate + synthesis
    synthesis_content = ""
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
                    display2.add_status(
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
                    display2.set_phase(
                        "Synthesizing results...",
                        style="magenta",
                    )
                case EventType.SYNTHESIS_COMPLETE:
                    synthesis_content = event.content
                case EventType.ERROR:
                    display2.add_status(
                        Panel(
                            f"[bold red]{event.content}[/bold red]",
                            title=f"Error ({event.agent_id or 'unknown'})",
                            border_style="red",
                        )
                    )

    # Print synthesis after Live context exits so it stays on screen
    if synthesis_content:
        console.print(
            Panel(
                Markdown(synthesis_content),
                title="[bold magenta]Final Synthesis[/bold magenta]",
                border_style="magenta",
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
    "--max-parallel",
    default=5,
    type=int,
    help="Maximum concurrent agent calls (default: 5)",
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
@click.option(
    "--auto-persona",
    is_flag=True,
    default=False,
    help="Auto-assign personas to agents that don't have one (use @none to skip)",
)
def run(
    prompt: str,
    providers: str,
    max_rounds: int,
    cwd: str,
    orchestrator_model: str,
    timeout: int,
    max_parallel: int,
    no_report: bool,
    opening_only: bool,
    auto_persona: bool,
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
        _run, prompt, providers, max_rounds, cwd, orchestrator_model, report_dir, timeout, max_parallel, opening_only, auto_persona
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


@main.command()
@click.option(
    "--cwd",
    "-d",
    default=".",
    help="Working directory to scan for debates",
)
@click.option(
    "--port",
    "-p",
    default=0,
    type=int,
    help="Port to serve on (default: random available port)",
)
def ui(cwd: str, port: int) -> None:
    """Open the debate viewer in your browser.

    Starts a local web server and opens the debate transcript viewer.
    Shows all past debates from the working directory.

    Examples:

        agent-debate ui

        agent-debate ui --cwd /path/to/project --port 8080
    """
    from .server import start_server

    server = start_server(cwd, port=port, open_browser=True)
    actual_port = server.server_address[1]
    console.print(
        f"[bold green]Debate viewer running at[/bold green] "
        f"[link=http://localhost:{actual_port}]http://localhost:{actual_port}[/link]"
    )
    console.print("[dim]Press Ctrl+C to stop[/dim]")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[dim]Server stopped.[/dim]")
        server.shutdown()


if __name__ == "__main__":
    main()
