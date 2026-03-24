"""Amp CLI provider via subprocess."""

from __future__ import annotations

from .subprocess_base import SubprocessProvider


class AmpProvider(SubprocessProvider):
    """Provider adapter for Amp CLI."""

    id = "amp"
    display_name = "Amp CLI"
    command = "amp"
    uses_stdin = True  # Amp reads prompt from stdin

    DEFAULT_MODEL = "smart"

    def build_args(
        self,
        prompt: str,
        prompt_file: str,
        system_prompt: str,
        model: str | None = None,
    ) -> list[str]:
        args = ["-x"]  # Non-interactive execution mode
        args.extend(["-m", model or self.DEFAULT_MODEL])
        return args
