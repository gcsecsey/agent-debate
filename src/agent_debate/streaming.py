"""Streaming infrastructure for merging parallel agent outputs."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from .types import AgentResponse, DebateEvent, EventType


async def fan_out_streaming(
    agent_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, AsyncIterator[tuple[str, AgentResponse | None]]]]]],
) -> AsyncIterator[DebateEvent | AgentResponse]:
    """Run multiple agents in parallel, yielding chunk events as they stream.

    Each factory is a (agent_id, async_callable) tuple. The callable returns
    an async iterator yielding (chunk_text, None) for intermediate chunks,
    and ("", AgentResponse) as the final item.
    """
    queue: asyncio.Queue[DebateEvent | AgentResponse | None] = asyncio.Queue()
    total = len(agent_factories)

    async def run_and_enqueue(agent_id: str, factory: Callable) -> None:
        try:
            await queue.put(
                DebateEvent(type=EventType.AGENT_STARTED, agent_id=agent_id)
            )
            async for chunk, response in await factory():
                if response is not None:
                    # Final response
                    await queue.put(
                        DebateEvent(
                            type=EventType.AGENT_COMPLETED,
                            agent_id=response.agent_id,
                            round_number=response.round_number,
                        )
                    )
                    await queue.put(response)
                elif chunk:
                    await queue.put(
                        DebateEvent(
                            type=EventType.AGENT_CHUNK,
                            agent_id=agent_id,
                            content=chunk,
                        )
                    )
        except Exception as e:
            await queue.put(
                DebateEvent(
                    type=EventType.ERROR,
                    agent_id=agent_id,
                    content=str(e),
                )
            )
        finally:
            await queue.put(None)  # sentinel

    for agent_id, factory in agent_factories:
        asyncio.create_task(run_and_enqueue(agent_id, factory))

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
