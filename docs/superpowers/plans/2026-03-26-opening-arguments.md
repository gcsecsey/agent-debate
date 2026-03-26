# Opening Arguments Phase — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the orchestrator's `run()` into two phases (`run_opening` / `run_debate`) so the human can inspect opening arguments before deciding whether to proceed with debate rounds.

**Architecture:** Add one new event type (`OPENING_COMPLETE`) and split the monolithic `run()` generator into two public methods. The CLI stops its Rich live display after the opening phase, prompts the user with `click.confirm()`, then optionally starts a fresh live display for the debate phase. The existing `run()` method chains both phases for backward compatibility.

**Tech Stack:** Python 3.12, asyncio, Click, Rich, pytest

**Spec:** `docs/superpowers/specs/2026-03-25-opening-arguments-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/agent_debate/types.py:9-21` | Add `OPENING_COMPLETE` to `EventType` enum |
| Modify | `src/agent_debate/orchestrator.py:73-171` | Split `run()` into `run_opening()`, `run_debate()`, rewrite `run()` as chain |
| Modify | `src/agent_debate/cli.py:102-199` | Two-phase live display with `click.confirm()` checkpoint |
| Modify | `src/agent_debate/cli.py:210-279` | Add `--opening-only` flag to Click command |
| Modify | `plugin/debate/commands/run.md` | Add `--opening-only` flag usage and checkpoint language |
| Modify | `tests/test_orchestrator.py` | New tests for `run_opening()`, `run_debate()`, backward compat |

---

### Task 1: Add `OPENING_COMPLETE` event type

**Files:**
- Modify: `src/agent_debate/types.py:9-21`

- [ ] **Step 1: Write the failing test**

In `tests/test_orchestrator.py`, add a test that imports and uses `OPENING_COMPLETE`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_orchestrator.py::TestOpeningCompleteEvent -v`
Expected: `AttributeError: OPENING_COMPLETE` — the enum member doesn't exist yet.

- [ ] **Step 3: Add `OPENING_COMPLETE` to `EventType`**

In `src/agent_debate/types.py`, add after line 15 (`AGENT_COMPLETED`):

```python
    OPENING_COMPLETE = "opening_complete"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_orchestrator.py::TestOpeningCompleteEvent -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_debate/types.py tests/test_orchestrator.py
git commit -m "feat: add OPENING_COMPLETE event type"
```

---

### Task 2: Implement `run_opening()` on Orchestrator

**Files:**
- Modify: `src/agent_debate/orchestrator.py:73-106`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Add `DebateEvent` to top-level imports in test file**

In `tests/test_orchestrator.py`, add `DebateEvent` to the existing import block (line 14-21):

```python
from agent_debate.types import (
    AgentResponse,
    DebateConfig,
    DebateEvent,
    Disagreement,
    EventType,
    Finding,
    ProviderConfig,
)
```

- [ ] **Step 2: Write the failing test**

Add to `tests/test_orchestrator.py`:

```python
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

        # Use two different provider types: one that returns immediately, one that hangs
        fast_provider = FakeProvider(["Fast response"])
        slow_provider = SlowProvider()

        # Patch _fan_out_streaming to use different providers per index
        original_fan_out = orch._fan_out_streaming

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
        # Must end with OPENING_COMPLETE even though one agent timed out
        assert event_types[-1] == EventType.OPENING_COMPLETE
        # Should have an ERROR event for the timed-out agent
        assert EventType.ERROR in event_types
        # OPENING_COMPLETE should carry only 1 response (the fast agent)
        final = events[-1]
        responses = final.metadata["responses"]
        assert len(responses) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py::TestRunOpening -v`
Expected: `AttributeError: 'Orchestrator' object has no attribute 'run_opening'`

- [ ] **Step 3: Implement `run_opening()`**

In `src/agent_debate/orchestrator.py`, add before `run()` (at line 73):

```python
    async def run_opening(self, prompt: str) -> AsyncIterator[DebateEvent]:
        """Run round 1 independent analysis, yielding streaming events.

        Ends with an OPENING_COMPLETE event whose metadata["responses"]
        contains the list of AgentResponse objects from all agents that succeeded.
        """
        # Set up report writer
        if self.config.report_dir:
            self._report = ReportWriter(self.config.report_dir, self.config.cwd)
            self._report.start_run(prompt, self.config.providers)

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
```

Note: Store `self._trace` as an instance attribute so `run_debate()` can continue the same trace. Initialize `self._trace = None` in `__init__`.

In `__init__` (line 44), add:

```python
        self._trace: Any = None
