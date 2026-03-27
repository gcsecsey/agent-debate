"""Configuration parsing for the debate system."""

from __future__ import annotations

from .providers import PROVIDERS
from .types import DebateConfig, ProviderConfig

MODEL_GROUPS: dict[str, str] = {
    "top": "claude:opus,gemini,codex",
    "fast": "claude:sonnet,codex:codex-mini,gemini:gemini-2.0-flash",
}


def parse_provider_string(spec: str) -> ProviderConfig:
    """Parse a provider spec like 'claude:opus' or 'codex' into a ProviderConfig.

    Does not validate whether the provider exists — that's handled
    by the orchestrator at init time, which skips unknown/unavailable providers.
    """
    parts = spec.strip().split(":", 1)
    provider = parts[0]
    model = parts[1] if len(parts) > 1 else None
    return ProviderConfig(provider=provider, model=model)


def parse_providers_string(specs: str) -> list[ProviderConfig]:
    """Parse a comma-separated list of provider specs, or a group name.

    Examples:
        "top"                                    (expands to claude:opus,gemini,codex)
        "fast"                                   (expands to claude:sonnet,codex:codex-mini,gemini:gemini-2.0-flash)
        "claude:opus,claude:sonnet,claude:haiku"
        "claude:opus,codex,gemini"
    """
    specs = specs.strip()
    if specs in MODEL_GROUPS:
        specs = MODEL_GROUPS[specs]

    configs = []
    for spec in specs.split(","):
        spec = spec.strip()
        if spec:
            configs.append(parse_provider_string(spec))

    if not configs:
        raise ValueError("No providers specified")

    return configs


def build_config(
    providers: str = "top",
    max_rounds: int = 1,
    cwd: str = ".",
    orchestrator_model: str = "sonnet",
    report_dir: str | None = ".context/debate",
    agent_timeout: int = 300,
) -> DebateConfig:
    """Build a DebateConfig from CLI-style arguments."""
    return DebateConfig(
        providers=parse_providers_string(providers),
        max_rounds=max_rounds,
        cwd=cwd,
        orchestrator_model=orchestrator_model,
        report_dir=report_dir,
        agent_timeout=agent_timeout,
    )
