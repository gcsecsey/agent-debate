"""Eval: synthesis prompt quality.

Runs the full chain (dedup -> synthesis) against the LLM and scores the synthesis output.
"""

from __future__ import annotations

import pytest

from agent_debate.orchestrator import Orchestrator
from agent_debate.prompts import build_dedup_prompt, build_synthesis_prompt
from agent_debate.types import AgentResponse

from .conftest import call_llm
from .scoring import (
    Score,
    score_agent_references,
    score_clear_recommendation,
    score_has_sections,
    score_word_count,
)

pytestmark = [pytest.mark.eval, pytest.mark.anyio]


async def test_synthesis_quality(
    agent_responses: list[AgentResponse],
    user_prompt: str,
    langfuse_client,
    eval_run_id: str,
    commit_sha: str,
):
    # Phase 1: Run dedup to get real findings/disagreements
    dedup_prompt = build_dedup_prompt(user_prompt, agent_responses)
    dedup_raw, dedup_usage = await call_llm(dedup_prompt, model="haiku")
    findings, disagreements = Orchestrator._parse_dedup_response(dedup_raw)

    # Format findings for synthesis (same logic as orchestrator._synthesize)
    findings_lines = []
    for f in findings:
        agents = ", ".join(f.agents)
        findings_lines.append(
            f"- **[{f.severity.upper()}]** {f.topic} (flagged by: {agents})\n"
            f"  {f.description}"
        )
    findings_text = (
        "\n\n".join(findings_lines) if findings_lines else "No findings extracted."
    )

    # Phase 2: Run synthesis
    synthesis_prompt = build_synthesis_prompt(
        user_prompt=user_prompt,
        responses=agent_responses,
        findings_text=findings_text,
        disagreements=disagreements,
    )
    synthesis_raw, synthesis_usage = await call_llm(synthesis_prompt, model="sonnet")

    # Score
    agent_ids = {r.agent_id for r in agent_responses}
    scores: list[Score] = [
        score_has_sections(synthesis_raw),
        score_agent_references(synthesis_raw, agent_ids),
        score_clear_recommendation(synthesis_raw),
        score_word_count(synthesis_raw),
    ]

    # Log to Langfuse
    trace = langfuse_client.trace(
        name="eval:synthesis",
        input=user_prompt,
        output=synthesis_raw,
        metadata={
            "eval_run_id": eval_run_id,
            "commit_sha": commit_sha,
            "dedup_model": "haiku",
            "synthesis_model": "sonnet",
            "findings_count": len(findings),
            "disagreements_count": len(disagreements),
        },
    )
    trace.generation(
        name="dedup_call",
        model="haiku",
        input=dedup_prompt,
        output=dedup_raw,
        usage=dedup_usage,
    )
    trace.generation(
        name="synthesis_call",
        model="sonnet",
        input=synthesis_prompt,
        output=synthesis_raw,
        usage=synthesis_usage,
    )
    for name, value, comment in scores:
        trace.score(name=name, value=value, comment=comment)

    # Print scores for visibility
    for name, value, comment in scores:
        print(f"  {name}: {value:.2f} — {comment}")

    # Assert minimum bar
    for name, value, comment in scores:
        assert value >= 0.5, f"Score {name} too low: {value} ({comment})"
