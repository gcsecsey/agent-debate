# Opening Arguments Phase

## Summary

Add a checkpoint after round 1 independent analysis that shows the human all agent responses before deciding whether to proceed with debate rounds. This turns the debate from a fire-and-forget operation into a two-phase flow where the human can exit early when the opening arguments already answer their question.

## Motivation

- When all agents independently arrive at the same conclusion, cross-verification via debate rounds is unnecessary — the human can see consensus from the opening arguments alone.
- The human can judge whether the agents investigated the right parts of the codebase before committing to expensive debate rounds.
- Saves token cost and time when the answer is already clear.

## Design

### Orchestrator API (Approach A: Two-Phase Split)

Split `Orchestrator.run()` into two public methods:

**`run_opening(prompt: str) -> AsyncIterator[DebateEvent]`**
- Fans out the prompt to all agents in parallel (same as current round 1)
- Yields only `DebateEvent` objects: `ROUND_START`, `AGENT_STARTED`, `AGENT_CHUNK`, `AGENT_COMPLETED`
- `AgentResponse` objects are collected internally but NOT yielded — they are bundled into the final `OPENING_COMPLETE` event's metadata
- Ends by yielding `OPENING_COMPLETE` with `metadata={"responses": [AgentResponse, ...]}`
- If an agent fails, its `ERROR` event is yielded and it is excluded from the responses list. `OPENING_COMPLETE` still fires with whatever responses succeeded (even if zero).

**`run_debate(prompt: str, opening_responses: list[AgentResponse]) -> AsyncIterator[DebateEvent]`**
- Accepts the responses from the opening phase
- Runs disagreement detection, debate rounds, deadlock resolution, and synthesis
- May yield any post-round-1 event: `DISAGREEMENT_FOUND`, `DEBATE_ROUND_START`, `CONSENSUS_REACHED`, `DEADLOCK_RESOLVED`, `SYNTHESIS_START`, `SYNTHESIS_COMPLETE`, or `ERROR`
- If `opening_responses` is empty or has only one agent, skips debate and runs synthesis directly

**`run(prompt: str) -> AsyncIterator[DebateEvent]`**
- Convenience method that chains both phases without pausing:
  ```python
  async def run(self, prompt):
      responses = []
      async for event in self.run_opening(prompt):
          yield event
          if event.type == EventType.OPENING_COMPLETE:
              responses = event.metadata["responses"]
      async for event in self.run_debate(prompt, responses):
          yield event
  ```
- Preserves backward compatibility for the Python API

### Event Types

One new event type added to `EventType`:

- **`OPENING_COMPLETE`** — emitted after all agents finish round 1. Carries `metadata={"responses": [AgentResponse, ...]}` so the caller has the data needed to pass into `run_debate()`.

No changes to existing event types or data model classes (`AgentResponse`, `Disagreement`, `DebateConfig`, `PositionUpdate`, `ProviderConfig`).

Note: `metadata` is typed as `dict` on `DebateEvent`, so `metadata["responses"]` is weakly typed. This is consistent with how `metadata` is already used (e.g., `metadata={"positions": ...}` for `DISAGREEMENT_FOUND`). Callers must know to extract `list[AgentResponse]` from the key.

### CLI Changes

In the `run` Click command:

1. Stream `run_opening()` to the Rich live display (same UX as today for round 1)
2. After `OPENING_COMPLETE`, stop the live display (`live.stop()`) and prompt:
   ```
   Proceed with debate? [Y/n]
   ```
   Default is Yes (proceed), since the common case when agents disagree is to want the debate.
3. **Yes** → call `run_debate(prompt, responses)` with a new `Live` context for debate rounds + synthesis
4. **No** → print "Debate skipped." and exit. The opening arguments are already visible on screen.

Implementation note: `input()` / `click.confirm()` cannot run inside a Rich `Live` context. The live display must be stopped before prompting, then a fresh `Live` context created for the debate phase.

### Plugin Changes

In `commands/run.md`, insert a checkpoint between Phase 2 (Independent Analysis) and Phase 3 (Disagreement Detection). After collecting all three agent responses, present them to the user and ask:

> "Here are the opening arguments from all three agents. Would you like me to proceed with the debate (agents will cross-examine each other's findings), or are these responses sufficient?"

In package mode, this maps to calling `agent-debate` with a new `--opening-only` flag, then prompting the user before running the full debate. In built-in mode (Task sub-agents), the checkpoint is natural since the orchestrating agent can ask conversationally.

### Testing

New test cases:

- `run_opening()` yields `ROUND_START`, agent streaming events, then `OPENING_COMPLETE` with responses in metadata
- `run_debate()` accepts prior responses and runs disagreement → debate → synthesis flow
- `run()` still works end-to-end (backward compatibility)
- `OPENING_COMPLETE` event carries the correct number of responses matching provider config

No changes to existing test cases — they continue to exercise `run()` which chains both phases.

## What Does Not Change

- Provider implementations (claude, codex, gemini, amp)
- Config parsing
- Prompt templates
- Data model classes
- Streaming infrastructure
