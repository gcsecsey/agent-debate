"""Tests for agent persona loading and assignment."""

from agent_debate.personas import (
    DEFAULT_ROTATION,
    auto_assign_personas,
    get_persona,
    get_persona_instruction,
    load_all_personas,
)


class TestLoadAllPersonas:
    def test_loads_default_personas(self):
        personas = load_all_personas()
        assert len(personas) >= 5
        for name in DEFAULT_ROTATION:
            assert name in personas

    def test_persona_has_required_fields(self):
        personas = load_all_personas()
        for name, data in personas.items():
            assert data["name"] == name
            assert "label" in data
            assert "description" in data
            assert "instruction" in data


class TestGetPersona:
    def test_known_persona(self):
        data = get_persona("security")
        assert data is not None
        assert data["name"] == "security"
        assert "Security" in data["label"]

    def test_unknown_persona(self):
        assert get_persona("nonexistent") is None


class TestGetPersonaInstruction:
    def test_known_persona(self):
        result = get_persona_instruction("security")
        assert "security" in result
        assert "vulnerabilities" in result

    def test_unknown_persona_returns_empty(self):
        assert get_persona_instruction("nonexistent") == ""

    def test_all_default_personas_have_instructions(self):
        for name in DEFAULT_ROTATION:
            result = get_persona_instruction(name)
            assert result, f"Persona '{name}' should have an instruction"


class TestAutoAssignPersonas:
    def test_assigns_from_rotation(self):
        result = auto_assign_personas(3)
        assert result == DEFAULT_ROTATION[:3]

    def test_cycles_for_more_than_five(self):
        result = auto_assign_personas(7)
        assert len(result) == 7
        assert result[5] == result[0]
        assert result[6] == result[1]

    def test_single_agent(self):
        result = auto_assign_personas(1)
        assert len(result) == 1
        assert result[0] == DEFAULT_ROTATION[0]
