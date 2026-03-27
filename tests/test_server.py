"""Tests for the debate viewer server."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent_debate.server import scan_debates, load_debate


FIXTURE = Path(__file__).parent / "fixtures" / "debate.json"


def _setup_debates(tmp_path: Path, count: int = 1) -> list[Path]:
    """Create mock debate directories with debate.json files."""
    dirs = []
    for i in range(count):
        ts = f"2026-03-{26 - i:02d}T155249"
        debate_dir = tmp_path / ".context" / "debate" / ts
        debate_dir.mkdir(parents=True)
        shutil.copy(FIXTURE, debate_dir / "debate.json")
        dirs.append(debate_dir)
    return dirs


def test_scan_debates_finds_json_files(tmp_path: Path) -> None:
    _setup_debates(tmp_path, count=2)
    debates = scan_debates(str(tmp_path))

    assert len(debates) == 2
    assert debates[0]["prompt"] == "Should we use REST or gRPC?"
    assert "timestamp" in debates[0]
    assert "providers" in debates[0]
    assert "disagreements_count" in debates[0]


def test_scan_debates_sorted_newest_first(tmp_path: Path) -> None:
    _setup_debates(tmp_path, count=3)
    debates = scan_debates(str(tmp_path))

    timestamps = [d["timestamp"] for d in debates]
    assert timestamps == sorted(timestamps, reverse=True)


def test_scan_debates_empty_directory(tmp_path: Path) -> None:
    debates = scan_debates(str(tmp_path))
    assert debates == []


def test_scan_debates_skips_malformed_json(tmp_path: Path) -> None:
    _setup_debates(tmp_path, count=1)
    bad_dir = tmp_path / ".context" / "debate" / "2026-03-20T000000"
    bad_dir.mkdir(parents=True)
    (bad_dir / "debate.json").write_text("not json")

    debates = scan_debates(str(tmp_path))
    assert len(debates) == 1


def test_load_debate_returns_full_json(tmp_path: Path) -> None:
    dirs = _setup_debates(tmp_path, count=1)
    ts = dirs[0].name
    data = load_debate(str(tmp_path), ts)

    assert data is not None
    assert data["version"] == 1
    assert len(data["opening"]["responses"]) == 2


def test_load_debate_returns_none_for_missing(tmp_path: Path) -> None:
    data = load_debate(str(tmp_path), "nonexistent")
    assert data is None