```

And add the `Any` import if not already present (it is — line 10).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_orchestrator.py::TestRunOpening -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_debate/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: implement run_opening() on Orchestrator"
```

---

### Task 3: Implement `run_debate()` on Orchestrator

**Files:**
- Modify: `src/agent_debate/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py`:

```python
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
        # Should still attempt synthesis
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
            # Return disagreements to verify debate is still skipped with 1 agent
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py::TestRunDebate -v`
Expected: `AttributeError: 'Orchestrator' object has no attribute 'run_debate'`

- [ ] **Step 3: Implement `run_debate()`**

In `src/agent_debate/orchestrator.py`, add after `run_opening()`:

```python
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

            yield DebateEvent(type=EventType.SYNTHESIS_COMPLETE, content=synthesis)
        finally:
            if owns_trace:
                tracing.end_trace(trace)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_orchestrator.py::TestRunDebate -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_debate/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: implement run_debate() on Orchestrator"
```

---

### Task 4: Rewrite `run()` as a chain of `run_opening()` + `run_debate()`

**Files:**
- Modify: `src/agent_debate/orchestrator.py:73-171`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py`:

```python
class TestRunBackwardCompat:
    @pytest.mark.anyio
    async def test_run_chains_opening_and_debate(self):
        """run() should yield all events from both phases, including OPENING_COMPLETE."""
        config = make_config(num_agents=2)
        orch = Orchestrator.__new__(Orchestrator)
        orch.config = config
        orch._report = None
        orch._trace = None
        fake = FakeProvider(["Agent response content"])
        orch._providers = {"claude": fake}

        async def fake_call_orchestrator(prompt, model=None):
            if "deduplicate" in prompt.lower() or "findings" in prompt.lower():
                return VALID_DEDUP_JSON, None
            return "Final synthesis", None

        orch._call_orchestrator = fake_call_orchestrator  # type: ignore[assignment]

        events = []
        async for event in orch.run("test prompt"):
            events.append(event)

        event_types = [e.type for e in events if isinstance(e, DebateEvent)]

        # Should contain events from both phases
        assert EventType.ROUND_START in event_types
        assert EventType.OPENING_COMPLETE in event_types
        assert EventType.DEDUP_START in event_types
        assert EventType.SYNTHESIS_COMPLETE in event_types
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_orchestrator.py::TestRunBackwardCompat -v`
Expected: FAIL — current `run()` doesn't yield `OPENING_COMPLETE`.

- [ ] **Step 3: Rewrite `run()` to chain both phases**

Replace the entire `run()` method body in `src/agent_debate/orchestrator.py` with:

```python
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
```

- [ ] **Step 4: Run ALL tests to verify backward compatibility**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS — existing tests still work, new test passes.

- [ ] **Step 5: Commit**

```bash
git add src/agent_debate/orchestrator.py tests/test_orchestrator.py
git commit -m "refactor: rewrite run() as chain of run_opening + run_debate"
```

---

### Task 5: Update CLI for two-phase display with checkpoint

**Files:**
- Modify: `src/agent_debate/cli.py:102-199` (the `_run` function)
- Modify: `src/agent_debate/cli.py:210-279` (the Click command)

- [ ] **Step 1: Add `--opening-only` flag to Click command**

In `src/agent_debate/cli.py`, add a new option to the `run` command (after the `--no-report` option, around line 252):

```python
@click.option(
    "--opening-only",
    is_flag=True,
    default=False,
    help="Run only the opening arguments phase (skip debate)",
)
```

Update the `run()` function signature to accept `opening_only: bool` and pass it to `_run()`:

```python
def run(
    prompt: str,
    providers: str,
    max_rounds: int,
    cwd: str,
    orchestrator_model: str,
    timeout: int,
    no_report: bool,
    opening_only: bool,
) -> None:
```

Update the `anyio.run` call to pass the new parameter:

```python
    anyio.run(
        _run, prompt, providers, max_rounds, cwd, orchestrator_model, report_dir, timeout, opening_only
    )
