"""Abstract base class for provider adapters."""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class BaseProvider(ABC):
    """Base class for AI coding agent providers.

    Each provider wraps a specific AI tool (Claude, Codex, Gemini, Amp)
    and exposes a uniform async streaming interface.
    """

    id: str
    display_name: str

    @abstractmethod
    async def analyze(
        self,
        prompt: str,
        system_prompt: str,
        cwd: str = ".",
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream response chunks from the provider.

        Args:
            prompt: The full prompt to send to the agent.
            system_prompt: System-level instructions (persona, format).
            cwd: Working directory for the agent.
            model: Model override (provider-specific).

        Yields:
            Text chunks as they arrive.
        """
        ...  # pragma: no cover

    def available(self) -> bool:
        """Check if this provider's CLI/SDK is installed and usable."""
        return True

    def _cli_available(self, command: str) -> bool:
        """Check if a CLI command is on PATH."""
        return shutil.which(command) is not None
