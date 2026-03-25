"""Tests for the optional Langfuse tracing module."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


class TestNoOpStubs:
    """Verify the no-op path works when Langfuse is unavailable."""

    def test_noop_trace_span_lifecycle(self):
        from agent_debate.tracing import _NoOpSpan, _NoOpTrace

        trace = _NoOpTrace()
        span = trace.span(name="test")
        assert isinstance(span, _NoOpSpan)
        span.generation(name="gen", model="test", input="x", output="y")
        span.end()
        trace.end()

    def test_noop_span_generation_accepts_kwargs(self):
        from agent_debate.tracing import _NoOpSpan

        span = _NoOpSpan()
        span.generation(name="a", model="b", input="c", output="d", usage={"input_tokens": 10})
        span.end()


class TestPublicAPI:
    """Test the public tracing API functions in the no-op case."""

    def test_is_enabled_false_without_langfuse(self):
        """Without Langfuse credentials, tracing should be disabled."""
        from agent_debate import tracing

        # In test environment, Langfuse is not configured, so it should be disabled
        # (either not installed or auth_check fails)
        assert tracing.is_enabled() is False

    def test_start_trace_returns_noop(self):
        from agent_debate import tracing
        from agent_debate.tracing import _NoOpTrace

        trace = tracing.start_trace("test_trace", {"key": "value"})
        assert isinstance(trace, _NoOpTrace)

    def test_start_span_on_noop_trace(self):
        from agent_debate import tracing
        from agent_debate.tracing import _NoOpSpan

        trace = tracing.start_trace("test")
        span = tracing.start_span(trace, "phase_1")
        assert isinstance(span, _NoOpSpan)

    def test_log_generation_noop(self):
        from agent_debate import tracing

        trace = tracing.start_trace("test")
        span = tracing.start_span(trace, "phase_1")
        # Should not raise
        tracing.log_generation(
            span,
            name="gen",
            model="sonnet",
            input="prompt text",
            output="response text",
            usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        )

    def test_end_span_noop(self):
        from agent_debate import tracing

        trace = tracing.start_trace("test")
        span = tracing.start_span(trace, "phase_1")
        tracing.end_span(span)  # Should not raise

    def test_end_trace_noop(self):
        from agent_debate import tracing

        trace = tracing.start_trace("test")
        tracing.end_trace(trace)  # Should not raise

    def test_full_lifecycle_noop(self):
        """End-to-end lifecycle matching orchestrator usage pattern."""
        from agent_debate import tracing

        trace = tracing.start_trace("debate_run", {"providers": ["claude:opus"]})

        span1 = tracing.start_span(trace, "round_1")
        tracing.log_generation(span1, name="claude:opus", model="opus", input="p", output="r")
        tracing.end_span(span1)

        span2 = tracing.start_span(trace, "dedup")
        tracing.log_generation(span2, name="dedup_call", model="sonnet", input="p", output="r")
        tracing.end_span(span2)

        span3 = tracing.start_span(trace, "synthesis")
        tracing.log_generation(span3, name="synthesis_call", model="sonnet", input="p", output="r")
        tracing.end_span(span3)

        tracing.end_trace(trace)


class TestWithMockedLangfuse:
    """Test that the correct Langfuse SDK calls are made when available."""

    def test_enabled_with_mock_langfuse(self):
        mock_langfuse_instance = MagicMock()
        mock_langfuse_instance.auth_check.return_value = True

        mock_trace = MagicMock()
        mock_span = MagicMock()
        mock_langfuse_instance.trace.return_value = mock_trace
        mock_trace.span.return_value = mock_span

        # Patch the module-level _langfuse
        from agent_debate import tracing

        original = tracing._langfuse
        try:
            tracing._langfuse = mock_langfuse_instance

            assert tracing.is_enabled() is True

            trace = tracing.start_trace("debate_run", {"key": "val"})
            mock_langfuse_instance.trace.assert_called_once_with(
                name="debate_run", metadata={"key": "val"}
            )
            assert trace is mock_trace

            span = tracing.start_span(trace, "round_1")
            mock_trace.span.assert_called_once_with(name="round_1")
            assert span is mock_span

            tracing.log_generation(
                span,
                name="claude:opus",
                model="opus",
                input="prompt",
                output="response",
                usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            )
            mock_span.generation.assert_called_once_with(
                name="claude:opus",
                model="opus",
                input="prompt",
                output="response",
                usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            )

            tracing.end_span(span)
            mock_span.end.assert_called_once()

            tracing.end_trace(trace)
            mock_trace.end.assert_called_once()
            mock_langfuse_instance.flush.assert_called_once()
        finally:
            tracing._langfuse = original

    def test_log_generation_without_optional_fields(self):
        mock_langfuse_instance = MagicMock()
        mock_span = MagicMock()

        from agent_debate import tracing

        original = tracing._langfuse
        try:
            tracing._langfuse = mock_langfuse_instance

            tracing.log_generation(span=mock_span, name="agent")
            mock_span.generation.assert_called_once_with(name="agent")
        finally:
            tracing._langfuse = original
