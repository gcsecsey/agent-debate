"""Eval-specific fixtures: Langfuse client, LLM caller, and test data."""

from __future__ import annotations

import os
import uuid

import pytest

from agent_debate.types import AgentResponse

from .helpers import AUTH_PROMPT, call_llm, get_commit_sha, load_auth_scenario

# Re-export call_llm so existing test imports (from .conftest import call_llm) work
__all__ = ["call_llm"]

# All tests in this directory are eval tests
pytestmark = pytest.mark.eval


def _langfuse_configured() -> bool:
    """Check if Langfuse environment variables are set."""
    return bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY")
        and os.environ.get("LANGFUSE_SECRET_KEY")
    )


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
    return get_commit_sha()


@pytest.fixture
def user_prompt() -> str:
    return AUTH_PROMPT


@pytest.fixture
def agent_responses() -> list[AgentResponse]:
    """Load the three auth-scenario fixture files as AgentResponse objects."""
    _, responses = load_auth_scenario()
    return responses
