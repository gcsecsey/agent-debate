"""Tests for prompt template generation."""

from agent_debate.prompts import (
    _extract_structured_sections,
    _summarize_prompt,
    _trim_to_paragraph_boundary,
    build_dedup_prompt,
    build_round1_prompt,
    build_synthesis_prompt,
    build_targeted_debate_prompt,
)
from agent_debate.types import AgentResponse, Disagreement


class TestRound1Prompt:
    def test_contains_user_prompt(self):
        result = build_round1_prompt("Review auth module")
        assert "Review auth module" in result

    def test_contains_structure_guidance(self):
        result = build_round1_prompt("Review auth module")
        assert "### Approach" in result
        assert "### Key Points" in result
        assert "### Concerns" in result

    def test_no_persona_assignment(self):
        result = build_round1_prompt("Review auth module")
        assert "You are a" not in result


class TestSummarizePrompt:
    def test_short_prompt_unchanged(self):
        assert _summarize_prompt("Short prompt") == "Short prompt"

    def test_long_prompt_truncated(self):
        long_prompt = "x" * 300
        result = _summarize_prompt(long_prompt)
        assert len(result) == 203  # 200 chars + "..."
        assert result.endswith("...")

    def test_exact_boundary(self):
        prompt = "x" * 200
        assert _summarize_prompt(prompt) == prompt


class TestExtractStructuredSections:
    def test_extracts_target_sections(self):
        content = (
            "### Approach\n\nSome narrative prose.\n\n"
            "### Key Decisions\n\n1. Use JWT tokens\n2. Add rate limiting\n\n"
            "### Trade-offs\n\nGaining security, losing simplicity.\n\n"
            "### Concerns\n\nMay break legacy clients.\n\n"
            "### Proposed Changes\n\n```python\ncode here\n```"
        )
        result = _extract_structured_sections(content)
        assert "### Key Decisions" in result
        assert "Use JWT tokens" in result
        assert "### Trade-offs" in result
        assert "### Concerns" in result
        assert "### Approach" not in result
        assert "### Proposed Changes" not in result
        assert "code here" not in result

    def test_fallback_for_unstructured_content(self):
        content = "Just some freeform text without any headers."
        assert _extract_structured_sections(content) == content

    def test_partial_headers(self):
        content = (
            "### Key Decisions\n\n1. Use JWT\n\n"
            "### Proposed Changes\n\nSome code"
        )
        result = _extract_structured_sections(content)
        assert "### Key Decisions" in result
        assert "Use JWT" in result
        assert "### Proposed Changes" not in result


class TestDedupPrompt:
    def _make_response(self, agent_id: str, content: str) -> AgentResponse:
        return AgentResponse(
            agent_id=agent_id,
            provider="claude",
            model="opus",
            round_number=1,
            content=content,
        )

    def test_contains_structured_sections(self):
        content = (
            "### Approach\n\nNarrative.\n\n"
            "### Key Decisions\n\n1. Decision A\n\n"
            "### Proposed Changes\n\nCode block"
        )
        responses = [self._make_response("a1", content)]
        result = build_dedup_prompt("Review auth", responses)
        assert "Decision A" in result
        assert "Narrative" not in result  # Approach section dropped

    def test_truncates_long_prompt(self):
        long_prompt = "x" * 300
        responses = [self._make_response("a1", "Analysis")]
        result = build_dedup_prompt(long_prompt, responses)
        assert "x" * 200 + "..." in result
        assert "x" * 300 not in result

    def test_contains_dedup_instructions(self):
        responses = [self._make_response("a1", "Analysis")]
        result = build_dedup_prompt("Review auth", responses)
        assert "deduplicate" in result.lower()
        assert "findings" in result
        assert "stark_disagreements" in result

    def test_contains_severity_guidance(self):
        responses = [self._make_response("a1", "Analysis")]
        result = build_dedup_prompt("Review auth", responses)
        assert "critical" in result
        assert "important" in result
        assert "minor" in result


