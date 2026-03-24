"""Tests for prompt template generation."""

from agent_debate.prompts import (
    build_debate_prompt,
    build_deadlock_resolution_prompt,
    build_disagreement_prompt,
    build_round1_prompt,
    build_synthesis_prompt,
    get_persona,
    get_persona_name,
)
from agent_debate.types import AgentResponse, Disagreement, PositionUpdate


class TestPersonas:
    def test_default_personas_cycle(self):
        name0 = get_persona_name(0)
        name1 = get_persona_name(1)
        name2 = get_persona_name(2)
        name3 = get_persona_name(3)  # wraps around
        assert name0 == "Architect"
        assert name1 == "Pragmatist"
        assert name2 == "Reliability Engineer"
        assert name3 == "Architect"

    def test_persona_override(self):
        custom = "You are a database expert."
        result = get_persona(0, override=custom)
        assert result == custom

    def test_default_persona_content(self):
        result = get_persona(0)
        assert "architect" in result.lower()


class TestRound1Prompt:
    def test_contains_user_prompt(self):
        result = build_round1_prompt("Review auth module", "You are an architect.")
        assert "Review auth module" in result

    def test_contains_persona(self):
        result = build_round1_prompt("Review auth module", "You are an architect.")
        assert "You are an architect." in result

    def test_contains_structure_guidance(self):
        result = build_round1_prompt("Review auth module", "You are an architect.")
        assert "### Approach" in result
        assert "### Key Decisions" in result
        assert "### Concerns" in result


class TestDebatePrompt:
    def _make_response(self, agent_id: str, content: str) -> AgentResponse:
        return AgentResponse(
            agent_id=agent_id,
            provider="claude",
            model="sonnet",
            round_number=1,
            content=content,
            persona="Architect",
        )

    def test_contains_prior_analysis(self):
        own = self._make_response("claude:opus", "My analysis here")
        other = self._make_response("claude:sonnet", "Other analysis")
        disagreement = Disagreement(
            topic="JWT vs Sessions",
            positions={"claude:opus": "JWT", "claude:sonnet": "Sessions"},
            questions=["What scale are we targeting?"],
        )
        result = build_debate_prompt(
            "Review auth",
            "You are an architect.",
            own,
            [other],
            [disagreement],
            round_number=2,
        )
        assert "My analysis here" in result
        assert "Other analysis" in result
        assert "JWT vs Sessions" in result
        assert "What scale are we targeting?" in result
        assert "strong self-advocate" in result
        assert "Structured Position Updates" in result
        assert '"previous_position"' in result


class TestDisagreementPrompt:
    def test_contains_all_responses(self):
        responses = [
            AgentResponse(
                "a1",
                "claude",
                "opus",
                1,
                "Analysis 1",
                "Architect",
                [
                    PositionUpdate(
                        topic="JWT vs Sessions",
                        previous_position="Use JWT",
                        next_position="Use JWT",
                        change_type="maintain",
                        convincing_argument="Scale still matters most",
                    )
                ],
            ),
            AgentResponse("a2", "claude", "sonnet", 1, "Analysis 2", "Pragmatist"),
        ]
        result = build_disagreement_prompt("Review auth", responses)
        assert "Analysis 1" in result
        assert "Analysis 2" in result
        assert "JSON" in result  # asks for JSON output
        assert "Structured Position Updates" in result
        assert "Use JWT" in result


class TestDeadlockResolutionPrompt:
    def test_contains_history_and_disagreements(self):
        round1 = [
            AgentResponse("a1", "claude", "opus", 1, "Round 1 content", "Architect"),
        ]
        disagreements = [
            Disagreement("JWT vs Sessions", {"a1": "JWT", "a2": "Sessions"})
        ]
        result = build_deadlock_resolution_prompt(
            "Review auth", [round1], disagreements
        )
        assert "Round 1 content" in result
        assert "JWT vs Sessions" in result
        assert "Resolve the deadlock now" in result


class TestSynthesisPrompt:
    def test_contains_debate_history(self):
        round1 = [
            AgentResponse("a1", "claude", "opus", 1, "Round 1 content", "Architect"),
        ]
        result = build_synthesis_prompt("Review auth", [round1], [])
        assert "Round 1 content" in result
        assert "Consensus" in result
        assert "Recommendation" in result

    def test_contains_judge_resolution(self):
        round1 = [
            AgentResponse("a1", "claude", "opus", 1, "Round 1 content", "Architect"),
        ]
        result = build_synthesis_prompt(
            "Review auth",
            [round1],
            [Disagreement("JWT vs Sessions", {"a1": "JWT", "a2": "Sessions"})],
            "Judge says prefer sessions.",
        )
        assert "Judge Deadlock Resolution" in result
        assert "Judge says prefer sessions." in result
