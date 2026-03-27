"""Agent persona loader — reads persona definitions from JSON files."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PERSONAS_DIR = Path(__file__).parent / "personas"

# Default rotation order when no explicit personas are set
DEFAULT_ROTATION = [
    "security",
    "performance",
    "architecture",
    "reliability",
    "maintainability",
]


def _load_persona(path: Path) -> dict | None:
    """Load a single persona JSON file. Returns None on error."""
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or "name" not in data:
            logger.warning("Invalid persona file %s: missing 'name' field", path)
            return None
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load persona %s: %s", path, e)
        return None


def load_all_personas() -> dict[str, dict]:
    """Load all persona JSON files from the personas directory.

    Returns a dict mapping persona name to full persona data.
    """
    personas = {}
    if not PERSONAS_DIR.is_dir():
        return personas
    for path in sorted(PERSONAS_DIR.glob("*.json")):
        data = _load_persona(path)
        if data:
            personas[data["name"]] = data
    return personas


def get_persona(name: str) -> dict | None:
    """Get a single persona by name."""
    path = PERSONAS_DIR / f"{name}.json"
    if path.is_file():
        return _load_persona(path)
    return None


def get_persona_instruction(persona: str) -> str:
    """Get the system prompt instruction for a persona.

    Returns empty string for unknown personas so callers don't need to check.
    """
    data = get_persona(persona)
    if not data:
        return ""
    return data.get("instruction", "")


def auto_assign_personas(count: int) -> list[str | None]:
    """Return a list of persona names for N agents, cycling through defaults."""
    return [DEFAULT_ROTATION[i % len(DEFAULT_ROTATION)] for i in range(count)]
