# Opening Arguments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the orchestrator's `run()` into `run_opening()` + `run_debate()` with a human checkpoint between phases.

**Architecture:** Extract the round-1 fan-out into `run_opening()` which yields streaming events and ends with `OPENING_COMPLETE`. Extract the disagreement-detection-through-synthesis logic into `run_debate()`. Rewrite `run()` as a thin wrapper chaining both. Add a `click.confirm()` checkpoint in the CLI between phases.

**Tech Stack:** Python 3.10+, anyio, click, rich

---

### File Map

- Modify: `src/agent_debate/types.py` — add `OPENING_COMPLETE` to `EventType`
- Modify: `src/agent_debate/orchestrator.py` — split `run()` into `run_opening()` + `run_debate()` + `run()`
- Modify: `src/agent_debate/cli.py` — two-phase display with checkpoint prompt
- Modify: `plugin/debate/commands/run.md` — add checkpoint between Phase 2 and Phase 3
- Modify: `tests/test_orchestrator.py` — add tests for `run_opening()`, `run_debate()`, backward compat

---

### Task 1: Add OPENING_COMPLETE event type

**Files:**
- Modify: `src/agent_debate/types.py:9-22`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_orchestrator.py`, add at the top of the file (after existing imports):

```python
class TestEventTypes:
    def test_opening_complete_exists(self):
        assert EventType.OPENING_COMPLETE.value == "opening_complete"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_orchestrator.py::TestEventTypes -v`
Expected: FAIL with `AttributeError: OPENING_COMPLETE`

- [ ] **Step 3: Add OPENING_COMPLETE to EventType**

In `src/agent_debate/types.py`, add after `AGENT_COMPLETED = "agent_completed"` (line 14):

```python
    OPENING_COMPLETE = "opening_complete"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_orchestrator.py::TestEventTypes -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_debate/types.py tests/test_orchestrator.py
git commit -m "feat: add OPENING_COMPLETE event type"
```

---

### Task 2: Extract run_opening() from Orchestrator

**Files:**
- Modify: `src/agent_debate/orchestrator.py:69-80`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_orchestrator.py`, add a new test class. This test uses `FakeProvider` to verify `run_opening()` yields the right events and ends with `OPENING_COMPLETE` carrying responses:

```python
class TestRunOpening:
    @pytest.mark.anyio
    async def test_yields_opening_complete_with_responses(self):
        config = make_config(num_agents=2)
        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.config = config
        fake = FakeProvider(["Response from agent"])
        orchestrator._providers = {"claude": fake}

        events = []
        async for event in orchestrator.run_opening("test prompt"):
            events.append(event)

        event_types = [e.type for e in events]
        assert EventType.ROUND_START in event_types
        assert EventType.AGENT_STARTED in event_types
        assert EventType.AGENT_CHUNK in event_types
        assert EventType.AGENT_COMPLETED in event_types
        assert EventType.OPENING_COMPLETE in event_types
        assert event_types[-1] == EventType.OPENING_COMPLETE

        opening_event = events[-1]
        responses = opening_event.metadata["responses"]
        assert len(responses) == 2
        assert all(isinstance(r, AgentResponse) for r in responses)

    @pytest.mark.anyio
    async def test_agent_responses_not_yielded_directly(self):
        config = make_config(num_agents=2)
        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.config = config
        fake = FakeProvider(["Response"])
        orchestrator._providers = {"claude": fake}

        async for event in orchestrator.run_opening("test"):
            assert isinstance(event, DebateEvent), (
                f"run_opening() should only yield DebateEvent, got {type(event)}"
            )

    @pytest.mark.anyio
    async def test_partial_failure_still_yields_opening_complete(self):
        config = make_config(num_agents=2)
        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.config = config

        call_count = 0

        class FailingProvider:
            id = "claude"
            display_name = "Failing"

            async def analyze(self, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("Agent failed")
                yield "Success"

            def available(self):
                return True

        orchestrator._providers = {"claude": FailingProvider()}

        events = []
        async for event in orchestrator.run_opening("test"):
            events.append(event)

        event_types = [e.type for e in events]
        assert EventType.ERROR in event_types
        assert EventType.OPENING_COMPLETE in event_types

        opening_event = [e for e in events if e.type == EventType.OPENING_COMPLETE][0]
        responses = opening_event.metadata["responses"]
        assert len(responses) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py::TestRunOpening -v`
