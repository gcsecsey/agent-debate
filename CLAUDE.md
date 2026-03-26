# CLAUDE.md

## Project overview

Multi-agent debate system that fans out prompts to multiple AI coding CLIs (Claude, Codex, Gemini, Amp), detects disagreements, runs targeted debate rounds, and synthesizes consensus. Built on the Claude Agent SDK.

## Quick reference

```bash
# Install (development)
pip install -e ".[dev]"

# Run tests (unit only — no API calls)
python -m pytest tests/ -v --ignore=tests/evals

# Run eval tests (hits real APIs, costs money)
python -m pytest tests/ -m eval -v

# Run a debate
agent-debate run "Your prompt here"

# Discover available providers
agent-debate discover
```

## Architecture

- `src/agent_debate/` — main package
  - `orchestrator.py` — core debate loop: fan-out → dedup → debate → synthesize
  - `providers/` — one module per CLI provider, all extend `base.py`; CLI-based ones share `subprocess_base.py`
  - `prompts.py` — prompt templates for dedup, debate, and synthesis phases
  - `types.py` — dataclasses for config, events, findings, disagreements
  - `cli.py` — Click CLI entry point
  - `tracing.py` — optional Langfuse tracing (auto-enabled when SDK + env vars present)
  - `report.py` — markdown report generation
- `plugin/debate/` — Claude Code slash command plugin
- `tests/` — pytest suite; `tests/evals/` for LLM eval tests (marked `eval`)

## Code conventions

- Python 3.10+, use `from __future__ import annotations` for modern type syntax
- Dataclasses for data types (not Pydantic)
- Async-first with `anyio` (not raw asyncio)
- Tests use `pytest` + `pytest-anyio`; mocks for provider calls in unit tests
- No formatter/linter is configured — match existing style

## Adding a new provider

1. Create `src/agent_debate/providers/<name>.py`
2. Extend `SubprocessProvider` (for CLI tools) or `BaseProvider` (for SDK integrations)
3. Register in `src/agent_debate/providers/__init__.py`
4. Add to `src/agent_debate/config.py` provider resolution
