"""HTTP server for the debate viewer."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEBATE_SUBDIR = ".context/debate"


def scan_debates(cwd: str) -> list[dict]:
    """Scan for debate.json files and return summaries sorted newest first."""
    debate_root = Path(cwd) / DEBATE_SUBDIR
    if not debate_root.is_dir():
        return []

    summaries = []
    for debate_json in sorted(debate_root.glob("*/debate.json"), reverse=True):
        try:
            data = json.loads(debate_json.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Skipping malformed %s", debate_json)
            continue

        meta = data.get("meta", {})
        dedup = data.get("dedup") or {}
        disagreements = dedup.get("disagreements", [])

        summaries.append({
            "timestamp": debate_json.parent.name,
            "prompt": meta.get("prompt", ""),
            "providers": meta.get("providers", []),
            "disagreements_count": len(disagreements),
            "started_at": meta.get("started_at", ""),
        })

    return summaries


def load_debate(cwd: str, timestamp: str) -> dict | None:
    """Load a full debate.json by timestamp directory name."""
    debate_json = Path(cwd) / DEBATE_SUBDIR / timestamp / "debate.json"
    if not debate_json.is_file():
        return None
    try:
        return json.loads(debate_json.read_text())
    except (json.JSONDecodeError, OSError):
        return None
