"""Tests for the debate viewer server."""

from __future__ import annotations

import json
import shutil
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agent_debate.server import load_debate, scan_debates, start_server


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


def _start_test_server(cwd: str, port: int = 0) -> tuple:
    """Start a server in a background thread, return (server, port, thread)."""
    server = start_server(cwd, port=port, open_browser=False)
    actual_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server, actual_port, thread


def test_api_debates_returns_json(tmp_path: Path) -> None:
    _setup_debates(tmp_path, count=2)
    server, port, _ = _start_test_server(str(tmp_path))
    try:
        url = f"http://localhost:{port}/api/debates"
        with urllib.request.urlopen(url) as resp:
            assert resp.status == 200
            data = json.loads(resp.read())
            assert len(data) == 2
    finally:
        server.shutdown()


def test_api_debate_detail_returns_full_json(tmp_path: Path) -> None:
    dirs = _setup_debates(tmp_path, count=1)
    ts = dirs[0].name
    server, port, _ = _start_test_server(str(tmp_path))
    try:
        url = f"http://localhost:{port}/api/debates/{ts}"
        with urllib.request.urlopen(url) as resp:
            assert resp.status == 200
            data = json.loads(resp.read())
            assert data["version"] == 1
    finally:
        server.shutdown()


def test_api_debate_detail_404_for_missing(tmp_path: Path) -> None:
    server, port, _ = _start_test_server(str(tmp_path))
    try:
        url = f"http://localhost:{port}/api/debates/nonexistent"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(url)
        assert exc_info.value.code == 404
    finally:
        server.shutdown()
