"""Eval: dedup prompt quality.

Runs the real dedup prompt against the LLM with fixture data and scores the output.
"""

from __future__ import annotations

import pytest

from agent_debate.orchestrator import Orchestrator
from agent_debate.prompts import build_dedup_prompt
from agent_debate.types import AgentResponse

from .conftest import call_llm
from .scoring import (
    score_agent_refs,
    score_disagreement_detected,
    score_has_findings,
    score_no_duplicates,
    score_valid_json,
    score_valid_severities,
)

pytestmark = [pytest.mark.eval, pytest.mark.anyio]


async def test_dedup_quality(
    agent_responses: list[AgentResponse],
    user_prompt: str,
    langfuse_client,
    eval_run_id: str,
    commit_sha: str,
):
    # Build the real prompt
    prompt = build_dedup_prompt(user_prompt, agent_responses)

    # Call the LLM
    raw, usage = await call_llm(prompt, model="haiku")

    # Parse using existing logic
    findings, disagreements = Orchestrator._parse_dedup_response(raw)

    # Score
    valid_ids = {r.agent_id for r in agent_responses}
    scores = [
        score_valid_json(raw),
        score_has_findings(findings),
        score_agent_refs(findings, valid_ids),
        score_valid_severities(findings),
        score_disagreement_detected(disagreements),
        score_no_duplicates(findings),
    ]

    # Log to Langfuse
    trace = langfuse_client.trace(
        name="eval:dedup",
        input=prompt,
        output=raw,
        metadata={
            "eval_run_id": eval_run_id,
            "commit_sha": commit_sha,
            "model": "haiku",
            "findings_count": len(findings),
            "disagreements_count": len(disagreements),
        },
    )
    trace.generation(
        name="dedup_call",
        model="haiku",
        input=prompt,
        output=raw,
        usage=usage,
    )
    for name, value, comment in scores:
        trace.score(name=name, value=value, comment=comment)

    # Print scores for visibility in pytest output
    for name, value, comment in scores:
        print(f"  {name}: {value:.2f} — {comment}")

    # Assert minimum bar
    for name, value, comment in scores:
        assert value >= 0.5, f"Score {name} too low: {value} ({comment})"
