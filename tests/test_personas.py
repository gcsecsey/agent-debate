"""Tests for agent persona definitions and assignment."""

from agent_debate.personas import (
    DEFAULT_ROTATION,
    PERSONAS,
    auto_assign_personas,
    get_persona_instruction,
)


class TestGetPersonaInstruction:
    def test_known_persona(self):
        result = get_persona_instruction("security")
        assert "security" in result
        assert "vulnerabilities" in result

    def test_unknown_persona_returns_empty(self):
        assert get_persona_instruction("nonexistent") == ""

    def test_all_defined_personas_have_instructions(self):
        for name in PERSONAS:
            result = get_persona_instruction(name)
            assert result, f"Persona '{name}' should have an instruction"
            assert name in result


class TestAutoAssignPersonas:
    def test_assigns_from_rotation(self):
        result = auto_assign_personas(3)
        assert result == DEFAULT_ROTATION[:3]

    def test_cycles_for_more_than_five(self):
        result = auto_assign_personas(7)
        assert len(result) == 7
        assert result[5] == result[0]  # wraps around
        assert result[6] == result[1]

    def test_single_agent(self):
        result = auto_assign_personas(1)
        assert len(result) == 1
        assert result[0] == DEFAULT_ROTATION[0]
