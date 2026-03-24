"""Prompt templates for the debate system."""

from __future__ import annotations

from .types import AgentResponse, Disagreement

# --- Default personas ---

DEFAULT_PERSONAS = [
    {
        "name": "Architect",
        "prompt": (
            "You are a senior software architect. Focus on system design, "
            "scalability, maintainability, and long-term implications. "
            "Consider how components interact, where abstractions belong, "
            "and how the design will evolve over time."
        ),
    },
    {
        "name": "Pragmatist",
        "prompt": (
            "You are a pragmatic senior engineer. Focus on simplicity, "
            "shipping velocity, and avoiding over-engineering. Prefer "
            "concrete solutions over abstract frameworks. Challenge "
            "unnecessary complexity and premature abstraction."
        ),
    },
    {
        "name": "Reliability Engineer",
        "prompt": (
            "You are a reliability and security engineer. Focus on edge "
            "cases, failure modes, error handling, security vulnerabilities, "
            "observability, and operational concerns. Consider what happens "
            "when things go wrong."
        ),
    },
]


def get_persona(index: int, override: str | None = None) -> str:
    """Get persona prompt for an agent by index, with optional override."""
    if override:
        return override
    persona = DEFAULT_PERSONAS[index % len(DEFAULT_PERSONAS)]
    return persona["prompt"]


def get_persona_name(index: int) -> str:
    """Get persona display name by index."""
    return DEFAULT_PERSONAS[index % len(DEFAULT_PERSONAS)]["name"]


# --- Round 1: Independent analysis ---

ROUND_1_TEMPLATE = """\
{persona}

Analyze the following request and provide your recommendation.

## Request

{prompt}

## Instructions

Provide a thorough, structured analysis. Be specific — reference file paths, \
function names, and concrete implementation details where relevant.

Structure your response with these sections:

### Approach
Your recommended approach in 2-3 paragraphs.

### Key Decisions
Numbered list of the most important design/implementation decisions, \
each with a brief rationale.

### Trade-offs
What are you gaining and giving up with this approach?

### Concerns
What could go wrong? What are the risks or unknowns?

### Proposed Changes
If applicable, describe specific file changes, code patterns, or \
implementation steps. Include code snippets where helpful.
"""


def build_round1_prompt(user_prompt: str, persona: str) -> str:
    """Build the prompt for an agent's first-round independent analysis."""
    return ROUND_1_TEMPLATE.format(prompt=user_prompt, persona=persona)


# --- Round 2+: Debate ---

DEBATE_ROUND_TEMPLATE = """\
{persona}

You are in round {round_number} of a structured debate with other AI agents.

## Original Request

{prompt}

## Your Previous Analysis

{own_prior_response}

## Other Agents' Analyses

{other_responses}

## Disagreements Identified

The orchestrator identified these specific points of disagreement:

{disagreements}

## Instructions

Respond to each disagreement point above. For each one, you may:
- **Maintain** your position with additional reasoning or evidence
- **Concede** if another agent makes a compelling argument
- **Propose a compromise** that addresses both perspectives

Be specific and constructive. Reference concrete implementation details.

Structure your response:

### Response to Disagreements
Address each disagreement point by number.

### Updated Recommendation
Your revised recommendation (if anything changed). If unchanged, briefly restate why.

### Remaining Concerns
Any unresolved issues or new concerns raised by the debate.
"""


def build_debate_prompt(
    user_prompt: str,
    persona: str,
    own_prior: AgentResponse,
    other_responses: list[AgentResponse],
    disagreements: list[Disagreement],
    round_number: int,
) -> str:
    """Build the prompt for a debate round."""
    others_text = "\n\n---\n\n".join(
        f"**{r.agent_id}** ({r.persona}):\n\n{r.content}"
        for r in other_responses
    )

    disagreements_text = "\n\n".join(
        f"**{i + 1}. {d.topic}**\n"
        + "\n".join(f"  - {aid}: {pos}" for aid, pos in d.positions.items())
        + ("\n  Questions: " + "; ".join(d.questions) if d.questions else "")
        for i, d in enumerate(disagreements)
    )

    return DEBATE_ROUND_TEMPLATE.format(
        persona=persona,
        round_number=round_number,
        prompt=user_prompt,
        own_prior_response=own_prior.content,
        other_responses=others_text,
        disagreements=disagreements_text,
    )


