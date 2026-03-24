"""Claude provider using the Claude Agent SDK."""

from __future__ import annotations

from collections.abc import AsyncIterator

from claude_agent_sdk import query, ClaudeAgentOptions
from claude_agent_sdk.types import AssistantMessage, TextBlock

from .base import BaseProvider


class ClaudeProvider(BaseProvider):
    """Provider adapter for Claude Code via the Agent SDK."""

    id = "claude"
    display_name = "Claude Code"

    async def analyze(
        self,
        prompt: str,
        system_prompt: str,
        cwd: str = ".",
        model: str | None = None,
    ) -> AsyncIterator[str]:
        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            model=model or "sonnet",
            cwd=cwd,
            permission_mode="bypassPermissions",
        )

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        yield block.text

    def available(self) -> bool:
        return self._cli_available("claude")
