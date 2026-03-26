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
    DebateEvent,
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
    @pytest.mark.anyio
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


VALID_DEDUP_JSON = json.dumps(
    {
        "findings": [
            {
                "topic": "Use connection pooling",
                "description": "Agents agree on pooling",
                "agents": ["a1", "a2"],
                "severity": "important",
            }
        ],
        "stark_disagreements": [],
    }
)


def _make_orchestrator() -> Orchestrator:
    """Create an Orchestrator without calling __init__ (skips provider checks)."""
    config = make_config(num_agents=2)
    orch = Orchestrator.__new__(Orchestrator)
    orch.config = config
    orch._providers = {}
    orch._report = None
    return orch


class TestCallOrchestrator:
    @pytest.mark.anyio
    async def test_returns_text_and_usage(self):
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        msg = AssistantMessage(content=[TextBlock(text="hello world")], model="test")

        async def fake_query(**kwargs):
            yield msg

        orch = _make_orchestrator()
        with patch("agent_debate.orchestrator.query", side_effect=fake_query):
            text, usage = await orch._call_orchestrator("test prompt")
            assert text == "hello world"


class TestDedupRetry:
    @pytest.mark.anyio
    async def test_retry_on_empty_findings(self):
        """First call returns garbage, second returns valid JSON — findings come from retry."""
        orch = _make_orchestrator()
        responses = [
            AgentResponse(
                agent_id="a1", provider="claude", model="opus", round_number=1, content="resp1"
            ),
        ]

        call_count = 0

        async def fake_call_orchestrator(prompt, model=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "not json at all", None
            return VALID_DEDUP_JSON, None

        orch._call_orchestrator = fake_call_orchestrator  # type: ignore[assignment]

        findings, disagreements, raw = await orch._deduplicate_findings(
            "test", responses
        )
        assert call_count == 2
        assert len(findings) == 1
        assert findings[0].topic == "Use connection pooling"

    @pytest.mark.anyio
    async def test_double_failure_returns_empty(self):
        """Both calls return invalid JSON — returns empty, no crash."""
        orch = _make_orchestrator()
        responses = [
            AgentResponse(
                agent_id="a1", provider="claude", model="opus", round_number=1, content="resp1"
            ),
        ]

        async def fake_call_orchestrator(prompt, model=None):
            return "garbage", None

        orch._call_orchestrator = fake_call_orchestrator  # type: ignore[assignment]

        findings, disagreements, raw = await orch._deduplicate_findings(
            "test", responses
        )
        assert findings == []
        assert disagreements == []

    @pytest.mark.anyio
    async def test_no_retry_when_findings_present(self):
        """If first call succeeds, no retry happens."""
        orch = _make_orchestrator()
        responses = [
            AgentResponse(
                agent_id="a1", provider="claude", model="opus", round_number=1, content="resp1"
            ),
        ]

        call_count = 0

        async def fake_call_orchestrator(prompt, model=None):
            nonlocal call_count
            call_count += 1
            return VALID_DEDUP_JSON, None

        orch._call_orchestrator = fake_call_orchestrator  # type: ignore[assignment]

        findings, disagreements, raw = await orch._deduplicate_findings(
            "test", responses
        )
        assert call_count == 1
        assert len(findings) == 1


class TestOpeningCompleteEvent:
    def test_opening_complete_event_type_exists(self):
        """OPENING_COMPLETE should be a valid EventType."""
        from agent_debate.types import EventType

        assert EventType.OPENING_COMPLETE.value == "opening_complete"

    def test_opening_complete_event_carries_responses(self):
        """OPENING_COMPLETE event metadata should hold responses."""
        from agent_debate.types import AgentResponse, DebateEvent, EventType

        responses = [
            AgentResponse(agent_id="a1", provider="claude", model="opus", round_number=1, content="resp1"),
        ]
        event = DebateEvent(
            type=EventType.OPENING_COMPLETE,
            metadata={"responses": responses},
        )
        assert event.type == EventType.OPENING_COMPLETE
        assert len(event.metadata["responses"]) == 1
        assert event.metadata["responses"][0].agent_id == "a1"


class TestRunOpening:
    @pytest.mark.anyio
    async def test_yields_streaming_events_then_opening_complete(self):
        """run_opening() should yield agent streaming events, then OPENING_COMPLETE with responses."""
        config = make_config(num_agents=2)
        orch = Orchestrator.__new__(Orchestrator)
        orch.config = config
        orch._report = None
        orch._trace = None
        fake = FakeProvider(["Response from agent"])
        orch._providers = {"claude": fake}

        events = []
        async for event in orch.run_opening("test prompt"):
            events.append(event)

        event_types = [e.type for e in events if isinstance(e, DebateEvent)]
        assert EventType.ROUND_START in event_types
        assert EventType.AGENT_STARTED in event_types
        assert EventType.AGENT_COMPLETED in event_types
        assert event_types[-1] == EventType.OPENING_COMPLETE

        # OPENING_COMPLETE carries responses
        final = events[-1]
        assert final.type == EventType.OPENING_COMPLETE
        responses = final.metadata["responses"]
        assert len(responses) == 2
        assert all(isinstance(r, AgentResponse) for r in responses)

    @pytest.mark.anyio
    async def test_opening_complete_fires_even_with_agent_error(self):
        """If an agent errors (timeout), OPENING_COMPLETE still fires with the remaining responses."""
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
        orch._trace = None

        fast_provider = FakeProvider(["Fast response"])
        slow_provider = SlowProvider()

        async def patched_fan_out(prompt, round_number, span=None):
            """Use fast_provider for index 0, slow_provider for index 1."""
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
                            prompt=full_prompt, system_prompt="",
                            cwd=orch.config.cwd, model=pc.model,
                        ):
                            chunks.append(chunk)
                            await queue.put(DebateEvent(
                                type=EventType.AGENT_CHUNK, agent_id=agent_id,
                                round_number=round_number, content=chunk,
                            ))
                    await asyncio.wait_for(_stream(), timeout=orch.config.agent_timeout)
                    content = "".join(chunks)
                    response = AgentResponse(
                        agent_id=agent_id, provider=pc.provider,
                        model=pc.model, round_number=round_number, content=content,
                    )
                    await queue.put(DebateEvent(
                        type=EventType.AGENT_COMPLETED, agent_id=agent_id,
                        round_number=round_number,
                    ))
                    await queue.put(response)
                except asyncio.TimeoutError:
                    await queue.put(DebateEvent(
                        type=EventType.ERROR, agent_id=agent_id,
                        content=f"Agent timed out after {orch.config.agent_timeout}s",
                    ))
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

        orch._fan_out_streaming = patched_fan_out  # type: ignore[assignment]

        events = []
        async for event in orch.run_opening("test prompt"):
            events.append(event)

        event_types = [e.type for e in events if isinstance(e, DebateEvent)]
        assert event_types[-1] == EventType.OPENING_COMPLETE
        assert EventType.ERROR in event_types
        final = events[-1]
        responses = final.metadata["responses"]
        assert len(responses) == 1