class TestTargetedDebatePrompt:
    def _make_response(self, agent_id: str, content: str) -> AgentResponse:
        return AgentResponse(
            agent_id=agent_id,
            provider="claude",
            model="opus",
            round_number=1,
            content=content,
        )

    def test_contains_own_position(self):
        own = self._make_response("claude:opus", "My full analysis here")
        other = self._make_response("claude:sonnet", "Other analysis")
        disagreement = Disagreement(
            topic="JWT vs Sessions",
            positions={"claude:opus": "JWT", "claude:sonnet": "Sessions"},
        )
        result = build_targeted_debate_prompt(
            "Review auth",
            own,
            [disagreement],
            [other],
        )
        # Position summary is used, not full response content
        assert "JWT" in result
        assert "JWT vs Sessions" in result
        assert "Your Previous Positions" in result
        assert "My full analysis here" not in result

    def test_asks_for_strongest_case(self):
        own = self._make_response("claude:opus", "My analysis")
        disagreement = Disagreement(
            topic="REST vs gRPC",
            positions={"claude:opus": "REST", "claude:sonnet": "gRPC"},
        )
        result = build_targeted_debate_prompt(
            "Design API",
            own,
            [disagreement],
            [],
        )
        assert "strongest case" in result

    def test_no_position_tracking(self):
        own = self._make_response("claude:opus", "My analysis")
        disagreement = Disagreement(
            topic="REST vs gRPC",
            positions={"claude:opus": "REST"},
        )
        result = build_targeted_debate_prompt(
            "Design API",
            own,
            [disagreement],
            [],
        )
        assert "position_updates" not in result.lower()
        assert "Structured Position Updates" not in result

    def test_no_user_prompt_in_debate(self):
        own = self._make_response("claude:opus", "My analysis")
        disagreement = Disagreement(
            topic="Test",
            positions={"claude:opus": "Pos A"},
        )
        result = build_targeted_debate_prompt("Review auth module", own, [disagreement], [])
        assert "Original Request" not in result
        assert "Review auth module" not in result

    def test_multiple_disagreements(self):
        own = self._make_response("claude:opus", "My analysis")
        other = self._make_response("claude:sonnet", "Other analysis")
        d1 = Disagreement(
            topic="JWT vs Sessions",
            positions={"claude:opus": "JWT", "claude:sonnet": "Sessions"},
        )
        d2 = Disagreement(
            topic="REST vs gRPC",
            positions={"claude:opus": "REST", "claude:sonnet": "gRPC"},
        )
        d3 = Disagreement(
            topic="SQL vs NoSQL",
            positions={"claude:opus": "SQL", "claude:sonnet": "NoSQL"},
        )
        result = build_targeted_debate_prompt(
            "Design system",
            own,
            [d1, d2, d3],
            [other],
        )
        # All topics appear
        assert "JWT vs Sessions" in result
        assert "REST vs gRPC" in result
        assert "SQL vs NoSQL" in result
        # Numbered list
        assert "### 1." in result
        assert "### 2." in result
        assert "### 3." in result
        # Own positions listed
        assert "**JWT vs Sessions**: JWT" in result
        assert "**REST vs gRPC**: REST" in result
        assert "**SQL vs NoSQL**: SQL" in result


class TestTrimToParagraphBoundary:
    def test_short_content_unchanged(self):
        assert _trim_to_paragraph_boundary("Short text") == "Short text"

    def test_long_content_truncated_at_paragraph(self):
        content = "First paragraph.\n\nSecond paragraph.\n\n" + "x" * 3000
        result = _trim_to_paragraph_boundary(content, max_chars=50)
        assert result == "First paragraph.\n\nSecond paragraph.\n\n[... truncated]"

    def test_no_paragraph_boundary_truncates_at_limit(self):
        content = "a" * 3000
        result = _trim_to_paragraph_boundary(content, max_chars=100)
        assert len(result) <= 120  # 100 + "[... truncated]"
        assert result.endswith("[... truncated]")


class TestSynthesisPrompt:
    def test_contains_findings_not_raw_responses(self):
        responses = [
            AgentResponse("a1", "claude", "opus", 1, "Round 1 content"),
        ]
        result = build_synthesis_prompt(
            "Review auth", responses, "Finding 1: Use auth tokens", []
        )
        assert "Finding 1" in result
        assert "Recommendation" in result
        assert "1 agent analyses" in result
        # Full response content should NOT appear in synthesis prompt
        assert "Round 1 content" not in result

    def test_agent_count(self):
        responses = [
            AgentResponse("a1", "claude", "opus", 1, "Content 1"),
            AgentResponse("a2", "claude", "sonnet", 1, "Content 2"),
            AgentResponse("a3", "openai", "gpt4", 1, "Content 3"),
        ]
        result = build_synthesis_prompt("Review auth", responses, "Findings", [])
        assert "3 agent analyses" in result

    def test_contains_debate_responses(self):
        responses = [
            AgentResponse("a1", "claude", "opus", 1, "Round 1 content"),
        ]
        debate = [
            AgentResponse("a1", "claude", "opus", 2, "Debate response"),
        ]
        result = build_synthesis_prompt(
            "Review auth",
            responses,
            "Some findings",
            [Disagreement("JWT vs Sessions", {"a1": "JWT", "a2": "Sessions"})],
            debate_responses=debate,
        )
        assert "Debate response" in result
        assert "Targeted Debate" in result

    def test_debate_responses_trimmed_in_synthesis(self):
        responses = [
            AgentResponse("a1", "claude", "opus", 1, "Round 1 content"),
        ]
        long_debate = "First point.\n\n" + "x" * 3000
        debate = [
            AgentResponse("a1", "claude", "opus", 2, long_debate),
        ]
        result = build_synthesis_prompt(
            "Review auth",
            responses,
            "Some findings",
            [Disagreement("JWT vs Sessions", {"a1": "JWT", "a2": "Sessions"})],
            debate_responses=debate,
        )
        assert "First point." in result
        assert "[... truncated]" in result
        assert "x" * 3000 not in result

    def test_no_disagreements_message(self):
        responses = [
            AgentResponse("a1", "claude", "opus", 1, "Content"),
        ]
        result = build_synthesis_prompt("Review auth", responses, "Findings", [])
        assert "substantially agreed" in result