Expected: FAIL with `AttributeError: 'Orchestrator' object has no attribute 'run_opening'`

- [ ] **Step 3: Implement run_opening()**

In `src/agent_debate/orchestrator.py`, add this method to the `Orchestrator` class, before the existing `run()` method (before line 69):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_orchestrator.py::TestRunOpening -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/agent_debate/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: extract run_opening() from orchestrator"
```

---

### Task 3: Extract run_debate() from Orchestrator

**Files:**
- Modify: `src/agent_debate/orchestrator.py:69-172`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_orchestrator.py`, add:

```python
class TestRunDebate:
    @pytest.mark.anyio
    async def test_runs_synthesis_with_opening_responses(self):
        """run_debate() should detect disagreements and synthesize."""
        config = make_config(num_agents=2)
        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.config = config
        fake = FakeProvider(["Debate response"])
        orchestrator._providers = {"claude": fake}

        opening_responses = [
            AgentResponse("claude:agent0", "claude", "agent0", 1, "Use REST", "Architect"),
            AgentResponse("claude:agent1", "claude", "agent1", 1, "Use gRPC", "Pragmatist"),
        ]

        # Mock the Claude Agent SDK calls used by disagreement detection and synthesis
        mock_query_result = AsyncMock()
        mock_query_result.__aiter__ = lambda self: self
        mock_query_result.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

        with patch("agent_debate.orchestrator.query", return_value=mock_query_result):
            events = []
            async for event in orchestrator.run_debate("test prompt", opening_responses):
                events.append(event)

        event_types = [e.type for e in events]
        # Should always end with synthesis
        assert EventType.SYNTHESIS_START in event_types
        assert EventType.SYNTHESIS_COMPLETE in event_types

    @pytest.mark.anyio
    async def test_empty_responses_skips_to_synthesis(self):
        """With no opening responses, run_debate() should skip debate and synthesize."""
        config = make_config(num_agents=2)
        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.config = config

        mock_query_result = AsyncMock()
        mock_query_result.__aiter__ = lambda self: self
        mock_query_result.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

        with patch("agent_debate.orchestrator.query", return_value=mock_query_result):
            events = []
            async for event in orchestrator.run_debate("test", []):
                events.append(event)

        event_types = [e.type for e in events]
        assert EventType.SYNTHESIS_START in event_types
        assert EventType.DEBATE_ROUND_START not in event_types
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py::TestRunDebate -v`
Expected: FAIL with `AttributeError: 'Orchestrator' object has no attribute 'run_debate'`

- [ ] **Step 3: Implement run_debate()**

In `src/agent_debate/orchestrator.py`, add this method after `run_opening()`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_orchestrator.py::TestRunDebate -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_debate/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: extract run_debate() from orchestrator"
```

---

### Task 4: Rewrite run() as a thin wrapper

**Files:**
- Modify: `src/agent_debate/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Add a backward-compatibility test that verifies `run()` still yields all expected event types end-to-end:

```python
class TestRunBackwardCompat:
    @pytest.mark.anyio
    async def test_run_yields_opening_complete_and_synthesis(self):
        """run() should chain both phases and yield all events including OPENING_COMPLETE."""
        config = make_config(num_agents=2)
        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.config = config
        fake = FakeProvider(["Agent response"])
        orchestrator._providers = {"claude": fake}

        mock_query_result = AsyncMock()
        mock_query_result.__aiter__ = lambda self: self
        mock_query_result.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

        with patch("agent_debate.orchestrator.query", return_value=mock_query_result):
            events = []
            async for event in orchestrator.run("test prompt"):
                events.append(event)

        event_types = [e.type for e in events]
        assert EventType.ROUND_START in event_types
        assert EventType.OPENING_COMPLETE in event_types
        assert EventType.SYNTHESIS_START in event_types
        assert EventType.SYNTHESIS_COMPLETE in event_types
```

- [ ] **Step 2: Run test to verify it fails (or passes if run() already works)**

Run: `python -m pytest tests/test_orchestrator.py::TestRunBackwardCompat -v`

- [ ] **Step 3: Replace the existing run() method**

