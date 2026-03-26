"""Agent persona definitions for differentiated analysis perspectives."""

from __future__ import annotations

PERSONAS: dict[str, str] = {
    "security": (
        "Focus on security vulnerabilities, auth flaws, injection risks, "
        "and data exposure. Flag anything that could be exploited."
    ),
    "performance": (
        "Focus on performance bottlenecks, memory usage, query efficiency, "
        "caching opportunities, and scalability concerns."
    ),
    "architecture": (
        "Focus on code organization, separation of concerns, extensibility, "
        "dependency management, and design patterns."
    ),
    "reliability": (
        "Focus on error handling, edge cases, failure modes, data integrity, "
        "and operational concerns."
    ),
    "maintainability": (
        "Focus on code clarity, test coverage, documentation gaps, tech debt, "
        "and onboarding friction."
    ),
}

# Default rotation when no explicit personas are set
DEFAULT_ROTATION = [
    "security",
    "performance",
    "architecture",
    "reliability",
    "maintainability",
]


def get_persona_instruction(persona: str) -> str:
    """Build a system prompt instruction for a persona.

    Returns empty string for unknown personas so callers don't need to check.
    """
    description = PERSONAS.get(persona)
    if not description:
        return ""
    return (
        f"You are analyzing this from a **{persona}** perspective. "
        f"{description}\n\n"
        "Still provide a complete analysis, but weight your attention "
        "toward your area of expertise."
    )


def auto_assign_personas(count: int) -> list[str | None]:
    """Return a list of persona names for N agents, cycling through defaults."""
    return [DEFAULT_ROTATION[i % len(DEFAULT_ROTATION)] for i in range(count)]
