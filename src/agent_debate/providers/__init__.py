"""Provider adapters for AI coding agents."""

from .amp import AmpProvider
from .base import BaseProvider
from .claude import ClaudeProvider
from .codex import CodexProvider
from .gemini import GeminiProvider

PROVIDERS: dict[str, type[BaseProvider]] = {
    "claude": ClaudeProvider,
    "codex": CodexProvider,
    "gemini": GeminiProvider,
    "amp": AmpProvider,
}


def get_provider(name: str) -> type[BaseProvider]:
    """Get a provider class by name."""
    if name not in PROVIDERS:
        available = ", ".join(PROVIDERS.keys())
        raise ValueError(f"Unknown provider '{name}'. Available: {available}")
    return PROVIDERS[name]


def discover_available() -> dict[str, bool]:
    """Check which providers have their CLI/SDK available."""
    results = {}
    for name, cls in PROVIDERS.items():
        provider = cls()
        results[name] = provider.available()
    return results


__all__ = [
    "AmpProvider",
    "BaseProvider",
    "ClaudeProvider",
    "CodexProvider",
    "GeminiProvider",
    "discover_available",
    "get_provider",
    "PROVIDERS",
]
