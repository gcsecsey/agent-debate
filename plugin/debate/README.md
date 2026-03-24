# debate

Multi-agent debate plugin for Claude Code. Fan out prompts to multiple AI coding agents, have them debate disagreements, and synthesize a consensus recommendation.

## Usage

```
/debate Review the auth module for security issues
/debate Should we use REST or gRPC for the new API?
/debate Plan the database migration strategy
```

## How it works

1. Your prompt is sent to multiple agents with different perspectives (Architect, Pragmatist, Reliability Engineer)
2. An orchestrator identifies genuine disagreements between agents
3. Agents debate the disagreements in follow-up rounds
4. The orchestrator synthesizes a final recommendation with consensus points, resolved disagreements, and remaining differences

## Modes

**Built-in mode (default):** Uses Claude Code's Task sub-agents with different models/personas. No dependencies required.

**Package mode:** If `agent-debate` is installed (`pip install agent-debate`), the command uses it for multi-provider support (Claude, Codex, Gemini, Amp) and streaming output.

## Configuration

The `/debate` command accepts inline options:

- `--providers claude:opus,codex,gemini` — specify agents (package mode only)
- `--max-rounds 3` — maximum debate rounds
- `--orchestrator-model sonnet` — model for the orchestrator

## Installation

Install from the Automattic Claude Code plugins marketplace:

```
/plugin install debate
```

For multi-provider support, also install the Python package:

```bash
pip install agent-debate
```
