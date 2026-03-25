# debate

Multi-perspective analysis plugin for Claude Code. Fan out prompts to multiple AI agents, deduplicate findings, and synthesize actionable recommendations.

## Usage

```
/debate Review the auth module for security issues
/debate Should we use REST or gRPC for the new API?
/debate --providers fast Plan the database migration strategy
```

## How it works

1. Your prompt is sent to multiple agents with different perspectives (Architect, Pragmatist, Reliability Engineer)
2. An orchestrator deduplicates findings across all agents and identifies stark contradictions
3. If agents genuinely contradict each other, a single targeted debate round runs
4. The orchestrator synthesizes a final recommendation with key findings, disagreements, and next steps

## Model Groups

Use `--providers` with a group name for quick setup:

- `top` — Claude Opus, Gemini Pro, Codex (best models, default)
- `fast` — Claude Sonnet, Codex Mini, Gemini Flash (fast/cheap)

Or specify models manually: `--providers claude:opus,codex,gemini`

## Modes

**Built-in mode (default):** Uses Claude Code's Task sub-agents with different personas. No dependencies required.

**Package mode:** If `agent-debate` is installed (`pip install agent-debate`), the command uses it for multi-provider support (Claude, Codex, Gemini, Amp) and streaming output.

## Configuration

The `/debate` command accepts inline options:

- `--providers top|fast|claude:opus,codex,gemini` — model group or manual specs
- `--max-rounds 1` — targeted debate rounds (0 to disable)
- `--orchestrator-model sonnet` — model for deduplication and synthesis

## Installation

Install from the marketplace:

```
/plugin install debate
```

For multi-provider support, also install the Python package:

```bash
pip install agent-debate
```
