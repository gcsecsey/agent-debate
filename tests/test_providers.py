"""Tests for provider adapters."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent_debate.providers import (
    PROVIDERS,
    discover_available,
    get_provider,
)
from agent_debate.providers.amp import AmpProvider
from agent_debate.providers.codex import CodexProvider
from agent_debate.providers.gemini import GeminiProvider
from agent_debate.providers.subprocess_base import SubprocessProvider


class TestProviderRegistry:
    def test_all_providers_registered(self):
        assert "claude" in PROVIDERS
        assert "codex" in PROVIDERS
        assert "gemini" in PROVIDERS
        assert "amp" in PROVIDERS

    def test_get_known_provider(self):
        cls = get_provider("claude")
        assert cls is not None

    def test_get_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown provider 'unknown'"):
            get_provider("unknown")


class TestCodexProvider:
    def test_build_args(self):
        provider = CodexProvider()
        args = provider.build_args(
            prompt="test prompt",
            prompt_file="/tmp/test.md",
            system_prompt="You are an architect.",
        )
        assert "exec" in args
        assert "-m" in args
        assert "gpt-5.3-codex" in args
        assert "--skip-git-repo-check" in args
        # Should reference the prompt file
        assert any("/tmp/test.md" in a for a in args)

    def test_build_args_with_model(self):
        provider = CodexProvider()
        args = provider.build_args(
            prompt="test",
            prompt_file="/tmp/test.md",
            system_prompt="test",
            model="o4-mini",
        )
        model_idx = args.index("-m")
        assert args[model_idx + 1] == "o4-mini"

    def test_uses_file_not_stdin(self):
        provider = CodexProvider()
        assert provider.uses_stdin is False

    def test_id_and_command(self):
        provider = CodexProvider()
        assert provider.id == "codex"
        assert provider.command == "codex"


class TestGeminiProvider:
    def test_build_args(self):
        provider = GeminiProvider()
        args = provider.build_args(
            prompt="test prompt",
            prompt_file="/tmp/test.md",
            system_prompt="You are an architect.",
        )
        assert "-p" in args
        assert "--output-format" in args
        assert "text" in args
        assert "-m" in args
        assert "gemini-2.5-pro" in args

    def test_build_args_with_model(self):
        provider = GeminiProvider()
        args = provider.build_args(
            prompt="test",
            prompt_file="/tmp/test.md",
            system_prompt="test",
            model="gemini-3-pro-preview",
        )
        model_idx = args.index("-m")
        assert args[model_idx + 1] == "gemini-3-pro-preview"

    def test_uses_stdin(self):
        provider = GeminiProvider()
        assert provider.uses_stdin is True

    def test_prompt_suppresses_narration(self):
        provider = GeminiProvider()
        result = provider.build_prompt("my prompt", "system prompt")
        assert "Do not narrate" in result
        assert "my prompt" in result
        assert "system prompt" in result


class TestAmpProvider:
    def test_build_args(self):
        provider = AmpProvider()
        args = provider.build_args(
            prompt="test prompt",
            prompt_file="/tmp/test.md",
            system_prompt="You are an architect.",
        )
        assert "-x" in args
        assert "-m" in args
        assert "smart" in args

    def test_build_args_with_model(self):
        provider = AmpProvider()
        args = provider.build_args(
            prompt="test",
            prompt_file="/tmp/test.md",
            system_prompt="test",
            model="deep",
        )
        model_idx = args.index("-m")
        assert args[model_idx + 1] == "deep"

    def test_uses_stdin(self):
        provider = AmpProvider()
        assert provider.uses_stdin is True


class TestDiscoverAvailable:
    def test_returns_dict_of_booleans(self):
        result = discover_available()
        assert isinstance(result, dict)
        for name, available in result.items():
            assert isinstance(name, str)
            assert isinstance(available, bool)

    def test_all_providers_checked(self):
        result = discover_available()
        assert set(result.keys()) == set(PROVIDERS.keys())

    @patch("shutil.which", return_value=None)
    def test_unavailable_when_cli_missing(self, mock_which):
        provider = CodexProvider()
        assert provider.available() is False

    @patch("shutil.which", return_value="/usr/local/bin/codex")
    def test_available_when_cli_found(self, mock_which):
        provider = CodexProvider()
        assert provider.available() is True


class TestSubprocessProviderPrompt:
    def test_default_build_prompt(self):
        """SubprocessProvider.build_prompt combines system + user prompt."""
        provider = CodexProvider()
        result = provider.build_prompt("user prompt", "system prompt")
        assert "system prompt" in result
        assert "user prompt" in result
        assert "---" in result  # separator
