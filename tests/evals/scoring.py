"""Pure scoring functions for eval tests.

Each function returns a (score_name, value, comment) tuple.
Values are floats in [0.0, 1.0].
"""

from __future__ import annotations

import re

from agent_debate.orchestrator import Orchestrator
from agent_debate.types import Disagreement, Finding

Score = tuple[str, float, str]

# Token budgets for orchestrator calls (output tokens).
# Set at ~2x observed baseline to catch regressions without false positives.
TOKEN_BUDGETS = {
    "dedup_output": 1500,
    "synthesis_output": 3000,
    "total_orchestrator": 15000,
}


# --- Dedup scores ---


def score_valid_json(raw: str) -> Score:
    """Check whether a JSON object can be extracted from the raw response."""
    blob = Orchestrator._extract_json_object(raw)
    if blob is not None:
        return ("dedup/valid_json", 1.0, "JSON extracted successfully")
    return ("dedup/valid_json", 0.0, "No JSON object found in response")


def score_has_findings(findings: list[Finding]) -> Score:
    n = len(findings)
    if n > 0:
        return ("dedup/has_findings", 1.0, f"{n} findings extracted")
    return ("dedup/has_findings", 0.0, "No findings extracted")


def score_agent_refs(findings: list[Finding], valid_ids: set[str]) -> Score:
    """Check that all agent IDs referenced in findings are real."""
    if not findings:
        return ("dedup/agent_refs", 0.0, "No findings to check")
    total = 0
    valid = 0
    for f in findings:
        for agent in f.agents:
            total += 1
            if agent in valid_ids:
                valid += 1
    if total == 0:
        return ("dedup/agent_refs", 0.0, "No agent references in findings")
    ratio = valid / total
    return (
        "dedup/agent_refs",
        ratio,
        f"{valid}/{total} agent references are valid",
    )


def score_valid_severities(findings: list[Finding]) -> Score:
    """Check that all severity values are from the expected set."""
    allowed = {"critical", "important", "minor"}
    if not findings:
        return ("dedup/valid_severities", 0.0, "No findings to check")
    valid = sum(1 for f in findings if f.severity in allowed)
    ratio = valid / len(findings)
    return (
        "dedup/valid_severities",
        ratio,
        f"{valid}/{len(findings)} have valid severity",
    )


def score_disagreement_detected(disagreements: list[Disagreement]) -> Score:
    """Check that at least one disagreement was identified.

    The auth fixtures contain a clear JWT-vs-sessions disagreement.
    """
    if disagreements:
        topics = ", ".join(d.topic for d in disagreements)
        return (
            "dedup/disagreement_detected",
            1.0,
            f"Found {len(disagreements)} disagreement(s): {topics}",
        )
    return ("dedup/disagreement_detected", 0.0, "No disagreements detected")


def _jaccard(a: str, b: str) -> float:
    """Word-level Jaccard similarity between two strings."""
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def score_no_duplicates(findings: list[Finding], threshold: float = 0.7) -> Score:
    """Check that finding topics are sufficiently distinct."""
    if len(findings) <= 1:
        return ("dedup/no_duplicates", 1.0, "0-1 findings, no duplicates possible")
    for i, a in enumerate(findings):
        for b in findings[i + 1 :]:
            sim = _jaccard(a.topic, b.topic)
            if sim >= threshold:
                return (
                    "dedup/no_duplicates",
                    0.0,
                    f"Duplicate topics: '{a.topic}' ~ '{b.topic}' (Jaccard={sim:.2f})",
                )
    return ("dedup/no_duplicates", 1.0, f"All {len(findings)} topics are distinct")


def score_disagreement_quality(
    disagreements: list[Disagreement],
    expected_terms: list[list[str]],
) -> Score:
    """Check that detected disagreements capture the expected conflict sides.

    expected_terms is a list of term groups, e.g. [["jwt", "token"], ["session", "cookie"]].
    Each group represents one side of the expected disagreement.
    """
    if not expected_terms:
        return ("dedup/disagreement_quality", 1.0, "No expected terms to check")

    all_text = " ".join(
        d.topic + " " + " ".join(d.positions.values())
        for d in disagreements
    ).lower()

    sides_found = 0
    for term_group in expected_terms:
        if any(term in all_text for term in term_group):
            sides_found += 1

    ratio = sides_found / len(expected_terms)
    return (
        "dedup/disagreement_quality",
        ratio,
        f"{sides_found}/{len(expected_terms)} disagreement sides captured",
    )


