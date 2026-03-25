"""Orchestrator — the core debate loop."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator

from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk.types import AssistantMessage, TextBlock

from .prompts import (
    build_deadlock_resolution_prompt,
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
    PositionUpdate,
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
                1
                for i, p in enumerate(self.config.providers[:index])
                if p.agent_id == base
            )
            return f"{base}#{occurrence + 1}"
        return base

    async def run_opening(self, prompt: str) -> AsyncIterator[DebateEvent]:
        """Run the opening arguments phase: fan out to all agents, yield events.

        Ends with an OPENING_COMPLETE event whose metadata["responses"]
        contains the list of AgentResponse objects.
        """
        yield DebateEvent(type=EventType.ROUND_START, round_number=1)

        responses: list[AgentResponse] = []
        async for event in self._fan_out_streaming(prompt, round_number=1):
            if isinstance(event, AgentResponse):
                responses.append(event)
            else:
                yield event

        yield DebateEvent(
            type=EventType.OPENING_COMPLETE,
            round_number=1,
            metadata={"responses": responses},
        )

    async def run_debate(
        self,
        prompt: str,
        opening_responses: list[AgentResponse],
    ) -> AsyncIterator[DebateEvent]:
        """Run the debate phase: disagreement detection, debate rounds, synthesis.

        Accepts the responses from run_opening(). If opening_responses is empty
        or has only one agent, skips debate and runs synthesis directly.
        """
        judge_resolution: str | None = None
        disagreements: list[Disagreement] = []

        if len(opening_responses) >= 2:
            disagreements = await self._detect_disagreements(prompt, opening_responses)
            all_responses = [opening_responses]

            if not disagreements:
                yield DebateEvent(type=EventType.CONSENSUS_REACHED, round_number=1)
            else:
                for disagreement in disagreements:
                    yield DebateEvent(
                        type=EventType.DISAGREEMENT_FOUND,
                        content=disagreement.topic,
                        metadata={"positions": disagreement.positions},
                    )

                round_num = 2
                while disagreements and round_num <= self.config.max_rounds:
                    yield DebateEvent(
                        type=EventType.DEBATE_ROUND_START,
                        round_number=round_num,
                    )

                    latest_responses: list[AgentResponse] = []
                    async for event in self._debate_round_streaming(
                        prompt,
                        all_responses[-1],
                        disagreements,
                        round_num,
                    ):
                        if isinstance(event, AgentResponse):
                            latest_responses.append(event)
                        else:
                            yield event

                    all_responses.append(latest_responses)

                    new_disagreements = await self._detect_disagreements(
                        prompt,
                        latest_responses,
                        previous=disagreements,
                    )

                    round_state = self._classify_round(
                        disagreements,
                        new_disagreements,
                        latest_responses,
                    )

                    if round_state == "consensus":
                        yield DebateEvent(
                            type=EventType.CONSENSUS_REACHED,
                            round_number=round_num,
                        )
                        disagreements = new_disagreements
                        break

                    if round_state == "deadlock":
                        disagreements = new_disagreements
                        judge_resolution = await self._resolve_deadlock(
                            prompt,
                            all_responses,
                            disagreements,
                        )
                        yield DebateEvent(
                            type=EventType.DEADLOCK_RESOLVED,
                            round_number=round_num,
                            content=judge_resolution,
                        )
                        break

                    disagreements = new_disagreements
                    round_num += 1

                if disagreements and judge_resolution is None:
                    judge_resolution = await self._resolve_deadlock(
                        prompt,
                        all_responses,
                        disagreements,
                    )
                    yield DebateEvent(
                        type=EventType.DEADLOCK_RESOLVED,
                        round_number=max(1, len(all_responses)),
                        content=judge_resolution,
                    )
        else:
            all_responses = [opening_responses] if opening_responses else [[]]

        yield DebateEvent(type=EventType.SYNTHESIS_START)
        synthesis = await self._synthesize(
            prompt,
            all_responses,
            disagreements,
            judge_resolution,
        )
        yield DebateEvent(type=EventType.SYNTHESIS_COMPLETE, content=synthesis)

    async def run(self, prompt: str) -> AsyncIterator[DebateEvent]:
        """Run the full debate loop, yielding events as they occur."""
        judge_resolution: str | None = None

        yield DebateEvent(type=EventType.ROUND_START, round_number=1)

        round1_responses: list[AgentResponse] = []
        async for event in self._fan_out_streaming(prompt, round_number=1):
            if isinstance(event, AgentResponse):
                round1_responses.append(event)
            else:
                yield event

        disagreements = await self._detect_disagreements(prompt, round1_responses)
        all_responses = [round1_responses]

        if not disagreements:
            yield DebateEvent(type=EventType.CONSENSUS_REACHED, round_number=1)
        else:
            for disagreement in disagreements:
                yield DebateEvent(
                    type=EventType.DISAGREEMENT_FOUND,
                    content=disagreement.topic,
                    metadata={"positions": disagreement.positions},
                )

            round_num = 2
            while disagreements and round_num <= self.config.max_rounds:
                yield DebateEvent(
                    type=EventType.DEBATE_ROUND_START,
                    round_number=round_num,
                )

                latest_responses: list[AgentResponse] = []
                async for event in self._debate_round_streaming(
                    prompt,
                    all_responses[-1],
                    disagreements,
                    round_num,
                ):
                    if isinstance(event, AgentResponse):
                        latest_responses.append(event)
                    else:
                        yield event

                all_responses.append(latest_responses)

                new_disagreements = await self._detect_disagreements(
                    prompt,
                    latest_responses,
                    previous=disagreements,
                )

                round_state = self._classify_round(
                    disagreements,
                    new_disagreements,
                    latest_responses,
                )

                if round_state == "consensus":
                    yield DebateEvent(
                        type=EventType.CONSENSUS_REACHED,
                        round_number=round_num,
                    )
                    disagreements = new_disagreements
                    break

                if round_state == "deadlock":
                    disagreements = new_disagreements
                    judge_resolution = await self._resolve_deadlock(
                        prompt,
                        all_responses,
                        disagreements,
                    )
                    yield DebateEvent(
                        type=EventType.DEADLOCK_RESOLVED,
                        round_number=round_num,
                        content=judge_resolution,
                    )
                    break

                disagreements = new_disagreements
                round_num += 1

            if disagreements and judge_resolution is None:
                judge_resolution = await self._resolve_deadlock(
                    prompt,
                    all_responses,
                    disagreements,
                )
                yield DebateEvent(
                    type=EventType.DEADLOCK_RESOLVED,
                    round_number=max(1, len(all_responses)),
                    content=judge_resolution,
                )

        yield DebateEvent(type=EventType.SYNTHESIS_START)
        synthesis = await self._synthesize(
            prompt,
            all_responses,
            disagreements,
            judge_resolution,
        )
        yield DebateEvent(type=EventType.SYNTHESIS_COMPLETE, content=synthesis)

    async def _fan_out_streaming(
        self,
        prompt: str,
        round_number: int,
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

        for index, provider_config in agents:
            asyncio.create_task(run_agent(index, provider_config))

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
        response_by_id = {response.agent_id: response for response in prior_responses}

        async def run_debate_agent(index: int, pc: ProviderConfig) -> None:
            provider = self._providers[pc.provider]
            agent_id = self._agent_id(index, pc)
            persona = get_persona(index, pc.persona)
            persona_name = get_persona_name(index)

            own_prior = response_by_id.get(agent_id)
            if own_prior is None:
                full_prompt = build_round1_prompt(prompt, persona)
            else:
                others = [
                    response
                    for response in prior_responses
                    if response.agent_id != agent_id
                ]
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

                raw_content = "".join(chunks)
                content, position_updates = self._extract_position_updates(raw_content)
                response = AgentResponse(
                    agent_id=agent_id,
                    provider=pc.provider,
                    model=pc.model,
                    round_number=round_number,
                    content=content,
                    persona=persona_name,
                    position_updates=position_updates,
                )
                await queue.put(
                    DebateEvent(
                        type=EventType.AGENT_COMPLETED,
                        agent_id=agent_id,
                        round_number=round_number,
                    )
                )
                await queue.put(response)
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

        for index, provider_config in agents:
            asyncio.create_task(run_debate_agent(index, provider_config))

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
    def _extract_json_array(raw: str) -> str | None:
        """Extract the first JSON array from a possibly wrapped response."""
        fenced_match = re.search(
            r"```json\s*(\[.*?\])\s*```",
            raw,
            re.DOTALL | re.IGNORECASE,
        )
        if fenced_match:
            return fenced_match.group(1)

        json_match = re.search(r"\[.*\]", raw, re.DOTALL)
        if json_match:
            return json_match.group()

        return None

    @staticmethod
    def _parse_disagreements(raw: str) -> list[Disagreement]:
        """Parse JSON disagreements from the orchestrator's response."""
        json_blob = Orchestrator._extract_json_array(raw)
        if json_blob is None:
            return []

        try:
            data = json.loads(json_blob)
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
    def _parse_position_updates(raw: str) -> list[PositionUpdate]:
        """Parse structured position updates from agent output."""
        json_blob = Orchestrator._extract_json_array(raw)
        if json_blob is None:
            return []

        try:
            data = json.loads(json_blob)
        except json.JSONDecodeError:
            return []

        updates = []
        for item in data:
            if not isinstance(item, dict):
                continue
            topic = item.get("topic")
            previous_position = item.get("previous_position")
            next_position = item.get("next_position")
            change_type = item.get("change_type")
            if not all(
                isinstance(value, str) and value
                for value in [
                    topic,
                    previous_position,
                    next_position,
                    change_type,
                ]
            ):
                continue
            updates.append(
                PositionUpdate(
                    topic=topic,
                    previous_position=previous_position,
                    next_position=next_position,
                    change_type=change_type,
                    convincing_argument=str(item.get("convincing_argument", "")),
                    confidence=str(item.get("confidence", "medium")),
                    remaining_concern=str(item.get("remaining_concern", "")),
                )
            )
        return updates

    @classmethod
    def _extract_position_updates(
        cls,
        raw_content: str,
    ) -> tuple[str, list[PositionUpdate]]:
        """Separate a debate response from its structured position updates."""
        section_match = re.search(
            r"\n### Structured Position Updates\s*\n\s*```json\s*(\[.*?\])\s*```",
            raw_content,
            re.DOTALL | re.IGNORECASE,
        )
        if section_match:
            updates = cls._parse_position_updates(section_match.group(1))
            if updates:
                cleaned = (
                    raw_content[: section_match.start()]
                    + raw_content[section_match.end() :]
                ).strip()
                return cleaned, updates

        return raw_content, cls._parse_position_updates(raw_content)

    @staticmethod
    def _positions_changed(
        old: list[Disagreement],
        new: list[Disagreement],
    ) -> bool:
        """Check whether the judge's summarized positions materially changed."""
        old_positions = {
            disagreement.topic: frozenset(disagreement.positions.items())
            for disagreement in old
        }
        new_positions = {
            disagreement.topic: frozenset(disagreement.positions.items())
            for disagreement in new
        }
        return old_positions != new_positions

    @classmethod
    def _classify_round(
        cls,
        old: list[Disagreement],
        new: list[Disagreement],
        responses: list[AgentResponse],
    ) -> str:
        """Classify the debate state after a round."""
        if not new:
            return "consensus"

        old_topics = {disagreement.topic for disagreement in old}
        new_topics = {disagreement.topic for disagreement in new}

        if len(new) < len(old):
            return "progress"

        if cls._positions_changed(old, new):
            return "progress"

        if any(response.has_position_shift for response in responses):
            return "progress"

        if old_topics == new_topics:
            return "deadlock"

        return "progress"

    async def _resolve_deadlock(
        self,
        prompt: str,
        all_responses: list[list[AgentResponse]],
        disagreements: list[Disagreement],
    ) -> str:
        """Use the judge model to resolve an unresolved debate deadlock."""
        resolution_prompt = build_deadlock_resolution_prompt(
            prompt,
            all_responses,
            disagreements,
        )

        result_chunks: list[str] = []
        options = ClaudeAgentOptions(
            model=self.config.orchestrator_model,
            max_turns=1,
        )

        async for message in query(prompt=resolution_prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        result_chunks.append(block.text)

        return "".join(result_chunks)

    async def _synthesize(
        self,
        prompt: str,
        all_responses: list[list[AgentResponse]],
        disagreements: list[Disagreement],
        deadlock_resolution: str | None,
    ) -> str:
        """Produce the final synthesis using Claude."""
        synthesis_prompt = build_synthesis_prompt(
            prompt,
            all_responses,
            disagreements,
            deadlock_resolution,
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
