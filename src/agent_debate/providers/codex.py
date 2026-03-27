"""OpenAI Codex provider via CLI subprocess."""

from __future__ import annotations

from .subprocess_base import SubprocessProvider


class CodexProvider(SubprocessProvider):
    """Provider adapter for OpenAI Codex CLI."""

    id = "codex"
    display_name = "OpenAI Codex"
    command = "codex"
    uses_stdin = False  # Codex reads prompt from file reference in args

    DEFAULT_MODEL = "gpt-5.3-codex"

    def build_args(
        self,
        prompt: str,
        prompt_file: str,
        system_prompt: str,
        model: str | None = None,
    ) -> list[str]:
        instruction = f"Read the file at {prompt_file} and follow the instructions within it."

        args = ["exec"]
        args.extend(["-m", model or self.DEFAULT_MODEL])
        args.extend(["-c", "web_search=live"])
        args.append("--skip-git-repo-check")
        args.append("--full-auto")
        args.append(instruction)

        return args
