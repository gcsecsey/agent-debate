"""Optional Langfuse tracing for the debate pipeline."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

try:
    from langfuse import Langfuse

    _langfuse: Langfuse | None = Langfuse()
    if not _langfuse.auth_check():
        logger.debug("Langfuse auth check failed — tracing disabled")
        _langfuse = None
except Exception:
    _langfuse = None


class _NoOpSpan:
    """Stub returned when tracing is disabled."""

    def end(self) -> None:
        pass

    def generation(self, **kwargs: Any) -> None:
        pass


class _NoOpTrace:
    """Stub returned when tracing is disabled."""

    def span(self, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()

    def end(self) -> None:
        pass


def is_enabled() -> bool:
    """Return True if Langfuse tracing is available and configured."""
    return _langfuse is not None


def start_trace(name: str, metadata: dict[str, Any] | None = None) -> Any:
    """Start a new Langfuse trace, or return a no-op stub."""
    if _langfuse is None:
        return _NoOpTrace()
    return _langfuse.trace(name=name, metadata=metadata or {})


def start_span(trace: Any, name: str) -> Any:
    """Create a span under a trace for a pipeline phase."""
    return trace.span(name=name)


def log_generation(
    span: Any,
    *,
    name: str,
    model: str | None = None,
    input: Any = None,
    output: Any = None,
    usage: dict[str, int] | None = None,
) -> None:
    """Log an LLM call as a Langfuse generation under the given span."""
    kwargs: dict[str, Any] = {"name": name}
    if model is not None:
        kwargs["model"] = model
    if input is not None:
        kwargs["input"] = input
    if output is not None:
        kwargs["output"] = output
    if usage is not None:
        kwargs["usage"] = usage
    span.generation(**kwargs)


def end_span(span: Any) -> None:
    """End/close a span."""
    span.end()


def end_trace(trace: Any) -> None:
    """End/close a trace and flush to Langfuse."""
    trace.end()
    if _langfuse is not None:
        _langfuse.flush()
