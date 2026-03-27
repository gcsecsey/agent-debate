"""Markdown report writer for multi-perspective analysis runs."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from .types import AgentResponse, Disagreement, Finding, ProviderConfig


class ReportWriter:
    """Saves a full analysis run to a timestamped markdown directory."""

    def __init__(self, base_dir: str, cwd: str = ".") -> None:
        timestamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
        self.run_dir = Path(cwd) / base_dir / timestamp
        self._agents_dir = self.run_dir / "agents"
        self._debate_dir = self.run_dir / "debate"
        self._json_data: dict = {}

    def start_run(
        self,
        prompt: str,
        providers: list[ProviderConfig],
        orchestrator_model: str = "sonnet",
        max_rounds: int = 1,
    ) -> Path:
        """Create the run directory and write the README header."""
        self._agents_dir.mkdir(parents=True, exist_ok=True)

        self._json_data = {
            "version": 1,
            "meta": {
                "prompt": prompt,
                "providers": [
                    {
                        "provider": pc.provider,
                        "model": pc.model,
                        "agent_id": pc.agent_id,
                    }
                    for pc in providers
                ],
                "orchestrator_model": orchestrator_model,
                "max_rounds": max_rounds,
                "cwd": str(self.run_dir.parent.parent),
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
            },
            "opening": {"responses": []},
            "dedup": None,
            "debate": None,
            "synthesis": None,
        }

        agents_list = ", ".join(pc.agent_id for pc in providers)
        readme = (
            f"# Analysis Run\n\n"
            f"**Prompt:** {prompt}\n\n"
            f"**Models:** {agents_list}\n\n"
            f"**Time:** {datetime.now().isoformat()}\n"
        )
        (self.run_dir / "README.md").write_text(readme)
        return self.run_dir

    def save_agent_response(self, response: AgentResponse) -> None:
        """Save an agent's full response to agents/<agent_id>.md."""
        filename = _safe_filename(response.agent_id)
        path = self._agents_dir / f"{filename}.md"
        content = (
            f"# {response.agent_id}\n\n"
            f"{response.content}\n"
        )
        path.write_text(content)

    def save_dedup(
        self,
        raw_reasoning: str,
        findings: list[Finding],
        disagreements: list[Disagreement],
    ) -> None:
        """Save the orchestrator's dedup analysis."""
        lines = ["# Deduplication Analysis\n"]

        lines.append("## Orchestrator Reasoning\n")
        lines.append(raw_reasoning)
        lines.append("")

        lines.append("## Parsed Findings\n")
        lines.append("| # | Finding | Severity | Agents |")
        lines.append("|---|---------|----------|--------|")
        for i, f in enumerate(findings, 1):
            agents = ", ".join(f.agents)
            lines.append(f"| {i} | {f.topic} | {f.severity} | {agents} |")
        lines.append("")

        if disagreements:
            lines.append("## Stark Disagreements\n")
            for d in disagreements:
                lines.append(f"### {d.topic}\n")
                for aid, pos in d.positions.items():
                    lines.append(f"- **{aid}**: {pos}")
                lines.append("")
        else:
            lines.append("## Stark Disagreements\n")
            lines.append("None — agents substantially agreed.\n")

        (self.run_dir / "dedup.md").write_text("\n".join(lines))

    def save_debate_response(self, response: AgentResponse) -> None:
        """Save a targeted debate response to debate/<agent_id>.md."""
        self._debate_dir.mkdir(parents=True, exist_ok=True)
        filename = _safe_filename(response.agent_id)
        path = self._debate_dir / f"{filename}.md"
        content = (
            f"# {response.agent_id} — Targeted Debate\n\n"
            f"{response.content}\n"
        )
        path.write_text(content)

    def save_synthesis(self, content: str) -> None:
        """Save the final synthesis."""
        (self.run_dir / "synthesis.md").write_text(
            f"# Final Synthesis\n\n{content}\n"
        )

    def finalize_readme(self, synthesis: str) -> None:
        """Append the synthesis summary to the README."""
        readme_path = self.run_dir / "README.md"
        existing = readme_path.read_text()
        readme_path.write_text(
            existing + f"\n---\n\n## Synthesis\n\n{synthesis}\n"
        )


def _safe_filename(agent_id: str) -> str:
    """Convert an agent_id to a safe filename."""
    return agent_id.replace(":", "-").replace("#", "-").replace("/", "-")
