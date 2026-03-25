"""Base class for CLI-based providers that run as subprocesses."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from .base import BaseProvider


class SubprocessProvider(BaseProvider):
    """Base for providers invoked via their CLI tool as a subprocess.

    Subclasses implement build_args() to construct the CLI invocation.
    Prompt delivery is either via a temp file (the agent reads it) or via stdin.
    """

    command: str  # CLI binary name, e.g. "codex", "gemini", "amp"
    uses_stdin: bool = False  # Whether prompt is delivered via stdin vs file ref

    def build_args(
        self,
        prompt: str,
        prompt_file: str,
        system_prompt: str,
        model: str | None = None,
    ) -> list[str]:
        """Build CLI arguments. Subclasses must override.

        Args:
            prompt: The full prompt text.
            prompt_file: Path to a temp file containing the prompt.
            system_prompt: System-level persona instructions.
            model: Optional model override.

        Returns:
            List of CLI arguments (not including the command itself).
        """
        raise NotImplementedError

    def build_prompt(self, prompt: str, system_prompt: str) -> str:
        """Combine system prompt and user prompt for CLI delivery.

        Subclasses can override for provider-specific formatting.
        """
        return f"{system_prompt}\n\n---\n\n{prompt}"

    async def analyze(
        self,
        prompt: str,
        system_prompt: str,
        cwd: str = ".",
        model: str | None = None,
    ) -> AsyncIterator[str]:
        full_prompt = self.build_prompt(prompt, system_prompt)

        # Write prompt to temp file (some CLIs reference it by path)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, prefix="agent-debate-"
        ) as f:
            f.write(full_prompt)
            prompt_file = f.name

        try:
            args = self.build_args(full_prompt, prompt_file, system_prompt, model)

            proc = await asyncio.create_subprocess_exec(
                self.command,
                *args,
                stdin=asyncio.subprocess.PIPE if self.uses_stdin else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            if self.uses_stdin:
                assert proc.stdin is not None
                proc.stdin.write(full_prompt.encode())
                proc.stdin.write_eof()

            assert proc.stdout is not None

            # Stream stdout line by line
            async for line in proc.stdout:
                decoded = line.decode("utf-8", errors="replace")
                if decoded.strip():
                    yield decoded

            await proc.wait()

            if proc.returncode != 0:
                assert proc.stderr is not None
                stderr = await proc.stderr.read()
                error_msg = stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(
                    f"Provider '{self.id}' exited with code {proc.returncode}"
                    + (f": {error_msg}" if error_msg else "")
                )
        finally:
            Path(prompt_file).unlink(missing_ok=True)

    def available(self) -> bool:
        return self._cli_available(self.command)
