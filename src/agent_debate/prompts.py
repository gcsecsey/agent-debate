"""Prompt templates for the multi-perspective analysis system."""

from __future__ import annotations

import re

from .types import AgentResponse, Disagreement


# --- Round 1: Independent analysis ---

ROUND_1_TEMPLATE = """\
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


def build_round1_prompt(user_prompt: str) -> str:
    """Build the prompt for an agent's first-round independent analysis."""
    return ROUND_1_TEMPLATE.format(prompt=user_prompt)


# --- Helpers ---


def _format_response_simple(response: AgentResponse) -> str:
    """Format an agent response for judge-facing prompts."""
    return f"**{response.agent_id}**:\n\n{response.content}"


def _format_responses(responses: list[AgentResponse]) -> str:
    """Format all responses for judge-facing prompts."""
    return "\n\n---\n\n".join(_format_response_simple(r) for r in responses)


def _summarize_prompt(prompt: str, max_chars: int = 200) -> str:
    """Truncate prompt to a short summary for judge-facing prompts."""
    if len(prompt) <= max_chars:
        return prompt
    return prompt[:max_chars] + "..."


_STRUCTURED_HEADERS = re.compile(
    r"^###\s+(Key Decisions|Trade-offs|Concerns)\s*$",
    re.MULTILINE,
)
_ANY_H3 = re.compile(r"^###\s+", re.MULTILINE)


def _extract_structured_sections(content: str) -> str:
    """Extract Key Decisions, Trade-offs, and Concerns sections from a response.

    Drops the Approach (narrative prose) and Proposed Changes (code blocks)
    sections to reduce token count.  Falls back to full content when no
    recognised headers are found (e.g. debate-round responses).
    """
    matches = list(_STRUCTURED_HEADERS.finditer(content))
    if not matches:
        return content

    parts: list[str] = []
    for match in matches:
        start = match.start()
        # Find where the next ### header starts (any header, not just ours)
        rest = content[match.end():]
        next_h3 = _ANY_H3.search(rest)
        if next_h3:
            end = match.end() + next_h3.start()
        else:
            end = len(content)
        parts.append(content[start:end].strip())

    return "\n\n".join(parts)


# --- Deduplication ---

DEDUP_TEMPLATE = """\
You are analyzing multiple AI agent responses to extract and deduplicate findings.

## Original Request (summary)

{prompt_summary}

## Agent Responses

{responses}

## Instructions

Your job is to:
1. Extract every distinct finding, recommendation, or concern from all agents
2. Merge findings that say the same thing in different words
3. Tag each finding with which agents identified it and a severity level
4. Identify any stark contradictions where agents recommend opposite approaches

Return your analysis as a JSON object with this structure:

```json
{{
  "findings": [
    {{
      "topic": "Brief title of the finding",
      "description": "One-paragraph description of the finding or recommendation",
      "agents": ["agent_id_1", "agent_id_2"],
      "severity": "critical|important|minor"
    }}
  ],
  "stark_disagreements": [
    {{
      "topic": "Brief description of the contradiction",
      "positions": {{
        "agent_id": "One-line summary of their position"
      }}
    }}
  ]
}}
```

Guidelines:
- A finding is "critical" if ignoring it would likely cause a bug, security issue, \
or significant architectural problem
- A finding is "important" if it meaningfully affects quality, performance, or maintainability
- A finding is "minor" if it's a nice-to-have or stylistic preference
- Only flag stark_disagreements for genuine contradictions (agent A says do X, \
agent B says do the opposite), NOT for different emphasis on the same point
- If agents substantially agree, return an empty stark_disagreements array

IMPORTANT: Return ONLY the JSON object, no other text.
"""


def build_dedup_prompt(
    user_prompt: str,
    responses: list[AgentResponse],
) -> str:
    """Build the prompt for the orchestrator to deduplicate findings."""
    # Extract only structured sections from each response to reduce tokens
    trimmed = [
        AgentResponse(
            agent_id=r.agent_id,
            provider=r.provider,
            model=r.model,
            round_number=r.round_number,
            content=_extract_structured_sections(r.content),
        )
        for r in responses
    ]
    return DEDUP_TEMPLATE.format(
        prompt_summary=_summarize_prompt(user_prompt),
        responses=_format_responses(trimmed),
    )


# --- Targeted debate (only when stark disagreements exist) ---

TARGETED_DEBATE_TEMPLATE = """\
You are responding to a specific contradiction identified between your analysis \
and another agent's analysis.

## Original Request (summary)

{prompt_summary}

## Your Previous Position

{own_position}

## The Contradiction

{disagreement}

## Other Agents' Positions

{other_positions}

## Instructions

Make your strongest case for your position in 2-3 paragraphs. Be specific and \
reference concrete implementation details. If, after seeing the other positions, \
you believe your original position was wrong, say so directly and explain why.

Do NOT hedge or seek artificial compromise — give your honest technical judgment.
"""


def build_targeted_debate_prompt(
    user_prompt: str,
    own_response: AgentResponse,
    disagreement: Disagreement,
    other_responses: list[AgentResponse],
) -> str:
    """Build the prompt for a targeted debate round."""
    positions_text = "\n".join(
        f"- {aid}: {pos}" for aid, pos in disagreement.positions.items()
        if aid != own_response.agent_id
    )

    own_position = disagreement.positions.get(own_response.agent_id, "")

    return TARGETED_DEBATE_TEMPLATE.format(
        prompt_summary=_summarize_prompt(user_prompt),
        own_position=own_position,
        disagreement=f"**{disagreement.topic}**\n"
        + "\n".join(
            f"- {aid}: {pos}" for aid, pos in disagreement.positions.items()
        ),
        other_positions=positions_text,
    )


# --- Synthesis ---

SYNTHESIS_TEMPLATE = """\
You are synthesizing a multi-perspective analysis into a clear, actionable summary.

## Original Request

{prompt}

## Deduplicated Findings

The findings below were extracted from {agent_count} agent analyses.

{findings}

## Disagreements

{disagreements}

{debate_section}

## Instructions

Produce a clear, well-structured synthesis. Include:

### Key Findings
The most important findings, ordered by severity. For each, note which agents \
flagged it and why it matters.

### Disagreements
If agents disagreed on anything, present each side fairly with their reasoning. \
If a targeted debate was run, incorporate those arguments.

### Recommendation
Your judgment call — the recommended approach, drawing on the strongest \
arguments. Explain your reasoning.

### Next Steps
Concrete, actionable steps the user can take. If agents proposed code \
changes, include the most well-reasoned version.
"""


def build_synthesis_prompt(
    user_prompt: str,
    responses: list[AgentResponse],
    findings_text: str,
    disagreements: list[Disagreement],
    debate_responses: list[AgentResponse] | None = None,
) -> str:
    """Build the prompt for final synthesis."""
    disagreements_text = (
        "None — agents substantially agreed."
        if not disagreements
        else "\n\n".join(
            f"**{d.topic}**\n"
            + "\n".join(f"  - {aid}: {pos}" for aid, pos in d.positions.items())
            for d in disagreements
        )
    )

    debate_section = ""
    if debate_responses:
        debate_section = (
            "## Targeted Debate Responses\n\n"
            + _format_responses(debate_responses)
        )

    return SYNTHESIS_TEMPLATE.format(
        prompt=user_prompt,
        agent_count=len(responses),
        findings=findings_text,
        disagreements=disagreements_text,
        debate_section=debate_section,
    )
