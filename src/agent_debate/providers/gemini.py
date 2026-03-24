"""Google Gemini CLI provider via subprocess."""

from __future__ import annotations

from .subprocess_base import SubprocessProvider


class GeminiProvider(SubprocessProvider):
    """Provider adapter for Gemini CLI."""

    id = "gemini"
    display_name = "Gemini CLI"
    command = "gemini"
    uses_stdin = True  # Gemini reads prompt from stdin

    DEFAULT_MODEL = "gemini-2.5-pro"

    def build_args(
        self,
        prompt: str,
        prompt_file: str,
        system_prompt: str,
        model: str | None = None,
    ) -> list[str]:
        args = ["-p", ""]  # Non-interactive/headless mode
        args.extend(["-m", model or self.DEFAULT_MODEL])
        args.extend(["--output-format", "text"])
        return args

    def build_prompt(self, prompt: str, system_prompt: str) -> str:
        """Append instruction to suppress Gemini's tool-use narration."""
        base = super().build_prompt(prompt, system_prompt)
        return (
            base
            + "\n\nIMPORTANT: Do not narrate your tool usage, internal planning, "
            "or chain of thought. Start your response directly with your analysis. "
            "Do not prefix your response with lines like \"I will read...\" or "
            "\"I will list...\"."
        )
