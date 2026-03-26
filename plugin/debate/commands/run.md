---
description: Run a multi-perspective analysis to get diverse AI perspectives on a coding question
argument-hint: <prompt> [--providers top|fast|claude:opus,codex,gemini] [--max-rounds 1]
allowed-tools: Bash, Read, Glob, Grep, AskUserQuestion
---

# Multi-Perspective Analysis

Get multiple AI perspectives on a coding question, deduplicate findings, and synthesize a recommendation.

## Context

**User Request:**

Arguments provided: `$ARGUMENTS`

Parse the arguments to extract:
- The **prompt** (required) — the coding question or task to analyze
- `--providers` (optional) — comma-separated provider specs or group name (`top`, `fast`), default: `top`
- `--max-rounds` (optional) — maximum targeted debate rounds (0 to disable), default: `1`
- `--orchestrator-model` (optional) — model for orchestrator, default: `sonnet`
- `--opening-only` (optional) — run only the opening arguments phase, default: false

## Instructions

### Step 1: Check for agent-debate package

Try to detect if the `agent-debate` Python package is installed:

```bash
command -v agent-debate && agent-debate discover
```

**If agent-debate is available**, run it (see below).
**If not available**, inform the user they need to install it.

---

### Step 2A: Package Mode

Run the opening arguments phase first using `--opening-only`:

```bash
agent-debate run "<prompt>" --providers "<providers>" --max-rounds <max_rounds> --cwd "$(pwd)" --opening-only
```

Present the opening arguments output to the user and ask:

> "Here are the opening arguments from all agents. Would you like me to proceed with the debate (agents will cross-examine each other's findings), or are these responses sufficient?"

If the user wants to proceed, run the full analysis:

```bash
agent-debate run "<prompt>" --providers "<providers>" --max-rounds <max_rounds> --cwd "$(pwd)"
```

Read the output and present it to the user. Done.

---

### If agent-debate is NOT available

Inform the user:

> The `agent-debate` package is required. Install it with:
> ```
> pip install -e /path/to/agent-debate
> ```

Do NOT attempt to run the analysis without the package.
