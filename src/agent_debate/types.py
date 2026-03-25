"""Type definitions for the agent debate system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EventType(Enum):
    """Events emitted during a debate."""

    ROUND_START = "round_start"
    AGENT_STARTED = "agent_started"
    AGENT_CHUNK = "agent_chunk"
    AGENT_COMPLETED = "agent_completed"
    OPENING_COMPLETE = "opening_complete"
    DISAGREEMENT_FOUND = "disagreement_found"
    DEBATE_ROUND_START = "debate_round_start"
    CONSENSUS_REACHED = "consensus_reached"
    DEADLOCK_RESOLVED = "deadlock_resolved"
    SYNTHESIS_START = "synthesis_start"
    SYNTHESIS_COMPLETE = "synthesis_complete"
    ERROR = "error"


@dataclass
class DebateEvent:
    """A single event emitted during a debate."""

    type: EventType
    agent_id: str | None = None
    round_number: int = 0
    content: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class ProviderConfig:
    """Configuration for a single agent in the debate."""

    provider: str  # e.g. "claude", "codex", "gemini", "amp"
    model: str | None = None  # e.g. "opus", "sonnet", "o4-mini"
    persona: str | None = None  # Override default persona assignment

    @property
    def agent_id(self) -> str:
        """Unique identifier for this agent in the debate."""
        model_suffix = f":{self.model}" if self.model else ""
        return f"{self.provider}{model_suffix}"


@dataclass
class PositionUpdate:
    """A structured record of how an agent's position changed."""

    topic: str
    previous_position: str
    next_position: str
    change_type: str
    convincing_argument: str = ""
    confidence: str = "medium"
    remaining_concern: str = ""


@dataclass
class AgentResponse:
    """A single agent's response in a debate round."""

    agent_id: str
    provider: str
    model: str | None
    round_number: int
    content: str
    persona: str = ""
    position_updates: list[PositionUpdate] = field(default_factory=list)

    @property
    def has_position_shift(self) -> bool:
        """Whether this response reports a meaningful position change."""
        return any(
            update.change_type.lower() != "maintain"
            or update.previous_position.strip() != update.next_position.strip()
            for update in self.position_updates
        )


@dataclass
class Disagreement:
    """A point of disagreement between agents."""

    topic: str
    positions: dict[str, str]  # agent_id -> position summary
    questions: list[str] = field(default_factory=list)


@dataclass
class DebateConfig:
    """Top-level configuration for a debate run."""

    providers: list[ProviderConfig]
    max_rounds: int = 3
    cwd: str = "."
    orchestrator_model: str = "sonnet"
