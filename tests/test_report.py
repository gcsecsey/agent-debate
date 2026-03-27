"""Tests for the report writer's JSON output."""

from __future__ import annotations

import json
from pathlib import Path

from agent_debate.report import ReportWriter
from agent_debate.types import AgentResponse, Disagreement, Finding, ProviderConfig


def test_start_run_captures_meta(tmp_path: Path) -> None:
    writer = ReportWriter(base_dir="reports", cwd=str(tmp_path))
    providers = [
        ProviderConfig(provider="claude", model="opus"),
        ProviderConfig(provider="codex", model=None),
    ]
    writer.start_run(
        prompt="Should we use REST or gRPC?",
        providers=providers,
        orchestrator_model="sonnet",
        max_rounds=1,
    )

    assert writer._json_data["version"] == 1
    assert writer._json_data["meta"]["prompt"] == "Should we use REST or gRPC?"
    assert writer._json_data["meta"]["orchestrator_model"] == "sonnet"
    assert writer._json_data["meta"]["max_rounds"] == 1
    assert len(writer._json_data["meta"]["providers"]) == 2
    assert writer._json_data["meta"]["providers"][0]["agent_id"] == "claude:opus"
    assert "started_at" in writer._json_data["meta"]


def _make_writer(tmp_path: Path) -> ReportWriter:
    """Helper: create a writer with start_run already called."""
    writer = ReportWriter(base_dir="reports", cwd=str(tmp_path))
    writer.start_run(
        prompt="test prompt",
        providers=[ProviderConfig(provider="claude", model="opus")],
    )
    return writer


def test_save_agent_response_accumulates_json(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    response = AgentResponse(
        agent_id="claude:opus",
        provider="claude",
        model="opus",
        round_number=1,
        content="My analysis...",
    )
    writer.save_agent_response(response)

    assert len(writer._json_data["opening"]["responses"]) == 1
    entry = writer._json_data["opening"]["responses"][0]
    assert entry["agent_id"] == "claude:opus"
    assert entry["content"] == "My analysis..."


def test_save_dedup_accumulates_json(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    findings = [
        Finding(topic="Use gRPC", description="Both agree", agents=["a", "b"], severity="important"),
    ]
    disagreements = [
        Disagreement(topic="Public API", positions={"a": "REST", "b": "gRPC-Web"}),
    ]
    writer.save_dedup("raw reasoning text", findings, disagreements)

    dedup = writer._json_data["dedup"]
    assert dedup is not None
    assert len(dedup["findings"]) == 1
    assert dedup["findings"][0]["topic"] == "Use gRPC"
    assert len(dedup["disagreements"]) == 1
    assert dedup["disagreements"][0]["positions"]["a"] == "REST"
    assert dedup["raw_reasoning"] == "raw reasoning text"


def test_save_debate_response_accumulates_json(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    response = AgentResponse(
        agent_id="claude:opus",
        provider="claude",
        model="opus",
        round_number=2,
        content="My rebuttal...",
    )
    writer.save_debate_response(response)

    assert writer._json_data["debate"] is not None
    assert len(writer._json_data["debate"]["responses"]) == 1
    assert writer._json_data["debate"]["responses"][0]["content"] == "My rebuttal..."


def test_write_json_creates_file(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)

    # Simulate a full run
    writer.save_agent_response(AgentResponse(
        agent_id="claude:opus", provider="claude", model="opus",
        round_number=1, content="Opening statement",
    ))
    writer.save_dedup("reasoning", [], [])
    writer.save_synthesis("Final synthesis content")
    writer.write_json()

    json_path = writer.run_dir / "debate.json"
    assert json_path.exists()

    data = json.loads(json_path.read_text())
    assert data["version"] == 1
    assert data["meta"]["completed_at"] is not None
    assert len(data["opening"]["responses"]) == 1
    assert data["synthesis"]["content"] == "Final synthesis content"


def test_write_json_no_debate_when_skipped(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    writer.save_agent_response(AgentResponse(
        agent_id="claude:opus", provider="claude", model="opus",
        round_number=1, content="Opening",
    ))
    writer.save_dedup("reasoning", [], [])
    writer.save_synthesis("Synthesis")
    writer.write_json()

    data = json.loads((writer.run_dir / "debate.json").read_text())
    assert data["debate"] is None
