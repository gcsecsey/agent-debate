"""Orchestrator — the core debate loop."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator

from claude_agent_sdk import query, ClaudeAgentOptions
from claude_agent_sdk.types import AssistantMessage, TextBlock

from .prompts import (
    build_debate_prompt,
    build_disagreement_prompt,
    build_round1_prompt,
    build_synthesis_prompt,
    get_persona,
    get_persona_name,
)
from .providers import get_provider
from .providers.base import BaseProvider
from .types import (
    AgentResponse,
    DebateConfig,
    DebateEvent,
    Disagreement,
    EventType,
    ProviderConfig,
)


class Orchestrator:
    """Manages the multi-agent debate: fan-out, disagreement detection, debate rounds, synthesis."""

    def __init__(self, config: DebateConfig) -> None:
        self.config = config
        self._providers: dict[str, BaseProvider] = {}
        self._init_providers()

    def _init_providers(self) -> None:
        """Instantiate provider adapters, checking availability."""
        for pc in self.config.providers:
            if pc.provider not in self._providers:
                provider_cls = get_provider(pc.provider)
                provider = provider_cls()
                if not provider.available():
                    raise RuntimeError(
                        f"Provider '{pc.provider}' is not available. "
                        f"Is the CLI installed?"
                    )
                self._providers[pc.provider] = provider

    def _agent_id(self, index: int, pc: ProviderConfig) -> str:
        """Generate a unique agent ID, handling duplicates."""
        base = pc.agent_id
        all_ids = [p.agent_id for p in self.config.providers]
        if all_ids.count(base) > 1:
            occurrence = sum(
                1 for i, p in enumerate(self.config.providers[:index])
                if p.agent_id == base
            )
            return f"{base}#{occurrence + 1}"
        return base

    async def run(self, prompt: str) -> AsyncIterator[DebateEvent]:
        """Run the full debate loop, yielding events as they occur."""

        # Phase 1: Independent analysis (parallel fan-out with streaming)
        yield DebateEvent(type=EventType.ROUND_START, round_number=1)

        round1_responses: list[AgentResponse] = []
        async for event in self._fan_out_streaming(prompt, round_number=1):
            if isinstance(event, AgentResponse):
                round1_responses.append(event)
            else:
                yield event

        # Phase 2: Detect disagreements
        disagreements = await self._detect_disagreements(prompt, round1_responses)

        all_responses = [round1_responses]

        if not disagreements:
            yield DebateEvent(type=EventType.CONSENSUS_REACHED, round_number=1)
        else:
            for d in disagreements:
                yield DebateEvent(
                    type=EventType.DISAGREEMENT_FOUND,
                    content=d.topic,
                    metadata={"positions": d.positions},
                )

            # Phase 3: Adaptive debate rounds
            latest_responses = round1_responses
            round_num = 2

            while disagreements and round_num <= self.config.max_rounds:
                yield DebateEvent(
                    type=EventType.DEBATE_ROUND_START,
                    round_number=round_num,
                )

                latest_responses = []
                async for event in self._debate_round_streaming(
                    prompt, all_responses[-1], disagreements, round_num
                ):
                    if isinstance(event, AgentResponse):
                        latest_responses.append(event)
                    else:
                        yield event

                all_responses.append(latest_responses)

                new_disagreements = await self._detect_disagreements(
                    prompt, latest_responses, previous=disagreements
                )

                if self._converged(disagreements, new_disagreements):
                    yield DebateEvent(
                        type=EventType.CONSENSUS_REACHED,
                        round_number=round_num,
                    )
                    disagreements = new_disagreements
                    break

                disagreements = new_disagreements
                round_num += 1

        # Phase 4: Synthesis
        yield DebateEvent(type=EventType.SYNTHESIS_START)
        synthesis = await self._synthesize(prompt, all_responses, disagreements)
        yield DebateEvent(
            type=EventType.SYNTHESIS_COMPLETE,
            content=synthesis,
        )

    async def _fan_out_streaming(
        self, prompt: str, round_number: int
    ) -> AsyncIterator[DebateEvent | AgentResponse]:
        """Run all agents in parallel, yielding chunk and completion events."""
        queue: asyncio.Queue[DebateEvent | AgentResponse | None] = asyncio.Queue()
        agents = list(enumerate(self.config.providers))
        total = len(agents)

        async def run_agent(index: int, pc: ProviderConfig) -> None:
            provider = self._providers[pc.provider]
            agent_id = self._agent_id(index, pc)
            persona = get_persona(index, pc.persona)
            persona_name = get_persona_name(index)
            full_prompt = build_round1_prompt(prompt, persona)

            await queue.put(
                DebateEvent(type=EventType.AGENT_STARTED, agent_id=agent_id)
            )

            try:
                chunks: list[str] = []
                async for chunk in provider.analyze(
                    prompt=full_prompt,
                    system_prompt=persona,
                    cwd=self.config.cwd,
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

                response = AgentResponse(
                    agent_id=agent_id,
                    provider=pc.provider,
                    model=pc.model,
                    round_number=round_number,
                    content="".join(chunks),
                    persona=persona_name,
                )
                await queue.put(
                    DebateEvent(
                        type=EventType.AGENT_COMPLETED,
                        agent_id=agent_id,
                        round_number=round_number,
                    )
                )
                await queue.put(response)
            except Exception as e:
                await queue.put(
                    DebateEvent(
                        type=EventType.ERROR,
                        agent_id=agent_id,
                        content=str(e),
                    )
                )
            finally:
                await queue.put(None)

        for index, pc in agents:
            asyncio.create_task(run_agent(index, pc))

        completed = 0
        while completed < total:
            item = await queue.get()
            if item is None:
                completed += 1
                continue
            yield item

    async def _debate_round_streaming(
        self,
        prompt: str,
        prior_responses: list[AgentResponse],
        disagreements: list[Disagreement],
        round_number: int,
    ) -> AsyncIterator[DebateEvent | AgentResponse]:
        """Run a debate round, yielding chunk and completion events."""
        queue: asyncio.Queue[DebateEvent | AgentResponse | None] = asyncio.Queue()
        agents = list(enumerate(self.config.providers))
        total = len(agents)
        response_by_id = {r.agent_id: r for r in prior_responses}

        async def run_debate_agent(index: int, pc: ProviderConfig) -> None:
            provider = self._providers[pc.provider]
            agent_id = self._agent_id(index, pc)
            persona = get_persona(index, pc.persona)
            persona_name = get_persona_name(index)

            own_prior = response_by_id.get(agent_id)
            if own_prior is None:
                full_prompt = build_round1_prompt(prompt, persona)
            else:
                others = [r for r in prior_responses if r.agent_id != agent_id]
                full_prompt = build_debate_prompt(
                    user_prompt=prompt,
                    persona=persona,
                    own_prior=own_prior,
                    other_responses=others,
                    disagreements=disagreements,
                    round_number=round_number,
                )

            await queue.put(
                DebateEvent(type=EventType.AGENT_STARTED, agent_id=agent_id)
            )

            try:
                chunks: list[str] = []
                async for chunk in provider.analyze(
                    prompt=full_prompt,
                    system_prompt=persona,
                    cwd=self.config.cwd,
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

                response = AgentResponse(
                    agent_id=agent_id,
                    provider=pc.provider,
                    model=pc.model,
                    round_number=round_number,
                    content="".join(chunks),
                    persona=persona_name,
                )
                await queue.put(
                    DebateEvent(
                        type=EventType.AGENT_COMPLETED,
                        agent_id=agent_id,
                        round_number=round_number,
                    )
                )
                await queue.put(response)
            except Exception as e:
                await queue.put(
                    DebateEvent(
                        type=EventType.ERROR,
                        agent_id=agent_id,
                        content=str(e),
                    )
                )
            finally:
                await queue.put(None)

        for index, pc in agents:
            asyncio.create_task(run_debate_agent(index, pc))

        completed = 0
        while completed < total:
            item = await queue.get()
            if item is None:
                completed += 1
                continue
            yield item

    async def _detect_disagreements(
        self,
        prompt: str,
        responses: list[AgentResponse],
        previous: list[Disagreement] | None = None,
    ) -> list[Disagreement]:
        """Use Claude to identify disagreements between agent responses."""
        detection_prompt = build_disagreement_prompt(prompt, responses)

        result_chunks: list[str] = []
        options = ClaudeAgentOptions(
            model=self.config.orchestrator_model,
            max_turns=1,
        )

        async for message in query(prompt=detection_prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        result_chunks.append(block.text)

        raw = "".join(result_chunks)
        return self._parse_disagreements(raw)

    @staticmethod
    def _parse_disagreements(raw: str) -> list[Disagreement]:
        """Parse JSON disagreements from the orchestrator's response."""
        json_match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not json_match:
            return []

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            return []

        disagreements = []
        for item in data:
            if isinstance(item, dict) and "topic" in item:
                disagreements.append(
                    Disagreement(
                        topic=item["topic"],
                        positions=item.get("positions", {}),
                        questions=item.get("questions", []),
                    )
                )
        return disagreements

    @staticmethod
    def _converged(
        old: list[Disagreement], new: list[Disagreement]
    ) -> bool:
        """Check if disagreements have converged (resolved or deadlocked)."""
        if not new:
            return True

        old_topics = {d.topic for d in old}
        new_topics = {d.topic for d in new}

        if old_topics == new_topics:
            old_positions = {
                d.topic: frozenset(d.positions.values()) for d in old
            }
            new_positions = {
                d.topic: frozenset(d.positions.values()) for d in new
            }
            if old_positions == new_positions:
                return True

        return len(new) < len(old)

    async def _synthesize(
        self,
        prompt: str,
        all_responses: list[list[AgentResponse]],
        disagreements: list[Disagreement],
    ) -> str:
        """Produce the final synthesis using Claude."""
        synthesis_prompt = build_synthesis_prompt(
            prompt, all_responses, disagreements
        )

        result_chunks: list[str] = []
        options = ClaudeAgentOptions(
            model=self.config.orchestrator_model,
            max_turns=1,
        )

        async for message in query(prompt=synthesis_prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        result_chunks.append(block.text)

        return "".join(result_chunks)
