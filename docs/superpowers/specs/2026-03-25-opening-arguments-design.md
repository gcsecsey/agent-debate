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
- Yields the existing streaming events: `ROUND_START`, `AGENT_STARTED`, `AGENT_CHUNK`, `AGENT_COMPLETED`
- Ends by yielding `OPENING_COMPLETE` with collected responses in metadata

**`run_debate(prompt: str, opening_responses: list[AgentResponse]) -> AsyncIterator[DebateEvent]`**
- Accepts the responses from the opening phase
- Runs disagreement detection, debate rounds, deadlock resolution, and synthesis
- Yields events from `DISAGREEMENT_FOUND` onward (same as today)

**`run(prompt: str) -> AsyncIterator[DebateEvent]`**
- Convenience method that chains `run_opening()` and `run_debate()` without pausing
- Preserves backward compatibility for the Python API

### Event Types

One new event type added to `EventType`:

- **`OPENING_COMPLETE`** — emitted after all agents finish round 1. Carries `metadata={"responses": [AgentResponse, ...]}` so the caller has the data needed to pass into `run_debate()`.

No changes to existing event types or data model classes (`AgentResponse`, `Disagreement`, `DebateConfig`, `PositionUpdate`, `ProviderConfig`).

### CLI Changes

In the `run` Click command:

1. Stream `run_opening()` to the Rich live display (same UX as today for round 1)
2. After `OPENING_COMPLETE`, end the live display and prompt:
   ```
   Proceed with debate? [y/N]
   ```
3. **Yes** → call `run_debate(prompt, responses)`, resume live display for debate rounds + synthesis
4. **No** → print "Debate skipped." and exit. The opening arguments are already visible on screen.

### Plugin Changes

The `commands/run.md` slash command follows the same flow. After showing opening arguments, the orchestrating agent asks the user whether to continue. In built-in mode (Task sub-agents), this is natural since the agent can ask conversationally.

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