```

- [ ] **Step 2: Update `_run()` signature**

Add `opening_only: bool = False` parameter to `_run()`:

```python
async def _run(
    prompt: str,
    providers: str,
    max_rounds: int,
    cwd: str,
    orchestrator_model: str,
    report_dir: str | None,
    agent_timeout: int = 300,
    opening_only: bool = False,
) -> None:
```

- [ ] **Step 3: Rewrite `_run()` for two-phase flow**

Replace the event loop in `_run()` (lines 131-199) with:

```python
    orchestrator = Orchestrator(config)
    display = LiveDebateDisplay()

    console.print(
        Panel(
            f"[bold]Prompt:[/bold] {prompt}\n"
            f"[bold]Agents:[/bold] {', '.join(c.agent_id for c in config.providers)}\n"
            f"[bold]Max debate rounds:[/bold] {max_rounds}",
            title="[bold]Multi-Perspective Analysis[/bold]",
            border_style="bright_blue",
        )
    )

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
                    display.add_static(
                        Panel(
                            f"[bold red]{event.content}[/bold red]",
                            title=f"Error ({event.agent_id or 'unknown'})",
                            border_style="red",
                        )
                    )

    # Checkpoint: ask user whether to proceed
    if opening_only:
        console.print("\n[dim]Opening-only mode — debate skipped.[/dim]")
        _print_report_path(report_dir, orchestrator)
        return

    if not opening_responses:
        console.print("\n[bold red]No agents responded — nothing to debate.[/bold red]")
        _print_report_path(report_dir, orchestrator)
        return

    proceed = click.confirm("\nProceed with debate?", default=True)
    if not proceed:
        console.print("[dim]Debate skipped.[/dim]")
        _print_report_path(report_dir, orchestrator)
        return

    # Phase 2: Debate + synthesis
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
                    display2.add_static(
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
                    display2.add_static(
                        Panel("[bold]Synthesizing results...[/bold]", style="magenta")
                    )
                case EventType.SYNTHESIS_COMPLETE:
                    display2.add_static(
                        Panel(
                            Markdown(event.content),
                            title="[bold magenta]Final Synthesis[/bold magenta]",
                            border_style="magenta",
                        )
                    )
                case EventType.ERROR:
                    display2.add_static(
                        Panel(
                            f"[bold red]{event.content}[/bold red]",
                            title=f"Error ({event.agent_id or 'unknown'})",
                            border_style="red",
                        )
                    )

    _print_report_path(report_dir, orchestrator)
```

- [ ] **Step 4: Extract `_print_report_path` helper**

Add this small helper at module level (before `_run`):

```python
def _print_report_path(report_dir: str | None, orchestrator: Orchestrator) -> None:
    if report_dir and orchestrator._report:
        console.print(
            f"\n[dim]Full report saved to: {orchestrator._report.run_dir}[/dim]"
        )
```

- [ ] **Step 5: Add `AgentResponse` import awareness**

The `_run` function already imports `AgentResponse` via `from .types import AgentResponse, EventType` at line 15. No change needed.

- [ ] **Step 6: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 7: Manual smoke test**

Run: `agent-debate run "What is 2+2?" --providers fast --opening-only --no-report`
Expected: Shows opening arguments, prints "Opening-only mode", exits without debate.

Run: `agent-debate run "What is 2+2?" --providers fast --no-report`
Expected: Shows opening arguments, prompts "Proceed with debate? [Y/n]", typing `n` skips debate.

- [ ] **Step 8: Commit**

```bash
git add src/agent_debate/cli.py
git commit -m "feat: two-phase CLI with checkpoint and --opening-only flag"
```

---

### Task 6: Update plugin command

**Files:**
- Modify: `plugin/debate/commands/run.md`

The plugin runs `agent-debate` as a subprocess. Since it can't resume a process mid-run, the plugin uses the interactive CLI checkpoint (the `click.confirm` prompt built into Task 5). When running in a terminal context, the CLI handles the checkpoint natively. For non-interactive contexts (like Claude Code plugin), we use `--opening-only` for the first pass and the full command if the user wants to proceed.

- [ ] **Step 1: Add `--opening-only` to argument parsing**

In `plugin/debate/commands/run.md`, update the argument parsing section (around line 17-21) to include:

```markdown
- `--opening-only` (optional) — run only the opening arguments phase, default: false
```

- [ ] **Step 2: Update package mode to use two-step flow**

Replace the Step 2A section with a two-step approach that presents opening arguments first:

```markdown
### Step 2A: Package Mode

Run the opening arguments phase first using `--opening-only`:

\`\`\`bash
agent-debate run "<prompt>" --providers "<providers>" --max-rounds <max_rounds> --cwd "$(pwd)" --opening-only
\`\`\`

Present the opening arguments output to the user and ask:

> "Here are the opening arguments from all agents. Would you like me to proceed with the debate (agents will cross-examine each other's findings), or are these responses sufficient?"

If the user wants to proceed, run the full analysis (agents will re-run — this is the trade-off for subprocess-based plugin mode):

\`\`\`bash
agent-debate run "<prompt>" --providers "<providers>" --max-rounds <max_rounds> --cwd "$(pwd)"
\`\`\`

Read the output and present it to the user. Done.
```

Note: In plugin mode, agents run twice if the user proceeds to debate. This is a known trade-off of subprocess-based invocation. The token cost is acceptable because the common case is that users skip the debate after seeing opening arguments (that's the whole point of this feature).

- [ ] **Step 3: Commit**

```bash
git add plugin/debate/commands/run.md
git commit -m "feat: update plugin command with opening-only checkpoint"
```

---

### Task 7: Final integration test

**Files:**
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write integration test for full two-phase flow**

```python
class TestTwoPhaseIntegration:
    @pytest.mark.anyio
    async def test_opening_then_debate_produces_same_result_as_run(self):
        """Calling run_opening() then run_debate() should produce the same events as run()."""
        config = make_config(num_agents=2)

        def make_orch():
            orch = Orchestrator.__new__(Orchestrator)
            orch.config = config
            orch._report = None
            orch._trace = None
            fake = FakeProvider(["Agent response"])
            orch._providers = {"claude": fake}

            async def fake_call(prompt, model=None):
                if "deduplicate" in prompt.lower() or "findings" in prompt.lower():
                    return VALID_DEDUP_JSON, None
                return "Synthesis", None

            orch._call_orchestrator = fake_call  # type: ignore[assignment]
            return orch

        # Collect events from run()
        orch1 = make_orch()
        run_events = []
        async for event in orch1.run("test"):
            if isinstance(event, DebateEvent):
                run_events.append(event.type)

        # Collect events from run_opening() + run_debate()
        orch2 = make_orch()
        split_events = []
        responses = []
        async for event in orch2.run_opening("test"):
            if isinstance(event, DebateEvent):
                split_events.append(event.type)
            if isinstance(event, DebateEvent) and event.type == EventType.OPENING_COMPLETE:
                responses = event.metadata["responses"]
        async for event in orch2.run_debate("test", responses):
            if isinstance(event, DebateEvent):
                split_events.append(event.type)

        assert run_events == split_events
```

- [ ] **Step 2: Run the integration test**

Run: `python -m pytest tests/test_orchestrator.py::TestTwoPhaseIntegration -v`
Expected: PASS

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_orchestrator.py
git commit -m "test: add two-phase integration test"
```
