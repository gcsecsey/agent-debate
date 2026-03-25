"""Tests for prompt template generation."""

from agent_debate.prompts import (
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
        assert "### Key Decisions" in result
        assert "### Concerns" in result

    def test_no_persona_assignment(self):
        result = build_round1_prompt("Review auth module")
        assert "You are a" not in result


class TestDedupPrompt:
    def _make_response(self, agent_id: str, content: str) -> AgentResponse:
        return AgentResponse(
            agent_id=agent_id,
            provider="claude",
            model="opus",
            round_number=1,
            content=content,
        )

    def test_contains_all_responses(self):
        responses = [
            self._make_response("a1", "Analysis 1"),
            self._make_response("a2", "Analysis 2"),
        ]
        result = build_dedup_prompt("Review auth", responses)
        assert "Analysis 1" in result
        assert "Analysis 2" in result
        assert "JSON" in result

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

    def test_contains_own_analysis(self):
        own = self._make_response("claude:opus", "My analysis here")
        other = self._make_response("claude:sonnet", "Other analysis")
        disagreement = Disagreement(
            topic="JWT vs Sessions",
            positions={"claude:opus": "JWT", "claude:sonnet": "Sessions"},
        )
        result = build_targeted_debate_prompt(
            "Review auth",
            own,
            disagreement,
            [other],
        )
        assert "My analysis here" in result
        assert "JWT vs Sessions" in result

    def test_asks_for_strongest_case(self):
        own = self._make_response("claude:opus", "My analysis")
        disagreement = Disagreement(
            topic="REST vs gRPC",
            positions={"claude:opus": "REST", "claude:sonnet": "gRPC"},
        )
        result = build_targeted_debate_prompt(
            "Design API",
            own,
            disagreement,
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
            disagreement,
            [],
        )
        assert "position_updates" not in result.lower()
        assert "Structured Position Updates" not in result


class TestSynthesisPrompt:
    def test_contains_responses_and_findings(self):
        responses = [
            AgentResponse("a1", "claude", "opus", 1, "Round 1 content"),
        ]
        result = build_synthesis_prompt(
            "Review auth", responses, "Finding 1: Use auth tokens", []
        )
        assert "Round 1 content" in result
        assert "Finding 1" in result
        assert "Recommendation" in result

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

    def test_no_disagreements_message(self):
        responses = [
            AgentResponse("a1", "claude", "opus", 1, "Content"),
        ]
        result = build_synthesis_prompt("Review auth", responses, "Findings", [])
        assert "substantially agreed" in result
