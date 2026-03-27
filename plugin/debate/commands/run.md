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

Run the opening arguments phase first using `--opening-only` and `--format plain` (plain format avoids broken Rich terminal output):

```bash
agent-debate run "<prompt>" --providers "<providers>" --max-rounds <max_rounds> --cwd "$(pwd)" --opening-only --format plain --timeout 120
```

Note: Use a Bash timeout of at least 300000ms (5 minutes) since agents can take time to respond.

After the command completes, **parse the report directory** from the output. Look for a line like:
```
REPORT_DIR: .context/debate/2026-03-27T143000
```

If a report directory was found, **read the individual agent responses** for richer presentation:

1. Use Glob to find agent response files: `<report_dir>/agents/*.md`
2. Read each agent's markdown file and present their full responses to the user
3. Present a structured summary showing each agent's key points

Ask the user:

> "Here are the opening arguments from all agents. Would you like me to proceed with the debate (agents will cross-examine each other's findings), or are these responses sufficient?"

If the user wants to proceed, run the full analysis:

```bash
agent-debate run "<prompt>" --providers "<providers>" --max-rounds <max_rounds> --cwd "$(pwd)" --format plain --timeout 120
```

After completion, **read the report files** to present results:

1. Parse the `REPORT_DIR:` line from the output
2. Read `<report_dir>/synthesis.md` for the final synthesis
3. Optionally read `<report_dir>/debate.json` for structured findings and disagreements
4. Present the synthesis and key findings to the user
5. Mention that full agent responses are available in the report directory

---

### If agent-debate is NOT available

Inform the user:

> The `agent-debate` package is required. Install it with:
> ```
> pip install -e /path/to/agent-debate
> ```

Do NOT attempt to run the analysis without the package.
