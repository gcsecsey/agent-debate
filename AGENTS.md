# AGENTS.md

## Cursor Cloud specific instructions

### Overview

This is a Python CLI tool (multi-agent debate system). No databases, Docker, or external services are required for development. See `CLAUDE.md` and `README.md` for full command reference.

### Environment

- Python 3.12 is pre-installed. The project requires Python 3.10+.
- `/home/ubuntu/.local/bin` must be on PATH for the `agent-debate` CLI entry point (added to `~/.bashrc`).
- Install: `pip install -e ".[dev]"` (editable dev install from `pyproject.toml`).

### Running tests

```bash
python3 -m pytest tests/ -v --ignore=tests/evals
```

**Known issue:** Several integration test classes (`TestRunOpening`, `TestRunDebate`, `TestRunBackwardCompat`, `TestTwoPhaseIntegration`) hang indefinitely due to a missing `_semaphore` attribute when tests use `Orchestrator.__new__()` to bypass `__init__`. To skip them:

```bash
python3 -m pytest tests/ -v --ignore=tests/evals \
  -k "not TestRunOpening and not TestRunDebate and not TestRunBackwardCompat and not TestTwoPhaseIntegration"
```

One pre-existing test failure: `test_available_when_cli_found` — the mock doesn't fully cover the `available()` check.

### Running the CLI

```bash
agent-debate --help
agent-debate discover
agent-debate run "Your prompt"
```

The `run` command requires at least one AI CLI provider (`claude`, `codex`, `gemini`, or `amp`) on PATH plus an `ANTHROPIC_API_KEY` for orchestration. In Cloud Agent environments without API keys, use `discover` and `--help` to verify the installation.

### Eval tests

Eval tests (`tests/evals/`) hit real APIs and cost money. They require `ANTHROPIC_API_KEY` and optionally Langfuse credentials. Do not run them unless explicitly requested.

### No linter configured

The project has no formatter or linter configured. Match existing code style.
