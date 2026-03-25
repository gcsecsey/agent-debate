---
description: Run a multi-agent debate to get diverse AI perspectives on a coding question
argument-hint: <prompt> [--providers claude:opus,codex,gemini] [--max-rounds 3]
allowed-tools: Task, Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

# Multi-Agent Debate

Get multiple AI perspectives on a coding question, identify disagreements, run debate rounds, and synthesize a recommendation.

## Context

**User Request:**

Arguments provided: `$ARGUMENTS`

Parse the arguments to extract:
- The **prompt** (required) — the coding question or task to debate
- `--providers` (optional) — comma-separated provider specs, default: `claude:opus,claude:sonnet,claude:haiku`
- `--max-rounds` (optional) — maximum debate rounds, default: `3`
- `--orchestrator-model` (optional) — model for orchestrator, default: `sonnet`

## Instructions

### Step 1: Check for agent-debate package

Try to detect if the `agent-debate` Python package is installed. Check the plugin's own venv first, then PATH:

```bash
DEBATE_BIN=""; if [ -x "$HOME/code/agent-debate/venv/bin/agent-debate" ]; then DEBATE_BIN="$HOME/code/agent-debate/venv/bin/agent-debate"; elif command -v agent-debate &>/dev/null; then DEBATE_BIN="agent-debate"; fi; [ -n "$DEBATE_BIN" ] && "$DEBATE_BIN" discover
```

**IMPORTANT:** Always show the discovery results to the user — print which providers were found and which were not. This is valuable context that should not be hidden in a collapsed tool call. Example output:

```
## Provider Discovery
- claude: available
- codex: not found
- gemini: not found
- amp: not found
```

**If agent-debate is available** (DEBATE_BIN is set), use **Package Mode** (Step 2A). Use `$DEBATE_BIN` in place of `agent-debate` in all commands below.
**If not available**, use **Built-in Mode** (Step 2B).

---

### Step 2A: Package Mode

Run the debate via the Python package. This supports multi-provider debates (Claude, Codex, Gemini, Amp).

For the checkpoint flow, use two steps:

```bash
# Phase 1: Opening arguments only
$DEBATE_BIN run "<prompt>" --providers "<providers>" --opening-only --cwd "$(pwd)"
```

Present the output to the user and ask if they want to proceed with the debate. If yes, run the full debate:

```bash
$DEBATE_BIN run "<prompt>" --providers "<providers>" --max-rounds <max_rounds> --cwd "$(pwd)"
```

Read the output and present it to the user. Done.

---

### Step 2B: Built-in Mode (Task Sub-Agents)

Run the debate using Claude Code's built-in Task sub-agents. This is Claude-only but requires no dependencies.

#### Phase 1: Gather Context

Before fanning out, gather relevant context from the codebase to enrich the prompt:

1. Read any files the user referenced in their prompt
2. If the prompt mentions recent changes, run `git log --oneline -10` and `git diff HEAD~1` to gather context
3. If the prompt mentions a specific module/directory, use Glob to find relevant files and read key ones

Build an **enriched prompt** that includes the user's original question plus the gathered context.

#### Phase 2: Independent Analysis (Fan Out)

Launch **3 Task sub-agents in parallel**, each with a different persona and model. All 3 Tasks MUST be launched in a single message to run in parallel.

**Agent 1 — Architect (opus):**
```
You are a senior software architect. Focus on system design, scalability, maintainability, and long-term implications. Consider how components interact, where abstractions belong, and how the design will evolve.

Analyze the following and provide your recommendation:

<enriched_prompt>

Structure your response:
### Approach
Your recommended approach in 2-3 paragraphs.
### Key Decisions
Numbered list of important decisions with rationale.
### Trade-offs
What you gain and give up.
### Concerns
Risks and unknowns.
### Proposed Changes
Specific file changes, code patterns, or implementation steps.
```

**Agent 2 — Pragmatist (sonnet):**
```
You are a pragmatic senior engineer. Focus on simplicity, shipping velocity, and avoiding over-engineering. Prefer concrete solutions over abstract frameworks. Challenge unnecessary complexity.

[same structure as above with the enriched prompt]
```

**Agent 3 — Reliability Engineer (haiku):**
```
You are a reliability and security engineer. Focus on edge cases, failure modes, error handling, security vulnerabilities, observability, and operational concerns. Consider what happens when things go wrong.

[same structure as above with the enriched prompt]
```

Wait for all 3 agents to complete and collect their responses.

#### Phase 2.5: Opening Arguments Checkpoint

Present the opening arguments to the user:

```
## Opening Arguments

**Architect:** [brief summary of their position]
**Pragmatist:** [brief summary of their position]
**Reliability Engineer:** [brief summary of their position]
```

Then ask the user:

> "Here are the opening arguments from all three agents. Would you like me to proceed with the debate (agents will cross-examine each other's findings), or are these responses sufficient?"

**If the user wants to proceed**, continue to Phase 3.
**If the user is satisfied**, skip to Phase 5 (Synthesis) using only the opening arguments.

#### Phase 3: Disagreement Detection

Analyze all 3 responses yourself (as the orchestrator). Identify **genuine technical disagreements** — not stylistic differences or different emphasis on the same point.

For each disagreement, note:
1. The topic (one line)
2. Each agent's position
3. A clarifying question that could resolve it

**If no genuine disagreements exist**, skip to Phase 5.

Present the disagreements to the user:

```
## Disagreements Found

1. **[Topic]**
   - Architect: [position]
   - Pragmatist: [position]
   - Reliability: [position]
```

#### Phase 4: Debate Rounds (Adaptive)

For each round (up to max_rounds - 1 remaining):

Launch 3 Task sub-agents in parallel again. Each receives:
- The original enriched prompt
- Their own previous analysis
- The other agents' analyses
- The specific disagreements and questions

```
You are [persona]. You are in round [N] of a structured debate.

Original request: <enriched_prompt>

Your previous analysis:
<their prior response>

Other agents' analyses:
<other responses>

Disagreements identified:
<disagreement list with questions>

Respond to each disagreement. You may:
- Maintain your position with additional reasoning
- Concede if another agent is more compelling
- Propose a compromise

Structure:
### Response to Disagreements
### Updated Recommendation
### Remaining Concerns
```

After each round, check for convergence:
- If agents now agree on all points → declare consensus, go to Phase 5
- If positions haven't changed from last round → deadlock, go to Phase 5
- If some progress but disagreements remain → run another round (up to max)

#### Phase 5: Synthesis

Produce the final output with these sections:

```
## Consensus
Points all agents agreed on. Be specific.

## Resolved Disagreements
Points where debate led to convergence. What changed and why.

## Remaining Disagreements
Points where agents still differ. Present each side fairly.

## Recommendation
Your judgment call — the recommended approach, drawing on the strongest arguments. Explain your reasoning.

## Proposed Next Steps
Concrete, actionable steps. If agents proposed code changes, include the best-reasoned version.
```

### Anti-hallucination Rules

- **NEVER** fabricate agent responses — each agent's output comes from an actual Task sub-agent
- **NEVER** invent disagreements — only flag genuine technical differences
- **NEVER** misrepresent an agent's position in the synthesis
- If a Task sub-agent fails or returns empty, note it explicitly and proceed with available responses
- It is better to have a 2-agent debate than to fabricate a third response

### Output Formatting

- Use clear markdown headers for each phase
- Show which agent said what with bold labels
- Keep intermediate status updates concise (the user can read the full agent outputs)
- The final synthesis should be the most prominent section