class TestRunDebate:
    @pytest.mark.anyio
    async def test_runs_dedup_and_synthesis(self):
        """run_debate() should run dedup + synthesis given opening responses."""
        orch = _make_orchestrator()
        responses = [
            AgentResponse(agent_id="a1", provider="claude", model="opus", round_number=1, content="resp1"),
            AgentResponse(agent_id="a2", provider="claude", model="sonnet", round_number=1, content="resp2"),
        ]

        async def fake_call_orchestrator(prompt, model=None):
            if "deduplicate" in prompt.lower() or "findings" in prompt.lower():
                return VALID_DEDUP_JSON, None
            return "Final synthesis content", None

        orch._call_orchestrator = fake_call_orchestrator  # type: ignore[assignment]
        orch._trace = None

        events = []
        async for event in orch.run_debate("test prompt", responses):
            events.append(event)

        event_types = [e.type for e in events]
        assert EventType.DEDUP_START in event_types
        assert EventType.DEDUP_COMPLETE in event_types
        assert EventType.SYNTHESIS_START in event_types
        assert EventType.SYNTHESIS_COMPLETE in event_types

    @pytest.mark.anyio
    async def test_empty_responses_skips_to_synthesis(self):
        """run_debate() with empty responses should skip debate and run synthesis directly."""
        orch = _make_orchestrator()

        async def fake_call_orchestrator(prompt, model=None):
            if "deduplicate" in prompt.lower() or "findings" in prompt.lower():
                return VALID_DEDUP_JSON, None
            return "Synthesis from empty", None

        orch._call_orchestrator = fake_call_orchestrator  # type: ignore[assignment]
        orch._trace = None

        events = []
        async for event in orch.run_debate("test prompt", []):
            events.append(event)

        event_types = [e.type for e in events]
        assert EventType.SYNTHESIS_START in event_types
        assert EventType.SYNTHESIS_COMPLETE in event_types

    @pytest.mark.anyio
    async def test_single_response_skips_debate(self):
        """run_debate() with one response should skip targeted debate."""
        orch = _make_orchestrator()
        responses = [
            AgentResponse(agent_id="a1", provider="claude", model="opus", round_number=1, content="resp1"),
        ]

        async def fake_call_orchestrator(prompt, model=None):
            if "deduplicate" in prompt.lower() or "findings" in prompt.lower():
                return json.dumps({
                    "findings": [{"topic": "T", "description": "D", "agents": ["a1"], "severity": "important"}],
                    "stark_disagreements": [{"topic": "X", "positions": {"a1": "yes"}}],
                }), None
            return "Single agent synthesis", None

        orch._call_orchestrator = fake_call_orchestrator  # type: ignore[assignment]
        orch._trace = None

        events = []
        async for event in orch.run_debate("test prompt", responses):
            events.append(event)

        event_types = [e.type for e in events]
        assert EventType.TARGETED_DEBATE_START not in event_types
        assert EventType.SYNTHESIS_COMPLETE in event_types
