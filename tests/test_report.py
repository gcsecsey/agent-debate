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
