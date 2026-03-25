"""Type definitions for the agent debate system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EventType(Enum):
    """Events emitted during a multi-perspective analysis."""

    ROUND_START = "round_start"
    AGENT_STARTED = "agent_started"
    AGENT_CHUNK = "agent_chunk"
    AGENT_COMPLETED = "agent_completed"
    DEDUP_START = "dedup_start"
    DEDUP_COMPLETE = "dedup_complete"
    TARGETED_DEBATE_START = "targeted_debate_start"
    SYNTHESIS_START = "synthesis_start"
    SYNTHESIS_COMPLETE = "synthesis_complete"
    ERROR = "error"


@dataclass
class DebateEvent:
    """A single event emitted during an analysis run."""

    type: EventType
    agent_id: str | None = None
    round_number: int = 0
    content: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class ProviderConfig:
    """Configuration for a single agent in the analysis."""

    provider: str  # e.g. "claude", "codex", "gemini", "amp"
    model: str | None = None  # e.g. "opus", "sonnet", "o4-mini"
    @property
    def agent_id(self) -> str:
        """Unique identifier for this agent."""
        model_suffix = f":{self.model}" if self.model else ""
        return f"{self.provider}{model_suffix}"


@dataclass
class Finding:
    """A deduplicated finding from the analysis."""

    topic: str
    description: str
    agents: list[str] = field(default_factory=list)
    severity: str = "important"  # critical, important, minor


@dataclass
class AgentResponse:
    """A single agent's response."""

    agent_id: str
    provider: str
    model: str | None
    round_number: int
    content: str


@dataclass
class Disagreement:
    """A stark contradiction between agents."""

    topic: str
    positions: dict[str, str]  # agent_id -> position summary


@dataclass
class DebateConfig:
    """Top-level configuration for an analysis run."""

    providers: list[ProviderConfig]
    max_rounds: int = 1
    cwd: str = "."
    orchestrator_model: str = "sonnet"
    report_dir: str | None = ".context/debate"
    agent_timeout: int = 300  # seconds, per provider call
