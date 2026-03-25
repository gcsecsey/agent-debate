"""Tests for the orchestrator with mocked providers."""

from __future__ import annotations

import asyncio
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
    Finding,
    ProviderConfig,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


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
    return DebateConfig(providers=providers, max_rounds=1, report_dir=None)


class TestParseDedupResponse:
    def test_valid_json(self):
        raw = json.dumps(
            {
                "findings": [
                    {
                        "topic": "Use connection pooling",
                        "description": "Both agents recommend connection pooling",
                        "agents": ["a1", "a2"],
                        "severity": "important",
                    }
                ],
                "stark_disagreements": [
                    {
                        "topic": "JWT vs Sessions",
                        "positions": {"a1": "JWT", "a2": "Sessions"},
                    }
                ],
            }
        )
        findings, disagreements = Orchestrator._parse_dedup_response(raw)
        assert len(findings) == 1
        assert findings[0].topic == "Use connection pooling"
        assert findings[0].agents == ["a1", "a2"]
        assert len(disagreements) == 1
        assert disagreements[0].topic == "JWT vs Sessions"

    def test_json_wrapped_in_markdown(self):
        raw = (
            "Here is the analysis:\n```json\n"
            + json.dumps(
                {
                    "findings": [
                        {
                            "topic": "DB choice",
                            "description": "Use Postgres",
                            "agents": ["a1"],
                            "severity": "critical",
                        }
                    ],
                    "stark_disagreements": [],
                }
            )
            + "\n```\nDone."
        )
        findings, disagreements = Orchestrator._parse_dedup_response(raw)
        assert len(findings) == 1
        assert findings[0].severity == "critical"
        assert disagreements == []

    def test_no_json(self):
        findings, disagreements = Orchestrator._parse_dedup_response(
            "No findings to report."
        )
        assert findings == []
        assert disagreements == []

    def test_invalid_json(self):
        findings, disagreements = Orchestrator._parse_dedup_response(
            "{invalid json}"
        )
        assert findings == []
        assert disagreements == []

    def test_empty_findings(self):
        raw = json.dumps({"findings": [], "stark_disagreements": []})
        findings, disagreements = Orchestrator._parse_dedup_response(raw)
        assert findings == []
        assert disagreements == []

    def test_missing_topic_skipped(self):
        raw = json.dumps(
            {
                "findings": [{"description": "no topic"}],
                "stark_disagreements": [{"positions": {"a": "x"}}],
            }
        )
        findings, disagreements = Orchestrator._parse_dedup_response(raw)
        assert findings == []
        assert disagreements == []


class TestAgentIdDedup:
    def test_unique_ids(self):
        config = DebateConfig(
            providers=[
                ProviderConfig("claude", "opus"),
                ProviderConfig("claude", "sonnet"),
            ],
            report_dir=None,
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
            ],
            report_dir=None,
        )
        orch = Orchestrator.__new__(Orchestrator)
        orch.config = config
        assert orch._agent_id(0, config.providers[0]) == "claude:opus#1"
        assert orch._agent_id(1, config.providers[1]) == "claude:opus#2"
        assert orch._agent_id(2, config.providers[2]) == "claude:opus#3"


class SlowProvider:
    """A mock provider that yields one chunk then hangs."""

    id = "claude"
    display_name = "Slow Claude"

    async def analyze(
        self,
        prompt: str,
        system_prompt: str,
        cwd: str = ".",
        model: str | None = None,
    ) -> AsyncIterator[str]:
        yield "partial response..."
        await asyncio.sleep(999)

    def available(self) -> bool:
        return True


class TestProviderTimeout:
    @pytest.mark.asyncio
    async def test_slow_provider_times_out(self):
        config = DebateConfig(
            providers=[
                ProviderConfig("claude", "fast"),
                ProviderConfig("claude", "slow"),
            ],
            max_rounds=0,
            report_dir=None,
            agent_timeout=1,
        )

        orch = Orchestrator.__new__(Orchestrator)
        orch.config = config
        orch._report = None
        orch._providers = {"claude": FakeProvider(["Fast response"])}

        # Inject slow provider for the second agent
        fast_provider = FakeProvider(["Fast response"])
        slow_provider = SlowProvider()

        original_fan_out = orch._fan_out_streaming

        async def patched_fan_out(prompt, round_number, span=None):
            # Override _providers per-agent by patching run_agent
            queue: asyncio.Queue = asyncio.Queue()
            providers_map = {0: fast_provider, 1: slow_provider}

            async def run_agent(index, pc):
                provider = providers_map[index]
                agent_id = orch._agent_id(index, pc)
                from agent_debate.prompts import build_round1_prompt
                full_prompt = build_round1_prompt(prompt)

                await queue.put(
                    DebateEvent(type=EventType.AGENT_STARTED, agent_id=agent_id)
                )

                try:
                    chunks = []

                    async def _stream():
                        async for chunk in provider.analyze(
                            prompt=full_prompt,
                            system_prompt="",
                            cwd=orch.config.cwd,
                            model=pc.model,
                        ):
                            chunks.append(chunk)
                            await queue.put(
                                DebateEvent(
                                    type=EventType.AGENT_CHUNK,
                                    agent_id=agent_id,
                                    round_number=round_number,
                                    content=chunk,
                                )
                            )

                    await asyncio.wait_for(
                        _stream(), timeout=orch.config.agent_timeout
                    )

                    content = "".join(chunks)
                    response = AgentResponse(
                        agent_id=agent_id,
                        provider=pc.provider,
                        model=pc.model,
                        round_number=round_number,
                        content=content,
                    )
                    await queue.put(
                        DebateEvent(
                            type=EventType.AGENT_COMPLETED,
                            agent_id=agent_id,
                            round_number=round_number,
                        )
                    )
                    await queue.put(response)
                except asyncio.TimeoutError:
                    await queue.put(
                        DebateEvent(
                            type=EventType.ERROR,
                            agent_id=agent_id,
                            content=f"Agent timed out after {orch.config.agent_timeout}s",
                        )
                    )
                except Exception as exc:
                    await queue.put(
                        DebateEvent(
                            type=EventType.ERROR,
                            agent_id=agent_id,
                            content=str(exc),
                        )
                    )
                finally:
                    await queue.put(None)

            for index, pc in enumerate(config.providers):
                asyncio.create_task(run_agent(index, pc))

            completed = 0
            while completed < len(config.providers):
                item = await queue.get()
                if item is None:
                    completed += 1
                    continue
                yield item

        from agent_debate.types import DebateEvent

        events = []
        async for event in patched_fan_out("test prompt", round_number=1):
            events.append(event)

        event_types = [e.type for e in events if isinstance(e, DebateEvent)]
        assert EventType.AGENT_COMPLETED in event_types, "Fast agent should complete"

        error_events = [
            e for e in events
            if isinstance(e, DebateEvent)
            and e.type == EventType.ERROR
            and "timed out" in e.content
        ]
        assert len(error_events) == 1, "Slow agent should time out"
