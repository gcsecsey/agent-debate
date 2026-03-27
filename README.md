# agent-debate

Multi-agent debate system. Fan out prompts to multiple AI coding agents in parallel, identify disagreements, run adaptive debate rounds, and synthesize a consensus recommendation.

Inspired by [counselors](https://github.com/aarondfrancis/counselors), but with a debate loop and built on the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python).

## How it works

1. Your prompt is sent to multiple AI agents in parallel (e.g. Claude Opus, Codex, Gemini) — each agent gets a persona (security, performance, architecture, etc.) for differentiated analysis
2. An orchestrator (Claude Haiku) extracts and deduplicates findings, then identifies genuine technical contradictions between agents
3. If contradictions are found, agents debate their positions in a single targeted round, seeing each other's arguments
4. A final synthesis (Claude Sonnet) presents: key findings, disagreements with both sides' reasoning, a recommended approach, and concrete next steps

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
# Default: top group (claude:opus, gemini, codex)
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
| `--providers` | `-p` | `top` | Comma-separated provider specs or group name |
| `--max-rounds` | `-r` | `1` | Maximum debate rounds |
| `--cwd` | `-d` | `.` | Working directory for agents |
| `--orchestrator-model` | `-m` | `sonnet` | Model for disagreement detection and synthesis |
| `--timeout` | `-t` | `300` | Timeout per agent call in seconds |
| `--max-parallel` | | `5` | Maximum concurrent agent calls |
| `--opening-only` | | `false` | Run only the opening analysis (skip debate) |
| `--no-report` | | `false` | Disable saving the markdown report |

#### Provider specs

Format: `provider[:model][@persona]`

```
claude:opus            # Claude with Opus model
claude:sonnet          # Claude with Sonnet model
codex                  # Codex with default model (gpt-5.3-codex)
codex:o4-mini          # Codex with specific model
gemini                 # Gemini with default model (gemini-2.5-pro)
amp:deep               # Amp with deep reasoning model
claude:opus@security   # Claude Opus with security persona
codex@performance      # Codex with performance persona
```

Available personas: `security`, `performance`, `architecture`, `reliability`, `maintainability`. When no personas are specified, they are auto-assigned round-robin.

You can use the same provider multiple times:

```bash
agent-debate run -p claude:opus,claude:opus,claude:opus "Review this code"
```

### Claude Code plugin

The plugin provides a `/debate:run` slash command that works inside Claude Code. Requires the Python package to be installed.

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
        providers="top",
        max_rounds=1,
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
├── personas.py           # Agent persona definitions and auto-assignment
├── prompts.py            # Prompt templates for analysis, dedup, debate, synthesis
├── providers/
│   ├── base.py           # Abstract BaseProvider
│   ├── subprocess_base.py # Shared subprocess logic for CLI providers
│   ├── claude.py         # Claude via Agent SDK
│   ├── codex.py          # Codex via subprocess
│   ├── gemini.py         # Gemini via subprocess
│   └── amp.py            # Amp via subprocess
├── orchestrator.py       # Debate loop: fan-out → detect → debate → synthesize
├── report.py             # Markdown report generation
├── tracing.py            # Optional Langfuse tracing integration
└── cli.py                # Click CLI

plugin/debate/            # Claude Code plugin (for Automattic marketplace)
├── commands/run.md       # /debate:run slash command
├── scripts/debate.sh     # Package mode wrapper
└── .claude-plugin/plugin.json
```

## Tracing

Optional [Langfuse](https://langfuse.com/) tracing produces structured traces with per-phase spans and per-LLM-call generations, giving visibility into token usage, cost, and latency.

### Setup

Install with the tracing extra:

```bash
pip install -e ".[tracing]"
```

Create a `.env` file in the project root (already gitignored):

```
LANGFUSE_HOST=https://langfuse.a8c.com
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
```

Get your API keys from Langfuse → Settings → API Keys.

### How it works

Tracing is automatically enabled when the Langfuse SDK is installed and the environment variables are set. No CLI flags or code changes needed — just run `agent-debate` as usual and traces appear in Langfuse.

Each debate run produces a trace with this structure:

```
debate_run (trace)
├── round_1 (span)
│   ├── claude:opus (generation)
│   ├── codex (generation)
│   └── gemini (generation)
├── dedup (span)
│   └── dedup_call (generation)
├── targeted_debate (span, if disagreements exist)
│   ├── claude:opus (generation)
│   └── ...
└── synthesis (span)
    └── synthesis_call (generation)
```

When Langfuse is not installed or not configured, tracing is silently disabled with zero overhead.

## Development

```bash
# Run tests
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_orchestrator.py -v
```