# --- Disagreement detection ---

DISAGREEMENT_DETECTION_TEMPLATE = """\
You are analyzing multiple AI agent responses to identify genuine technical \
disagreements.

## Original Request

{prompt}

## Agent Responses

{responses}

## Instructions

Identify specific, actionable technical disagreements between the agents. \
Ignore:
- Stylistic differences in explanation
- Different emphasis on the same underlying point
- Complementary (non-conflicting) perspectives

For each genuine disagreement, provide:
1. A concise topic (one line)
2. Each agent's position (one line per agent)
3. One or two clarifying questions that could resolve the disagreement

Return your analysis as a JSON array. Each element should have this structure:
```json
{{
  "topic": "Brief description of the disagreement",
  "positions": {{
    "agent_id": "One-line summary of their position"
  }},
  "questions": ["Clarifying question 1", "Clarifying question 2"]
}}
```

If the agents substantially agree (no genuine technical disagreements), \
return an empty array: `[]`

IMPORTANT: Return ONLY the JSON array, no other text.
"""


def build_disagreement_prompt(
    user_prompt: str,
    responses: list[AgentResponse],
) -> str:
    """Build the prompt for the orchestrator to detect disagreements."""
    responses_text = "\n\n---\n\n".join(
        f"**{r.agent_id}** ({r.persona}):\n\n{r.content}"
        for r in responses
    )
    return DISAGREEMENT_DETECTION_TEMPLATE.format(
        prompt=user_prompt,
        responses=responses_text,
    )


# --- Synthesis ---

SYNTHESIS_TEMPLATE = """\
You are synthesizing a multi-agent debate into a clear, actionable summary \
for the user.

## Original Request

{prompt}

## Debate History

{debate_history}

## Remaining Disagreements

{disagreements}

## Instructions

Produce a clear, well-structured synthesis that helps the user make a decision. \
Include:

### Consensus
Points where all agents agreed. Be specific.

### Resolved Disagreements
Points where debate led to convergence. Explain what changed and why.

### Remaining Disagreements
Points where agents still differ. Present each side fairly with their reasoning.

### Recommendation
Your judgment call — the recommended approach, drawing on the strongest \
arguments from the debate. Explain your reasoning.

### Proposed Next Steps
Concrete, actionable steps the user can take. If agents proposed code \
changes, include the most well-reasoned version (or a synthesis of the best \
parts from each).
"""


def build_synthesis_prompt(
    user_prompt: str,
    all_responses: list[list[AgentResponse]],
    disagreements: list[Disagreement],
) -> str:
    """Build the prompt for final synthesis."""
    history_parts = []
    for round_num, round_responses in enumerate(all_responses, 1):
        round_label = "Independent Analysis" if round_num == 1 else f"Debate Round {round_num}"
        history_parts.append(f"## Round {round_num}: {round_label}\n")
        for r in round_responses:
            history_parts.append(f"**{r.agent_id}** ({r.persona}):\n\n{r.content}\n\n---\n")

    disagreements_text = "None — agents reached consensus." if not disagreements else "\n\n".join(
        f"**{d.topic}**\n"
        + "\n".join(f"  - {aid}: {pos}" for aid, pos in d.positions.items())
        for d in disagreements
    )

    return SYNTHESIS_TEMPLATE.format(
        prompt=user_prompt,
        debate_history="\n".join(history_parts),
        disagreements=disagreements_text,
    )
