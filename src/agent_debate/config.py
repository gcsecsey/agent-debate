"""Configuration parsing for the debate system."""

from __future__ import annotations

from .providers import PROVIDERS
from .types import DebateConfig, ProviderConfig


def parse_provider_string(spec: str) -> ProviderConfig:
    """Parse a provider spec like 'claude:opus' or 'codex' into a ProviderConfig."""
    parts = spec.strip().split(":", 1)
    provider = parts[0]
    model = parts[1] if len(parts) > 1 else None

    if provider not in PROVIDERS:
        available = ", ".join(PROVIDERS.keys())
        raise ValueError(f"Unknown provider '{provider}'. Available: {available}")

    return ProviderConfig(provider=provider, model=model)


def parse_providers_string(specs: str) -> list[ProviderConfig]:
    """Parse a comma-separated list of provider specs.

    Examples:
        "claude:opus,claude:sonnet,claude:haiku"
        "claude:opus,codex,gemini"
        "claude:opus,claude:opus,claude:opus"  (same provider multiple times)
    """
    configs = []
    for spec in specs.split(","):
        spec = spec.strip()
        if spec:
            configs.append(parse_provider_string(spec))

    if not configs:
        raise ValueError("No providers specified")

    # Disambiguate agent IDs when the same provider:model appears multiple times
    seen: dict[str, int] = {}
    for config in configs:
        base_id = config.agent_id
        count = seen.get(base_id, 0)
        seen[base_id] = count + 1
        if count > 0:
            # Append a suffix to make agent_id unique
            config.persona = config.persona  # preserve any existing persona
            # We'll handle dedup in the orchestrator via index

    return configs


def build_config(
    providers: str = "claude:opus,claude:sonnet,claude:haiku",
    max_rounds: int = 3,
    cwd: str = ".",
    orchestrator_model: str = "sonnet",
) -> DebateConfig:
    """Build a DebateConfig from CLI-style arguments."""
    return DebateConfig(
        providers=parse_providers_string(providers),
        max_rounds=max_rounds,
        cwd=cwd,
        orchestrator_model=orchestrator_model,
    )
