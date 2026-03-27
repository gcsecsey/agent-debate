"""Shared utilities for eval tests and the baseline runner."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_debate.types import AgentResponse

FIXTURES = Path(__file__).parent.parent / "fixtures"

# Auth scenario prompt that matches the fixture responses
AUTH_PROMPT = (
    "Design and implement an authentication module for our web application. "
    "Consider security, scalability, and developer experience. "
    "The app is currently a monolith serving under 10k users."
)

_AUTH_AGENTS = [
    ("architect", "claude", "opus"),
    ("pragmatist", "codex", "gpt-5.3-codex"),
    ("reliability", "gemini", "gemini-2.5-pro"),
]


def get_commit_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def load_auth_scenario() -> tuple[str, list[AgentResponse]]:
    """Load the auth module scenario: returns (prompt, agent_responses)."""
    responses = []
    for name, provider, model in _AUTH_AGENTS:
        content = (FIXTURES / f"round1_{name}.md").read_text()
        responses.append(
            AgentResponse(
                agent_id=name,
                provider=provider,
                model=model,
                round_number=1,
                content=content,
            )
        )
    return AUTH_PROMPT, responses


async def call_llm(prompt: str, model: str = "haiku") -> tuple[str, dict[str, int] | None]:
    """Call the orchestrator LLM, replicating Orchestrator._call_orchestrator logic."""
    from claude_agent_sdk import ClaudeAgentOptions, query
    from claude_agent_sdk.types import AssistantMessage, TextBlock

    result_chunks: list[str] = []
    options = ClaudeAgentOptions(model=model, max_turns=1)
    usage_info: dict[str, int] | None = None

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    result_chunks.append(block.text)
            if hasattr(message, "usage") and message.usage is not None:
                u = message.usage if isinstance(message.usage, dict) else {}
                # Include cached tokens in the total input count
                inp = (
                    u.get("input_tokens", 0)
                    + u.get("cache_creation_input_tokens", 0)
                    + u.get("cache_read_input_tokens", 0)
                )
                out = u.get("output_tokens", 0)
                usage_info = {
                    "input_tokens": inp,
                    "output_tokens": out,
                    "total_tokens": inp + out,
                }

    return "".join(result_chunks), usage_info