Replace the entire existing `run()` method in `src/agent_debate/orchestrator.py` with:

```python
    async def run(self, prompt: str) -> AsyncIterator[DebateEvent]:
        """Run the full debate loop, yielding events as they occur.

        Convenience method that chains run_opening() and run_debate()
        without a human checkpoint.
        """
        responses: list[AgentResponse] = []
        async for event in self.run_opening(prompt):
            yield event
            if event.type == EventType.OPENING_COMPLETE:
                responses = event.metadata["responses"]
        async for event in self.run_debate(prompt, responses):
            yield event
```

- [ ] **Step 4: Run all tests to verify nothing breaks**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_debate/orchestrator.py tests/test_orchestrator.py
git commit -m "refactor: rewrite run() as thin wrapper over run_opening + run_debate"
```

---

### Task 5: Add checkpoint prompt to CLI

**Files:**
- Modify: `src/agent_debate/cli.py:102-201`

- [ ] **Step 1: Update _run() to use two-phase orchestrator with checkpoint**

Replace the `_run()` function in `src/agent_debate/cli.py` with:

```python
async def _run(
    prompt: str,
    providers: str,
    max_rounds: int,
    cwd: str,
    orchestrator_model: str,
    opening_only: bool = False,
) -> None:
    """Async entry point for the debate."""
    config = build_config(
        providers=providers,
        max_rounds=max_rounds,
        cwd=cwd,
        orchestrator_model=orchestrator_model,
    )

    console.print(
        Panel(
            f"[bold]Prompt:[/bold] {prompt}\n"
            f"[bold]Agents:[/bold] {', '.join(c.agent_id for c in config.providers)}\n"
            f"[bold]Max rounds:[/bold] {max_rounds}",
            title="[bold]Agent Debate[/bold]",
            border_style="bright_blue",
        )
    )

    orchestrator = Orchestrator(config)
    display = LiveDebateDisplay()
    opening_responses: list[AgentResponse] = []

    # Phase 1: Opening arguments
    with display.start():
        async for event in orchestrator.run_opening(prompt):
            if event.type == EventType.OPENING_COMPLETE:
                opening_responses = event.metadata["responses"]
                continue
            _handle_event(display, event)

    # If opening-only mode, stop here
    if opening_only:
        return

    # Checkpoint: ask human whether to proceed
    if not click.confirm("\nProceed with debate?", default=True):
        console.print("[dim]Debate skipped.[/dim]")
        return

    # Phase 2: Debate rounds + synthesis
    display = LiveDebateDisplay()
    with display.start():
        async for event in orchestrator.run_debate(prompt, opening_responses):
            _handle_event(display, event)
```

- [ ] **Step 2: Extract _handle_event() helper from the match block**

Add this function before `_run()` in `cli.py`:

```python
def _handle_event(display: LiveDebateDisplay, event: DebateEvent) -> None:
    """Route a DebateEvent to the appropriate display action."""
    match event.type:
        case EventType.ROUND_START:
            display.set_phase(
                f"Round {event.round_number}: Independent Analysis",
                style="blue",
            )
        case EventType.AGENT_STARTED:
            display.agent_started(event.agent_id or "unknown")
        case EventType.AGENT_CHUNK:
            display.agent_chunk(event.agent_id or "unknown", event.content)
        case EventType.AGENT_COMPLETED:
            display.agent_completed(event.agent_id or "unknown")
        case EventType.DISAGREEMENT_FOUND:
            positions = event.metadata.get("positions", {})
            pos_text = "\n".join(
                f"  {key}: {value}" for key, value in positions.items()
            )
            display.add_static(
                Panel(
                    f"[bold]{event.content}[/bold]\n{pos_text}",
                    title="[bold yellow]Disagreement[/bold yellow]",
                    border_style="yellow",
                )
            )
        case EventType.DEBATE_ROUND_START:
            display.clear_agents()
            display.set_phase(
                f"Debate Round {event.round_number}",
                style="cyan",
            )
        case EventType.CONSENSUS_REACHED:
            display.add_static(
                Panel(
                    f"[bold green]Consensus reached after round {event.round_number}[/bold green]",
                    style="green",
                )
            )
        case EventType.DEADLOCK_RESOLVED:
            display.clear_agents()
            display.add_static(
                Panel(
                    Markdown(event.content),
                    title=f"[bold red]Judge Resolution (round {event.round_number})[/bold red]",
                    border_style="red",
                )
            )
        case EventType.SYNTHESIS_START:
            display.clear_agents()
            display.add_static(
                Panel("[bold]Synthesizing results...[/bold]", style="magenta")
            )
        case EventType.SYNTHESIS_COMPLETE:
            display.add_static(
                Panel(
                    Markdown(event.content),
                    title="[bold magenta]Final Synthesis[/bold magenta]",
                    border_style="magenta",
                )
            )
        case EventType.ERROR:
            display.add_static(
                Panel(
                    f"[bold red]{event.content}[/bold red]",
                    title=f"Error ({event.agent_id or 'unknown'})",
                    border_style="red",
                )
            )
