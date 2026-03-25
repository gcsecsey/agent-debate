"""Eval-specific fixtures: Langfuse client, LLM caller, and test data."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

from agent_debate.types import AgentResponse

# All tests in this directory are eval tests
pytestmark = pytest.mark.eval

FIXTURES = Path(__file__).parent.parent / "fixtures"

# Auth scenario prompt that matches the fixture responses
AUTH_PROMPT = (
    "Design and implement an authentication module for our web application. "
    "Consider security, scalability, and developer experience. "
    "The app is currently a monolith serving under 10k users."
)


def _langfuse_configured() -> bool:
    """Check if Langfuse environment variables are set."""
    return bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY")
        and os.environ.get("LANGFUSE_SECRET_KEY")
    )


def _get_commit_sha() -> str:
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


@pytest.fixture(scope="session")
def langfuse_client():
    """Session-scoped Langfuse client. Skips if not configured."""
    if not _langfuse_configured():
        pytest.skip("Langfuse env vars not set (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY)")

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    from langfuse import Langfuse

    client = Langfuse()
    yield client
    client.flush()


@pytest.fixture(scope="session")
def eval_run_id() -> str:
    """Unique ID for this eval run, used to group scores in Langfuse."""
    return str(uuid.uuid4())


@pytest.fixture(scope="session")
def commit_sha() -> str:
    return _get_commit_sha()


@pytest.fixture
def user_prompt() -> str:
    return AUTH_PROMPT


@pytest.fixture
def agent_responses() -> list[AgentResponse]:
    """Load the three auth-scenario fixture files as AgentResponse objects."""
    fixtures = [
        ("architect", "claude", "opus"),
        ("pragmatist", "codex", "gpt-5.3-codex"),
        ("reliability", "gemini", "gemini-2.5-pro"),
    ]
    responses = []
    for name, provider, model in fixtures:
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
    return responses


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
                u = message.usage
                usage_info = {
                    "input_tokens": getattr(u, "input_tokens", 0),
                    "output_tokens": getattr(u, "output_tokens", 0),
                    "total_tokens": getattr(u, "input_tokens", 0)
                    + getattr(u, "output_tokens", 0),
                }

    return "".join(result_chunks), usage_info
