# agent-debate

Multi-agent debate system. Fan out prompts to multiple AI coding agents in parallel, identify disagreements, run adaptive debate rounds, and synthesize a consensus recommendation.

Inspired by [counselors](https://github.com/aarondfrancis/counselors), but with a debate loop and built on the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python).

## How it works

1. Your prompt is sent to multiple agents with different perspectives (Architect, Pragmatist, Reliability Engineer)
2. An orchestrator (Claude) identifies genuine technical disagreements between their responses
3. Agents debate the disagreements in follow-up rounds, explicitly advocating for their position while seeing each other's arguments
4. In debate rounds, agents submit structured position updates so the judge can track what changed and why
5. The orchestrator detects consensus, and if the debate deadlocks, the judge resolves it with a concrete recommendation
6. A final synthesis presents: consensus points, resolved disagreements, remaining differences, and a recommended approach

## Supported providers

| Provider | CLI | Prompt delivery |
|----------|-----|-----------------|
| Claude Code | `claude` | Agent SDK (`claude-agent-sdk`) |
| OpenAI Codex | `codex` | Subprocess, file reference |
| Gemini CLI | `gemini` | Subprocess, stdin |
| Amp CLI | `amp` | Subprocess, stdin |

## Install

Requires Python 3.10+.

```bash
pip install -e .
```

Or for development:

```bash
pip install -e ".[dev]"
```

### Prerequisites

Install the AI CLIs you want to use as debate agents:

- **Claude Code** (required for orchestration): [docs](https://docs.anthropic.com/en/docs/claude-code)
- **Codex** (optional): [github](https://github.com/openai/codex)
- **Gemini CLI** (optional): [github](https://github.com/google-gemini/gemini-cli)
- **Amp CLI** (optional): [ampcode.com](https://ampcode.com)

Check what's available on your system:

```bash
agent-debate discover
```

## Usage

### CLI

```bash
# Default: 3 Claude agents (opus, sonnet, haiku) debate
agent-debate run "Should we use REST or gRPC for the new API?"

# Multi-provider debate
agent-debate run -p claude:opus,codex,gemini "Review src/auth/ for security issues"

# Custom settings
agent-debate run \
  -p claude:opus,claude:sonnet,codex \
  -r 2 \
  -d ./my-project \
  -m opus \
  "Plan the database migration strategy"
```

#### Options

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--providers` | `-p` | `claude:opus,claude:sonnet,claude:haiku` | Comma-separated provider specs |
| `--max-rounds` | `-r` | `3` | Maximum debate rounds |
| `--cwd` | `-d` | `.` | Working directory for agents |
| `--orchestrator-model` | `-m` | `sonnet` | Model for disagreement detection and synthesis |

#### Provider specs

Format: `provider` or `provider:model`

```
claude:opus      # Claude with Opus model
claude:sonnet    # Claude with Sonnet model
codex            # Codex with default model (gpt-5.3-codex)
codex:o4-mini    # Codex with specific model
gemini           # Gemini with default model (gemini-2.5-pro)
amp:deep         # Amp with deep reasoning model
```

You can use the same provider multiple times:

```bash
agent-debate run -p claude:opus,claude:opus,claude:opus "Review this code"
```

### Claude Code plugin

The plugin provides a `/debate:run` slash command that works inside Claude Code with zero dependencies (falls back to Task sub-agents if the Python package isn't installed).

#### Install the plugin

In any Claude Code session, run:

```
/plugin marketplace add github:gcsecsey/agent-debate
/plugin install debate
```

The `/debate:run` command will be available in all future sessions.

For local development/testing (single session only):

```bash
claude --plugin-dir ~/projects/agent-debate/plugin/debate
```

#### Use the plugin

```
/debate:run Review the auth module for security issues
/debate:run --providers claude:opus,codex,gemini Should we use REST or gRPC?
```

### Python API

```python
import anyio
from agent_debate.config import build_config
from agent_debate.orchestrator import Orchestrator

async def main():
    config = build_config(
        providers="claude:opus,claude:sonnet,claude:haiku",
        max_rounds=3,
        cwd=".",
    )
    orchestrator = Orchestrator(config)

    async for event in orchestrator.run("Should we use REST or gRPC?"):
        print(f"[{event.type.value}] {event.content[:100]}")

anyio.run(main)
```

## Architecture

```
src/agent_debate/
├── types.py              # Event, response, config dataclasses
├── config.py             # Provider string parsing
├── prompts.py            # Prompt templates for personas, debate, synthesis
├── providers/
│   ├── base.py           # Abstract BaseProvider
│   ├── subprocess_base.py # Shared subprocess logic for CLI providers
│   ├── claude.py         # Claude via Agent SDK
│   ├── codex.py          # Codex via subprocess
│   ├── gemini.py         # Gemini via subprocess
│   └── amp.py            # Amp via subprocess
├── orchestrator.py       # Debate loop: fan-out → detect → debate → synthesize
├── streaming.py          # Async queue-based parallel event merging
└── cli.py                # Click CLI

plugin/debate/            # Claude Code plugin (for Automattic marketplace)
├── commands/run.md       # /debate:run slash command
├── scripts/debate.sh     # Package mode wrapper
└── .claude-plugin/plugin.json
```

## Development

```bash
# Run tests
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_orchestrator.py -v
```
