"""Tests for config parsing."""

import pytest

from agent_debate.config import build_config, parse_provider_string, parse_providers_string
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


class TestBuildConfig:
    def test_defaults(self):
        config = build_config()
        assert len(config.providers) == 3
        assert config.max_rounds == 3
        assert config.cwd == "."
        assert config.orchestrator_model == "sonnet"

    def test_custom_values(self):
        config = build_config(
            providers="claude:opus",
            max_rounds=5,
            cwd="/tmp",
            orchestrator_model="opus",
        )
        assert len(config.providers) == 1
        assert config.max_rounds == 5
        assert config.cwd == "/tmp"
        assert config.orchestrator_model == "opus"


class TestProviderConfig:
    def test_agent_id_with_model(self):
        pc = ProviderConfig(provider="claude", model="opus")
        assert pc.agent_id == "claude:opus"

    def test_agent_id_without_model(self):
        pc = ProviderConfig(provider="claude")
        assert pc.agent_id == "claude"
