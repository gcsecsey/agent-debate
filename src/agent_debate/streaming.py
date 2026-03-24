"""Streaming infrastructure for merging parallel agent outputs."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine
from typing import Any

from .types import AgentResponse, DebateEvent, EventType


async def fan_out_streaming(
    coroutines: list[Coroutine[Any, Any, AgentResponse]],
) -> AsyncIterator[DebateEvent | AgentResponse]:
    """Run multiple agent coroutines in parallel, yielding events as they arrive.

    Each coroutine should return an AgentResponse. This function wraps them
    to emit AGENT_STARTED and AGENT_COMPLETED events, merging everything
    through an asyncio.Queue so the caller gets a single ordered stream.

    Yields:
        DebateEvent for start/complete notifications, and the final
        AgentResponse objects (tagged with AGENT_COMPLETED events).
    """
    queue: asyncio.Queue[DebateEvent | AgentResponse | None] = asyncio.Queue()
    total = len(coroutines)

    async def run_and_enqueue(coro: Coroutine[Any, Any, AgentResponse]) -> None:
        try:
            response = await coro
            await queue.put(
                DebateEvent(
                    type=EventType.AGENT_COMPLETED,
                    agent_id=response.agent_id,
                    round_number=response.round_number,
                    content=response.content,
                )
            )
            await queue.put(response)
        except Exception as e:
            await queue.put(
                DebateEvent(
                    type=EventType.ERROR,
                    content=str(e),
                )
            )
        finally:
            await queue.put(None)  # sentinel

    for coro in coroutines:
        asyncio.create_task(run_and_enqueue(coro))

    completed = 0
    while completed < total:
        item = await queue.get()
        if item is None:
            completed += 1
            continue
        yield item


def collect_responses(events: list[DebateEvent | AgentResponse]) -> list[AgentResponse]:
    """Extract AgentResponse objects from a mixed event stream."""
    return [e for e in events if isinstance(e, AgentResponse)]
