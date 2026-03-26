"""Pure scoring functions for eval tests.

Each function returns a (score_name, value, comment) tuple.
Values are floats in [0.0, 1.0].
"""

from __future__ import annotations

import re

from agent_debate.orchestrator import Orchestrator
from agent_debate.types import Disagreement, Finding

Score = tuple[str, float, str]


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


# --- Synthesis scores ---

_REQUIRED_SECTIONS = [
    "### Key Findings",
    "### Disagreements",
    "### Recommendation",
    "### Next Steps",
]


def score_has_sections(text: str) -> Score:
    """Check for required markdown sections in synthesis output."""
    found = [s for s in _REQUIRED_SECTIONS if s.lower() in text.lower()]
    ratio = len(found) / len(_REQUIRED_SECTIONS)
    missing = [s for s in _REQUIRED_SECTIONS if s.lower() not in text.lower()]
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
    """Extract content under a ### header until the next ### or end."""
    pattern = re.compile(
        rf"###\s+{re.escape(header)}\s*\n(.*?)(?=\n###\s|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(text)
    return match.group(1) if match else ""


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
