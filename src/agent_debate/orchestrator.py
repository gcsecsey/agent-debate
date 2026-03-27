"""Orchestrator — the core multi-perspective analysis loop."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)

from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk.types import AssistantMessage, TextBlock

from . import tracing
from .personas import auto_assign_personas, get_persona_instruction
from .prompts import (
    build_dedup_prompt,
    build_round1_prompt,
    build_synthesis_prompt,
    build_targeted_debate_prompt,
)
from .providers import get_provider
from .providers.base import BaseProvider
from .report import ReportWriter
from .types import (
    AgentResponse,
    DebateConfig,
    DebateEvent,
    Disagreement,
    EventType,
    Finding,
    ProviderConfig,
)


class Orchestrator:
    """Manages multi-perspective analysis: fan-out, dedup, optional debate, synthesis."""

    def __init__(self, config: DebateConfig) -> None:
        self.config = config
        self._providers: dict[str, BaseProvider] = {}
        self._report: ReportWriter | None = None
        self._semaphore = asyncio.Semaphore(config.max_parallel)
        self._trace: Any = None
        self._init_providers()

    def _init_providers(self) -> None:
        """Instantiate provider adapters, skipping unavailable ones."""
        unavailable: list[str] = []
        for pc in self.config.providers:
            if pc.provider not in self._providers:
                try:
                    provider_cls = get_provider(pc.provider)
                except ValueError:
                    unavailable.append(pc.agent_id)
                    continue
                provider = provider_cls()
                if not provider.available():
                    unavailable.append(pc.agent_id)
                    continue
                self._providers[pc.provider] = provider

        if unavailable:
            # Remove unavailable providers from config
            self.config.providers = [
                pc for pc in self.config.providers
                if pc.provider in self._providers
            ]
            logger.warning(
                "Skipping unavailable providers: %s", ", ".join(unavailable)
            )

        if not self._providers:
            raise RuntimeError(
                f"No providers available. Tried: {', '.join(unavailable)}. "
                "Install at least one provider CLI."
            )

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
        """Run round 1 independent analysis, yielding streaming events.

        Ends with an OPENING_COMPLETE event whose metadata["responses"]
        contains the list of AgentResponse objects from all agents that succeeded.
        """
        # Set up report writer
        if self.config.report_dir:
            self._report = ReportWriter(self.config.report_dir, self.config.cwd)
            self._report.start_run(
                prompt,
                self.config.providers,
                orchestrator_model=self.config.orchestrator_model,
                max_rounds=self.config.max_rounds,
                personas=self._resolve_personas(),
            )

        self._trace = tracing.start_trace(
            name="debate_run",
            metadata={
                "providers": [pc.agent_id for pc in self.config.providers],
                "orchestrator_model": self.config.orchestrator_model,
                "max_rounds": self.config.max_rounds,
                "cwd": self.config.cwd,
            },
        )

        yield DebateEvent(type=EventType.ROUND_START, round_number=1)
        round1_span = tracing.start_span(self._trace, "round_1")

        responses: list[AgentResponse] = []
        async for event in self._fan_out_streaming(
            prompt, round_number=1, span=round1_span
        ):
            if isinstance(event, AgentResponse):
                responses.append(event)
                if self._report:
                    self._report.save_agent_response(event)
            else:
                yield event

        tracing.end_span(round1_span)

        yield DebateEvent(
            type=EventType.OPENING_COMPLETE,
            metadata={"responses": responses},
        )

    async def run_debate(
        self, prompt: str, opening_responses: list[AgentResponse]
    ) -> AsyncIterator[DebateEvent]:
        """Run dedup, optional debate rounds, and synthesis.

        Accepts the responses from run_opening(). If opening_responses is empty
        or has only one agent, skips targeted debate and runs synthesis directly.
        """
        trace = self._trace or tracing.start_trace(
            name="debate_run_phase2",
            metadata={"phase": "debate"},
        )
        owns_trace = self._trace is None

        try:
            # Phase 2: Deduplicate findings
            yield DebateEvent(type=EventType.DEDUP_START)
            dedup_span = tracing.start_span(trace, "dedup")
            findings, stark_disagreements, dedup_raw = (
                await self._deduplicate_findings(prompt, opening_responses, span=dedup_span)
            )
            tracing.end_span(dedup_span)

            if not findings and not stark_disagreements:
                yield DebateEvent(
                    type=EventType.ERROR,
                    content="Dedup produced no findings — synthesis will work from raw agent responses",
                    metadata={"phase": "dedup"},
                )

            if self._report:
                self._report.save_dedup(dedup_raw, findings, stark_disagreements)

            yield DebateEvent(
                type=EventType.DEDUP_COMPLETE,
                metadata={
                    "findings_count": len(findings),
                    "disagreements_count": len(stark_disagreements),
                },
            )

            # Phase 3: Optional targeted debate
            debate_responses: list[AgentResponse] | None = None
            if (
                stark_disagreements
                and self.config.max_rounds > 0
                and len(opening_responses) > 1
            ):
                yield DebateEvent(type=EventType.TARGETED_DEBATE_START)
                debate_span = tracing.start_span(trace, "targeted_debate")

                debate_responses = []
                async for event in self._targeted_debate_streaming(
                    prompt, opening_responses, stark_disagreements, span=debate_span
                ):
                    if isinstance(event, AgentResponse):
                        debate_responses.append(event)
                        if self._report:
                            self._report.save_debate_response(event)
                    else:
                        yield event
                tracing.end_span(debate_span)

            # Phase 4: Synthesis
            yield DebateEvent(type=EventType.SYNTHESIS_START)
            synthesis_span = tracing.start_span(trace, "synthesis")
            synthesis = await self._synthesize(
                prompt,
                opening_responses,
                findings,
                stark_disagreements,
                debate_responses,
                span=synthesis_span,
            )
            tracing.end_span(synthesis_span)

            if self._report:
                self._report.save_synthesis(synthesis)
                self._report.finalize_readme(synthesis)
                self._report.write_json()

            yield DebateEvent(type=EventType.SYNTHESIS_COMPLETE, content=synthesis)
        finally:
            if owns_trace:
                tracing.end_trace(trace)

    async def run(self, prompt: str) -> AsyncIterator[DebateEvent]:
        """Run the full analysis loop, yielding events as they occur.

        Convenience method that chains run_opening() and run_debate().
        """
        try:
            responses: list[AgentResponse] = []
            async for event in self.run_opening(prompt):
                yield event
                if event.type == EventType.OPENING_COMPLETE:
                    responses = event.metadata["responses"]
            async for event in self.run_debate(prompt, responses):
                yield event
        finally:
            if self._trace:
                tracing.end_trace(self._trace)
                self._trace = None

    def _resolve_personas(self) -> list[str | None]:
        """Resolve personas for all providers, auto-assigning if none are explicit."""
        explicit = [pc.persona for pc in self.config.providers]
        if any(p is not None for p in explicit):
            return explicit
        return auto_assign_personas(len(self.config.providers))

    async def _fan_out_streaming(
        self,
        prompt: str,
        round_number: int,
        span: Any = None,
    ) -> AsyncIterator[DebateEvent | AgentResponse]:
        """Run all agents in parallel, yielding chunk and completion events."""
        queue: asyncio.Queue[DebateEvent | AgentResponse | None] = asyncio.Queue()
        agents = list(enumerate(self.config.providers))
        total = len(agents)
        personas = self._resolve_personas()

        async def run_agent(index: int, pc: ProviderConfig) -> None:
            async with self._semaphore:
                provider = self._providers[pc.provider]
                agent_id = self._agent_id(index, pc)
                full_prompt = build_round1_prompt(prompt)
                persona = personas[index]
                system_prompt = get_persona_instruction(persona) if persona else ""

                await queue.put(
                    DebateEvent(type=EventType.AGENT_STARTED, agent_id=agent_id)
                )

                try:
                    chunks: list[str] = []

                    async def _stream() -> None:
                        async for chunk in provider.analyze(
                            prompt=full_prompt,
                            system_prompt=system_prompt,
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

                    await asyncio.wait_for(
                        _stream(), timeout=self.config.agent_timeout
                    )

                    content = "".join(chunks)
                    response = AgentResponse(
                        agent_id=agent_id,
                        provider=pc.provider,
                        model=pc.model,
                        round_number=round_number,
                        content=content,
                    )
                    if span is not None:
                        tracing.log_generation(
                            span,
                            name=agent_id,
                            model=pc.model,
                            input=full_prompt,
                            output=content,
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
                            content=f"Agent timed out after {self.config.agent_timeout}s",
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

        for index, provider_config in agents:
            asyncio.create_task(run_agent(index, provider_config))

        completed = 0
        while completed < total:
            item = await queue.get()
            if item is None:
                completed += 1
                continue
            yield item

    async def _targeted_debate_streaming(
        self,
        prompt: str,
        prior_responses: list[AgentResponse],
        disagreements: list[Disagreement],
        span: Any = None,
    ) -> AsyncIterator[DebateEvent | AgentResponse]:
        """Run a single targeted debate round for stark disagreements."""
        queue: asyncio.Queue[DebateEvent | AgentResponse | None] = asyncio.Queue()
        agents = list(enumerate(self.config.providers))
        total = len(agents)
        response_by_id = {r.agent_id: r for r in prior_responses}

        personas = self._resolve_personas()

        async def run_debate_agent(index: int, pc: ProviderConfig) -> None:
            async with self._semaphore:
                provider = self._providers[pc.provider]
                agent_id = self._agent_id(index, pc)

                own_prior = response_by_id.get(agent_id)
                if own_prior is None:
                    await queue.put(None)
                    return

                # Build a combined prompt addressing all disagreements
                others = [r for r in prior_responses if r.agent_id != agent_id]
                full_prompt = build_targeted_debate_prompt(
                    user_prompt=prompt,
                    own_response=own_prior,
                    disagreements=disagreements,
                    other_responses=others,
                )
                persona = personas[index]
                system_prompt = get_persona_instruction(persona) if persona else ""

                await queue.put(
                    DebateEvent(type=EventType.AGENT_STARTED, agent_id=agent_id)
                )

                try:
                    chunks: list[str] = []

                    async def _stream() -> None:
                        async for chunk in provider.analyze(
                            prompt=full_prompt,
                            system_prompt=system_prompt,
                            cwd=self.config.cwd,
                            model=pc.model,
                        ):
                            chunks.append(chunk)
                            await queue.put(
                                DebateEvent(
                                    type=EventType.AGENT_CHUNK,
                                    agent_id=agent_id,
                                    round_number=2,
                                    content=chunk,
                                )
                            )

                    await asyncio.wait_for(
                        _stream(), timeout=self.config.agent_timeout
                    )

                    content = "".join(chunks)
                    response = AgentResponse(
                        agent_id=agent_id,
                        provider=pc.provider,
                        model=pc.model,
                        round_number=2,
                        content=content,
                    )
                    if span is not None:
                        tracing.log_generation(
                            span,
                            name=agent_id,
                            model=pc.model,
                            input=full_prompt,
                            output=content,
                        )
                    await queue.put(
                        DebateEvent(
                            type=EventType.AGENT_COMPLETED,
                            agent_id=agent_id,
                            round_number=2,
                        )
                    )
                    await queue.put(response)
                except asyncio.TimeoutError:
                    await queue.put(
                        DebateEvent(
                            type=EventType.ERROR,
                            agent_id=agent_id,
                            content=f"Agent timed out after {self.config.agent_timeout}s",
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

        for index, provider_config in agents:
            asyncio.create_task(run_debate_agent(index, provider_config))

        completed = 0
        while completed < total:
            item = await queue.get()
            if item is None:
                completed += 1
                continue
            yield item

    async def _call_orchestrator(
        self,
        prompt: str,
        model: str | None = None,
    ) -> tuple[str, dict[str, int] | None]:
        """Make a single-turn orchestrator call. Returns (text, usage_info)."""
        result_chunks: list[str] = []
        options = ClaudeAgentOptions(
            model=model or self.config.orchestrator_model,
            max_turns=1,
        )

        usage_info: dict[str, int] | None = None
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        result_chunks.append(block.text)
                if hasattr(message, "usage") and message.usage is not None:
                    u = message.usage
                    usage_info = {
                        "input_tokens": getattr(u, "input_tokens", 0),
                        "output_tokens": getattr(u, "output_tokens", 0),
                        "total_tokens": getattr(u, "input_tokens", 0)
                        + getattr(u, "output_tokens", 0),
                    }

        return "".join(result_chunks), usage_info

    async def _deduplicate_findings(
        self,
        prompt: str,
        responses: list[AgentResponse],
        span: Any = None,
    ) -> tuple[list[Finding], list[Disagreement], str]:
        """Use Claude to deduplicate findings and identify contradictions.

        Returns (findings, stark_disagreements, raw_reasoning).
        Retries once on parse failure.
        """
        detection_prompt = build_dedup_prompt(prompt, responses)

        raw = ""
        findings: list[Finding] = []
        disagreements: list[Disagreement] = []

        for attempt in range(2):
            raw, usage_info = await self._call_orchestrator(
                detection_prompt, model="haiku"
            )

            if span is not None:
                tracing.log_generation(
                    span,
                    name=f"dedup_call{'_retry' if attempt > 0 else ''}",
                    model="haiku",
                    input=detection_prompt,
                    output=raw,
                    usage=usage_info,
                )

            findings, disagreements = self._parse_dedup_response(raw)

            if findings or attempt == 1:
                break

            logger.warning(
                "Dedup returned empty findings (attempt %d), retrying",
                attempt + 1,
            )

        return findings, disagreements, raw

    @staticmethod
    def _extract_json_object(raw: str) -> str | None:
        """Extract the first JSON object from a possibly wrapped response."""
        fenced_match = re.search(
            r"```json\s*(\{.*?\})\s*```",
            raw,
            re.DOTALL | re.IGNORECASE,
        )
        if fenced_match:
            return fenced_match.group(1)

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            return json_match.group()

        return None

    @classmethod
    def _parse_dedup_response(
        cls, raw: str
    ) -> tuple[list[Finding], list[Disagreement]]:
        """Parse the dedup JSON response into findings and disagreements."""
        json_blob = cls._extract_json_object(raw)
        if json_blob is None:
            logger.warning("Dedup response contained no JSON object — returning empty findings")
            return [], []

        try:
            data = json.loads(json_blob)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse dedup JSON: %s", e)
            return [], []

        findings = []
        for item in data.get("findings", []):
            if isinstance(item, dict) and "topic" in item:
                findings.append(
                    Finding(
                        topic=item["topic"],
                        description=item.get("description", ""),
                        agents=item.get("agents", []),
                        severity=item.get("severity", "important"),
                    )
                )

        disagreements = []
        for item in data.get("stark_disagreements", []):
            if isinstance(item, dict) and "topic" in item:
                disagreements.append(
                    Disagreement(
                        topic=item["topic"],
                        positions=item.get("positions", {}),
                    )
                )

        return findings, disagreements

    async def _synthesize(
        self,
        prompt: str,
        responses: list[AgentResponse],
        findings: list[Finding],
        disagreements: list[Disagreement],
        debate_responses: list[AgentResponse] | None = None,
        span: Any = None,
    ) -> str:
        """Produce the final synthesis using Claude."""
        # Format findings for the synthesis prompt
        findings_lines = []
        for f in findings:
            agents = ", ".join(f.agents)
            findings_lines.append(
                f"- **[{f.severity.upper()}]** {f.topic} (flagged by: {agents})\n"
                f"  {f.description}"
            )
        findings_text = "\n\n".join(findings_lines) if findings_lines else "No findings extracted."

        synthesis_prompt = build_synthesis_prompt(
            user_prompt=prompt,
            responses=responses,
            findings_text=findings_text,
            disagreements=disagreements,
            debate_responses=debate_responses,
        )

        raw, usage_info = await self._call_orchestrator(synthesis_prompt)

        if span is not None:
            tracing.log_generation(
                span,
                name="synthesis_call",
                model=self.config.orchestrator_model,
                input=synthesis_prompt,
                output=raw,
                usage=usage_info,
            )
        return raw
