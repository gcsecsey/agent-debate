"""Tests for the orchestrator debate loop with mocked providers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_debate.orchestrator import Orchestrator
from agent_debate.types import (
    AgentResponse,
    DebateConfig,
    Disagreement,
    EventType,
    PositionUpdate,
    ProviderConfig,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


class TestEventTypes:
    def test_opening_complete_exists(self):
        assert EventType.OPENING_COMPLETE.value == "opening_complete"


class FakeProvider:
    """A mock provider that returns predetermined responses."""

    id = "claude"
    display_name = "Fake Claude"

    def __init__(self, responses: list[str]):
        self._responses = responses
        self._call_count = 0

    async def analyze(
        self,
        prompt: str,
        system_prompt: str,
        cwd: str = ".",
        model: str | None = None,
    ) -> AsyncIterator[str]:
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        yield self._responses[idx]

    def available(self) -> bool:
        return True


def make_config(num_agents: int = 3) -> DebateConfig:
    providers = [
        ProviderConfig(provider="claude", model=f"agent{i}") for i in range(num_agents)
    ]
    return DebateConfig(providers=providers, max_rounds=3)


class TestParseDisagreements:
    def test_valid_json(self):
        raw = json.dumps(
            [
                {
                    "topic": "JWT vs Sessions",
                    "positions": {"a1": "JWT", "a2": "Sessions"},
                    "questions": ["What scale?"],
                }
            ]
        )
        result = Orchestrator._parse_disagreements(raw)
        assert len(result) == 1
        assert result[0].topic == "JWT vs Sessions"
        assert result[0].positions == {"a1": "JWT", "a2": "Sessions"}
        assert result[0].questions == ["What scale?"]

    def test_json_wrapped_in_text(self):
        raw = (
            "Here are the disagreements:\n"
            + json.dumps(
                [
                    {
                        "topic": "DB choice",
                        "positions": {"a1": "Postgres", "a2": "SQLite"},
                        "questions": [],
                    }
                ]
            )
            + "\nThat's all."
        )
        result = Orchestrator._parse_disagreements(raw)
        assert len(result) == 1
        assert result[0].topic == "DB choice"

    def test_empty_array(self):
        result = Orchestrator._parse_disagreements("[]")
        assert result == []

    def test_no_json(self):
        result = Orchestrator._parse_disagreements("No disagreements found.")
        assert result == []

    def test_invalid_json(self):
        result = Orchestrator._parse_disagreements("[{invalid json}]")
        assert result == []

    def test_missing_topic(self):
        raw = json.dumps([{"positions": {"a1": "x"}}])
        result = Orchestrator._parse_disagreements(raw)
        assert result == []


class TestRoundClassification:
    def test_empty_new_is_consensus(self):
        old = [Disagreement("topic", {"a": "x", "b": "y"})]
        assert Orchestrator._classify_round(old, [], []) == "consensus"

    def test_same_topics_same_positions_is_deadlock(self):
        old = [Disagreement("topic", {"a": "x", "b": "y"})]
        new = [Disagreement("topic", {"a": "x", "b": "y"})]
        assert Orchestrator._classify_round(old, new, []) == "deadlock"

    def test_fewer_topics_is_progress(self):
        old = [
            Disagreement("topic1", {"a": "x", "b": "y"}),
            Disagreement("topic2", {"a": "p", "b": "q"}),
        ]
        new = [Disagreement("topic1", {"a": "x", "b": "y"})]
        assert Orchestrator._classify_round(old, new, []) == "progress"

    def test_same_count_different_positions_is_progress(self):
        old = [Disagreement("topic", {"a": "x", "b": "y"})]
        new = [Disagreement("topic", {"a": "x", "b": "z"})]
        assert Orchestrator._classify_round(old, new, []) == "progress"

    def test_position_shift_is_progress_even_if_judge_summary_matches(self):
        old = [Disagreement("topic", {"a": "x", "b": "y"})]
        new = [Disagreement("topic", {"a": "x", "b": "y"})]
        responses = [
            AgentResponse(
                "a",
                "claude",
                "opus",
                2,
                "Updated analysis",
                "Architect",
                [
                    PositionUpdate(
                        topic="topic",
                        previous_position="Use x",
                        next_position="Use compromise z",
                        change_type="compromise",
                    )
                ],
            )
        ]
        assert Orchestrator._classify_round(old, new, responses) == "progress"

    def test_more_topics_is_progress(self):
        old = [Disagreement("topic1", {"a": "x"})]
        new = [
            Disagreement("topic1", {"a": "x"}),
            Disagreement("topic2", {"a": "y"}),
        ]
        assert Orchestrator._classify_round(old, new, []) == "progress"


class TestPositionUpdates:
    def test_parse_position_updates(self):
        raw = json.dumps(
            [
                {
                    "topic": "JWT vs Sessions",
                    "previous_position": "Use JWT",
                    "next_position": "Use Sessions",
                    "change_type": "revise",
                    "convincing_argument": "Revocation matters more",
                    "confidence": "medium",
                    "remaining_concern": "Need Redis",
                }
            ]
        )
        result = Orchestrator._parse_position_updates(raw)
        assert len(result) == 1
        assert result[0].topic == "JWT vs Sessions"
        assert result[0].change_type == "revise"

    def test_extract_position_updates_from_structured_section(self):
        raw = """### Response to Disagreements
Keep sessions.

### Structured Position Updates
```json
[
  {
    "topic": "JWT vs Sessions",
    "previous_position": "Use JWT",
    "next_position": "Use Sessions",
    "change_type": "revise",
    "convincing_argument": "Revocation matters more",
    "confidence": "medium",
    "remaining_concern": "Need Redis"
  }
]
```
"""
        content, updates = Orchestrator._extract_position_updates(raw)
        assert "Structured Position Updates" not in content
        assert len(updates) == 1
        assert updates[0].next_position == "Use Sessions"


class TestAgentIdDedup:
    def test_unique_ids(self):
        config = DebateConfig(
            providers=[
                ProviderConfig("claude", "opus"),
                ProviderConfig("claude", "sonnet"),
            ]
        )
        orch = Orchestrator.__new__(Orchestrator)
        orch.config = config
        assert orch._agent_id(0, config.providers[0]) == "claude:opus"
        assert orch._agent_id(1, config.providers[1]) == "claude:sonnet"

    def test_duplicate_ids_get_suffix(self):
        config = DebateConfig(
            providers=[
                ProviderConfig("claude", "opus"),
                ProviderConfig("claude", "opus"),
                ProviderConfig("claude", "opus"),
            ]
        )
        orch = Orchestrator.__new__(Orchestrator)
        orch.config = config
        assert orch._agent_id(0, config.providers[0]) == "claude:opus#1"
        assert orch._agent_id(1, config.providers[1]) == "claude:opus#2"
        assert orch._agent_id(2, config.providers[2]) == "claude:opus#3"
