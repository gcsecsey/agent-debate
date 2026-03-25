"""Tests for config parsing."""

import pytest

from agent_debate.config import (
    MODEL_GROUPS,
    build_config,
    parse_provider_string,
    parse_providers_string,
)
from agent_debate.types import ProviderConfig


class TestParseProviderString:
    def test_provider_only(self):
        result = parse_provider_string("claude")
        assert result.provider == "claude"
        assert result.model is None

    def test_provider_with_model(self):
        result = parse_provider_string("claude:opus")
        assert result.provider == "claude"
        assert result.model == "opus"

    def test_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown provider 'unknown'"):
            parse_provider_string("unknown")

    def test_whitespace_stripped(self):
        result = parse_provider_string("  claude:sonnet  ")
        assert result.provider == "claude"
        assert result.model == "sonnet"


class TestParseProvidersString:
    def test_single_provider(self):
        result = parse_providers_string("claude:opus")
        assert len(result) == 1
        assert result[0].provider == "claude"
        assert result[0].model == "opus"

    def test_multiple_providers(self):
        result = parse_providers_string("claude:opus,claude:sonnet,claude:haiku")
        assert len(result) == 3
        assert result[0].model == "opus"
        assert result[1].model == "sonnet"
        assert result[2].model == "haiku"

    def test_empty_string(self):
        with pytest.raises(ValueError, match="No providers specified"):
            parse_providers_string("")

    def test_whitespace_in_list(self):
        result = parse_providers_string("claude:opus , claude:sonnet")
        assert len(result) == 2

    def test_group_top(self):
        result = parse_providers_string("top")
        assert len(result) == 3
        assert result[0].provider == "claude"
        assert result[0].model == "opus"
        assert result[1].provider == "gemini"
        assert result[2].provider == "codex"

    def test_group_fast(self):
        result = parse_providers_string("fast")
        assert len(result) == 3
        assert result[0].provider == "claude"
        assert result[0].model == "sonnet"

    def test_unknown_group_treated_as_provider(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            parse_providers_string("nonexistent_group")


class TestBuildConfig:
    def test_defaults(self):
        config = build_config()
        assert len(config.providers) == 3  # "top" group
        assert config.max_rounds == 1
        assert config.cwd == "."
        assert config.orchestrator_model == "sonnet"
        assert config.report_dir == ".context/debate"

    def test_custom_values(self):
        config = build_config(
            providers="claude:opus",
            max_rounds=5,
            cwd="/tmp",
            orchestrator_model="opus",
            report_dir=None,
        )
        assert len(config.providers) == 1
        assert config.max_rounds == 5
        assert config.cwd == "/tmp"
        assert config.orchestrator_model == "opus"
        assert config.report_dir is None

    def test_group_name_as_providers(self):
        config = build_config(providers="fast")
        assert len(config.providers) == 3
        assert config.providers[0].model == "sonnet"


class TestModelGroups:
    def test_groups_defined(self):
        assert "top" in MODEL_GROUPS
        assert "fast" in MODEL_GROUPS

    def test_top_group_contents(self):
        assert "claude:opus" in MODEL_GROUPS["top"]
        assert "gemini" in MODEL_GROUPS["top"]
        assert "codex" in MODEL_GROUPS["top"]

    def test_fast_group_contents(self):
        assert "claude:sonnet" in MODEL_GROUPS["fast"]


class TestProviderConfig:
    def test_agent_id_with_model(self):
        pc = ProviderConfig(provider="claude", model="opus")
        assert pc.agent_id == "claude:opus"

    def test_agent_id_without_model(self):
        pc = ProviderConfig(provider="claude")
        assert pc.agent_id == "claude"
