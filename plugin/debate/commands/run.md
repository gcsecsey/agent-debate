---
description: Run a multi-perspective analysis to get diverse AI perspectives on a coding question
argument-hint: <prompt> [--providers top|fast|claude:opus,codex,gemini] [--max-rounds 1]
allowed-tools: Task, Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
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

## Instructions

### Step 1: Check for agent-debate package

Try to detect if the `agent-debate` Python package is installed:

```bash
command -v agent-debate && agent-debate discover
```

**If agent-debate is available**, use **Package Mode** (Step 2A).
**If not available**, use **Built-in Mode** (Step 2B).

---

### Step 2A: Package Mode

Run the analysis via the Python package. This supports multi-provider debates (Claude, Codex, Gemini, Amp).

```bash
agent-debate run "<prompt>" --providers "<providers>" --max-rounds <max_rounds> --cwd "$(pwd)"
```

Read the output and present it to the user. Done.

---

### Step 2B: Built-in Mode (Task Sub-Agents)

Run the analysis using Claude Code's built-in Task sub-agents. This is Claude-only but requires no dependencies.

#### Phase 1: Gather Context

Before fanning out, gather relevant context from the codebase to enrich the prompt:

1. Read any files the user referenced in their prompt
2. If the prompt mentions recent changes, run `git log --oneline -10` and `git diff HEAD~1` to gather context
3. If the prompt mentions a specific module/directory, use Glob to find relevant files and read key ones

Build an **enriched prompt** that includes the user's original question plus the gathered context.

#### Phase 2: Independent Analysis (Fan Out)

Launch **3 Task sub-agents in parallel**, each with a different model. All 3 Tasks MUST be launched in a single message to run in parallel.

Each agent gets the same prompt — no persona or role assignment. Let each model analyze independently:

```
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

Use different models for each agent (e.g., opus, sonnet, haiku) to get diverse perspectives through model diversity rather than artificial role assignment.

Wait for all 3 agents to complete and collect their responses.

#### Phase 3: Deduplicate Findings

Analyze all 3 responses yourself (as the orchestrator). Your job is to:

1. **Extract** every distinct finding, recommendation, or concern from all agents
2. **Merge** findings that say the same thing in different words
3. **Tag** each finding with severity (critical/important/minor) and which agents flagged it
4. **Identify contradictions** — only genuine ones where agents recommend opposite approaches

Present the deduplicated findings:

```
## Deduplicated Findings

### Critical
- [Finding] (flagged by: claude:opus, claude:sonnet)

### Important
- [Finding] (flagged by: all agents)

### Minor
- [Finding] (flagged by: claude:haiku)
```

**If no stark contradictions**, skip to Phase 5.

#### Phase 4: Targeted Debate (only if contradictions found)

If agents genuinely contradict each other, run **one** targeted debate round.

Launch 3 Task sub-agents in parallel. Each receives:
- The original enriched prompt
- Their own previous analysis
- The specific contradiction(s) to address
- The other agents' positions

```
A contradiction was identified between your analysis and other agents.

Original request: <enriched_prompt>

Your previous analysis:
<their prior response>

The contradiction:
<description of the stark disagreement and each agent's position>

Make your strongest case for your position in 2-3 paragraphs. Be specific and reference concrete implementation details. If you believe your original position was wrong after seeing other arguments, say so directly.
```

Collect responses. Do NOT run additional rounds.

#### Phase 5: Synthesis

Produce the final output:

```
## Key Findings
The most important findings, ordered by severity. For each, note which agents flagged it and why it matters.

## Disagreements
If agents disagreed, present each side fairly. If a debate round was run, incorporate those arguments.

## Recommendation
Your judgment call — the recommended approach, drawing on the strongest arguments. Explain your reasoning.

## Next Steps
Concrete, actionable steps. If agents proposed code changes, include the best-reasoned version.
```

### Anti-hallucination Rules

- **NEVER** fabricate agent responses — each agent's output comes from an actual Task sub-agent
- **NEVER** invent disagreements — only flag genuine technical contradictions
- **NEVER** misrepresent an agent's position in the synthesis
- If a Task sub-agent fails or returns empty, note it explicitly and proceed with available responses
- It is better to have a 2-agent analysis than to fabricate a third response

### Output Formatting

- Use clear markdown headers for each phase
- Show which agent said what with bold labels (use provider:model names, e.g. "claude:opus")
- Keep intermediate status updates concise (the user can read the full agent outputs)
- The final synthesis should be the most prominent section