```

- [ ] **Step 3: Add --opening-only flag to the Click command**

In `cli.py`, add the `--opening-only` option to the `run` Click command, after the existing `--orchestrator-model` option:

```python
@click.option(
    "--opening-only",
    is_flag=True,
    default=False,
    help="Run only the opening arguments phase (no debate or checkpoint prompt)",
)
```

Update the `run()` function signature to accept `opening_only: bool` and pass it through to `_run()`:

```python
def run(
    prompt: str,
    providers: str,
    max_rounds: int,
    cwd: str,
    orchestrator_model: str,
    opening_only: bool,
) -> None:
    ...
    anyio.run(_run, prompt, providers, max_rounds, cwd, orchestrator_model, opening_only)
```

- [ ] **Step 4: Remove the old inline match block from _run()**

The old `_run()` with its inline match block should be fully replaced by the new version from Step 1. Verify the old code is gone and the `AgentResponse` import is still present (it's used for the type of `opening_responses`).

- [ ] **Step 5: Verify CLI still works**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/agent_debate/cli.py
git commit -m "feat: add checkpoint prompt and --opening-only flag to CLI"
```

---

### Task 6: Update plugin command

**Files:**
- Modify: `plugin/debate/commands/run.md`

- [ ] **Step 1: Add checkpoint after Phase 2 in run.md**

In `plugin/debate/commands/run.md`, add a new section between Phase 2 (Independent Analysis) and Phase 3 (Disagreement Detection). After the line "Wait for all 3 agents to complete and collect their responses." (line 103), add:

```markdown
#### Phase 2.5: Opening Arguments Checkpoint

Present the opening arguments to the user:

```
## Opening Arguments

**Architect:** [brief summary of their position]
**Pragmatist:** [brief summary of their position]
**Reliability Engineer:** [brief summary of their position]
```

Then ask the user:

> "Here are the opening arguments from all three agents. Would you like me to proceed with the debate (agents will cross-examine each other's findings), or are these responses sufficient?"

**If the user wants to proceed**, continue to Phase 3.
**If the user is satisfied**, skip to Phase 5 (Synthesis) using only the opening arguments.
```

- [ ] **Step 2: Update Package Mode section**

In the Step 2A: Package Mode section, update the command to support opening-only mode. After the existing `agent-debate run` command, add:

```markdown
For the checkpoint flow, use two commands:

```bash
# Phase 1: Opening arguments only
agent-debate run "<prompt>" --providers "<providers>" --opening-only --cwd "$(pwd)"
```

Present the output to the user and ask if they want to proceed. If yes, run the full debate:

```bash
agent-debate run "<prompt>" --providers "<providers>" --max-rounds <max_rounds> --cwd "$(pwd)"
```
```

- [ ] **Step 3: Commit**

```bash
git add plugin/debate/commands/run.md
git commit -m "docs: add opening arguments checkpoint to plugin command"
```

---

### Task 7: Run full test suite and verify

- [ ] **Step 1: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Verify no regressions in existing test classes**

Specifically confirm these all pass:
- `TestParseDisagreements`
- `TestRoundClassification`
- `TestPositionUpdates`
- `TestAgentIdDedup`
- `TestParseProviderString`
- `TestParseProvidersString`
- `TestBuildConfig`
- `TestProviderConfig`

- [ ] **Step 3: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore: final cleanup for opening arguments feature"
```