def score_severity_distribution(findings: list[Finding]) -> Score:
    """Check that at least one finding has critical or important severity."""
    if not findings:
        return ("dedup/severity_distribution", 0.0, "No findings to check")
    has_significant = any(f.severity in {"critical", "important"} for f in findings)
    if has_significant:
        dist = {}
        for f in findings:
            dist[f.severity] = dist.get(f.severity, 0) + 1
        dist_str = ", ".join(f"{k}={v}" for k, v in sorted(dist.items()))
        return ("dedup/severity_distribution", 1.0, f"Distribution: {dist_str}")
    return (
        "dedup/severity_distribution",
        0.0,
        "All findings are minor — expected at least one critical/important",
    )


def score_finding_attribution(
    findings: list[Finding],
    attribution_map: dict[str, str],
) -> Score:
    """Check that findings attribute topics to the correct agents.

    attribution_map maps keywords to expected agent IDs,
    e.g. {"jwt": "architect", "session": "pragmatist"}.
    """
    if not attribution_map:
        return ("dedup/finding_attribution", 1.0, "No attribution map to check")

    checked = 0
    correct = 0
    for keyword, expected_agent in attribution_map.items():
        for f in findings:
            topic_and_desc = (f.topic + " " + f.description).lower()
            if keyword in topic_and_desc and expected_agent in f.agents:
                checked += 1
                correct += 1
                break
            elif keyword in topic_and_desc:
                checked += 1
                break

    if checked == 0:
        return ("dedup/finding_attribution", 1.0, "No matching findings to check")
    ratio = correct / checked
    return (
        "dedup/finding_attribution",
        ratio,
        f"{correct}/{checked} findings correctly attributed",
    )


# --- Token efficiency scores ---


def score_token_budget(
    usage: dict[str, int] | None,
    max_output: int,
    prefix: str,
) -> Score:
    """Check that output tokens are within budget. Includes actual counts in comment."""
    name = f"{prefix}/output_tokens"
    if usage is None:
        return (name, 1.0, "No usage data available")
    actual = usage.get("output_tokens", 0)
    if actual <= max_output:
        return (name, 1.0, f"{actual} tokens (budget: {max_output})")
    ratio = max(0.0, max_output / actual)
    return (name, round(ratio, 4), f"{actual} tokens exceeds budget {max_output}")


def score_total_orchestrator_tokens(
    dedup_usage: dict[str, int] | None,
    synthesis_usage: dict[str, int] | None,
    max_total: int,
) -> Score:
    """Check combined dedup+synthesis token usage against a total budget."""
    dedup_total = (dedup_usage or {}).get("total_tokens", 0)
    synthesis_total = (synthesis_usage or {}).get("total_tokens", 0)
    actual = dedup_total + synthesis_total
    if actual <= max_total:
        return (
            "orchestrator/total_tokens",
            1.0,
            f"{actual} tokens (dedup={dedup_total}, synthesis={synthesis_total}, budget={max_total})",
        )
    ratio = max(0.0, max_total / actual)
    return (
        "orchestrator/total_tokens",
        round(ratio, 4),
        f"{actual} tokens exceeds budget {max_total} (dedup={dedup_total}, synthesis={synthesis_total})",
    )


# --- Synthesis scores ---

_REQUIRED_SECTIONS = ["Key Findings", "Disagreements", "Recommendation", "Next Steps"]


def _section_pattern(name: str) -> re.Pattern:
    """Match a markdown heading at any level (# through ####) with the given name."""
    return re.compile(rf"^#{{1,4}}\s+{re.escape(name)}", re.MULTILINE | re.IGNORECASE)


def score_has_sections(text: str) -> Score:
    """Check for required markdown sections in synthesis output."""
    found = [s for s in _REQUIRED_SECTIONS if _section_pattern(s).search(text)]
    missing = [s for s in _REQUIRED_SECTIONS if not _section_pattern(s).search(text)]
    ratio = len(found) / len(_REQUIRED_SECTIONS)
    if missing:
        comment = f"Missing: {', '.join(missing)}"
    else:
        comment = "All sections present"
    return ("synthesis/has_sections", ratio, comment)


def score_agent_references(text: str, agent_ids: set[str]) -> Score:
    """Check that the synthesis references agents by name."""
    if not agent_ids:
        return ("synthesis/agent_references", 0.0, "No agent IDs to check")
    found = [aid for aid in agent_ids if aid.lower() in text.lower()]
    ratio = len(found) / len(agent_ids)
    return (
        "synthesis/agent_references",
        ratio,
        f"Referenced {len(found)}/{len(agent_ids)} agents",
    )


_HEDGE_PHRASES = re.compile(
    r"(it depends|either could work|both are valid|no clear winner|"
    r"there is no right answer|up to you|depends on your preference)",
    re.IGNORECASE,
)
_DIRECTIVE_VERBS = re.compile(
    r"\b(use|implement|choose|recommend|adopt|go with|prefer|select)\b",
    re.IGNORECASE,
)


