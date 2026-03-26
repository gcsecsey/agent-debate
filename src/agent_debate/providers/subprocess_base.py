"""Base class for CLI-based providers that run as subprocesses."""

from __future__ import annotations

import asyncio
import os
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
    idle_timeout: int = 60  # Kill agent if no output for this many seconds

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

        # Use a pty for stdout so the child process sees a TTY and uses
        # line-buffering instead of full-buffering (~4-8KB blocks).
        # Without this, CLI tools like gemini/codex buffer all output
        # until exit, preventing real-time streaming.
        controller_fd, worker_fd = os.openpty()

        try:
            args = self.build_args(full_prompt, prompt_file, system_prompt, model)

            proc = await asyncio.create_subprocess_exec(
                self.command,
                *args,
                stdin=asyncio.subprocess.PIPE if self.uses_stdin else None,
                stdout=worker_fd,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            # Parent doesn't need the worker end of the pty
            os.close(worker_fd)
            worker_fd = -1

            if self.uses_stdin:
                assert proc.stdin is not None
                proc.stdin.write(full_prompt.encode())
                proc.stdin.write_eof()

            # Wrap the pty controller fd in an async reader
            loop = asyncio.get_event_loop()
            reader = asyncio.StreamReader()
            transport, _ = await loop.connect_read_pipe(
                lambda: asyncio.StreamReaderProtocol(reader),
                os.fdopen(controller_fd, "rb", 0),
            )
            controller_fd = -1  # Now owned by the fdopen file object

            try:
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            reader.read(4096), timeout=self.idle_timeout
                        )
                    except asyncio.TimeoutError:
                        raise RuntimeError(
                            f"Provider '{self.command}' produced no output for "
                            f"{self.idle_timeout}s — likely stalled or rate-limited"
                        )
                    if not chunk:
                        break
                    decoded = chunk.decode("utf-8", errors="replace")
                    if decoded.strip():
                        yield decoded
            except OSError:
                # EIO is expected when the child process exits and the
                # worker side of the pty closes.
                pass
            finally:
                transport.close()

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
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            if worker_fd >= 0:
                os.close(worker_fd)
            if controller_fd >= 0:
                os.close(controller_fd)
            Path(prompt_file).unlink(missing_ok=True)

    def available(self) -> bool:
        return self._cli_available(self.command)