def _extract_section(text: str, header: str) -> str:
    """Extract content under a markdown header until the next header of same/higher level or end."""
    pattern = re.compile(
        rf"^(#{{1,4}})\s+{re.escape(header)}\s*\n(.*?)(?=\n#{{1,4}}\s|\Z)",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(text)
    return match.group(2) if match else ""


def score_clear_recommendation(text: str) -> Score:
    """Check that the Recommendation section takes a clear position."""
    rec = _extract_section(text, "Recommendation")
    if not rec.strip():
        return (
            "synthesis/clear_recommendation",
            0.0,
            "No Recommendation section found",
        )
    has_hedge = bool(_HEDGE_PHRASES.search(rec))
    has_directive = bool(_DIRECTIVE_VERBS.search(rec))
    if has_hedge:
        return (
            "synthesis/clear_recommendation",
            0.0,
            f"Recommendation contains hedging language",
        )
    if not has_directive:
        return (
            "synthesis/clear_recommendation",
            0.5,
            "No directive verbs found in recommendation",
        )
    return ("synthesis/clear_recommendation", 1.0, "Clear recommendation with directive language")


def score_word_count(text: str, min_words: int = 200, max_words: int = 2000) -> Score:
    """Check that synthesis output is a reasonable length."""
    count = len(text.split())
    if min_words <= count <= max_words:
        return ("synthesis/word_count", 1.0, f"{count} words (in range)")
    return (
        "synthesis/word_count",
        0.0,
        f"{count} words (expected {min_words}-{max_words})",
    )


def score_balance(text: str, agent_positions: dict[str, list[str]]) -> Score:
    """Check that each agent's core position is represented in the synthesis.

    agent_positions maps agent IDs to keywords that characterize their position,
    e.g. {"architect": ["jwt", "token"], "pragmatist": ["session", "cookie"]}.
    """
    if not agent_positions:
        return ("synthesis/balance", 1.0, "No agent positions to check")

    text_lower = text.lower()
    represented = 0
    details = []
    for agent_id, keywords in agent_positions.items():
        has_keyword = any(kw in text_lower for kw in keywords)
        if has_keyword:
            represented += 1
            details.append(f"{agent_id}=yes")
        else:
            details.append(f"{agent_id}=no")

    ratio = represented / len(agent_positions)
    return (
        "synthesis/balance",
        ratio,
        f"{represented}/{len(agent_positions)} positions represented ({', '.join(details)})",
    )


async def score_faithfulness(
    agent_responses_text: str,
    synthesis_text: str,
    call_llm_fn,
) -> Score:
    """LLM-as-judge: check that synthesis is faithful to agent responses.

    call_llm_fn should be an async function with signature (prompt, model) -> (text, usage).
    Uses Sonnet for more reliable judging.
    """
    # Truncate agent responses to keep judge prompt focused
    truncated = agent_responses_text[:6000] if len(agent_responses_text) > 6000 else agent_responses_text

    judge_prompt = f"""\
You are a strict evaluator checking whether a synthesis is faithful to the source material.

## Source: Agent Responses
{truncated}

## Output: Synthesis
{synthesis_text}

## Evaluation Criteria
A synthesis is FAITHFUL if:
1. Every claim attributed to a specific agent is something that agent actually said
2. No agent is credited with a position they did not take
3. Each agent's core recommendation is mentioned (not silently dropped)

Minor differences in wording are OK. The synthesis may add its own recommendation — that is fine. \
Only flag clear misattributions or omitted core positions.

Respond with ONLY this JSON (no markdown, no explanation):
{{"is_faithful": true, "issues": []}}
or
{{"is_faithful": false, "issues": ["specific issue 1", "specific issue 2"]}}"""

    raw, _ = await call_llm_fn(judge_prompt, model="haiku")

    # Parse judge response
    try:
        import json

        blob = Orchestrator._extract_json_object(raw)
        if blob:
            result = json.loads(blob)
        else:
            result = json.loads(raw)
        is_faithful = result.get("is_faithful", False)
        issues = result.get("issues", [])
    except (json.JSONDecodeError, KeyError):
        return (
            "synthesis/faithfulness",
            0.5,
            f"Could not parse judge response: {raw[:200]}",
        )

    if is_faithful:
        return ("synthesis/faithfulness", 1.0, "Synthesis is faithful to agent responses")
    issue_str = "; ".join(str(i) for i in issues) if issues else "unfaithful (no details)"
    return ("synthesis/faithfulness", 0.0, f"Faithfulness issues: {issue_str}")
