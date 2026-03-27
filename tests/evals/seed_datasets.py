"""Seed Langfuse datasets from fixture data.

Usage:
    uv run --extra eval python tests/evals/seed_datasets.py
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from langfuse import Langfuse

# Import helpers via sys.path since this runs as a standalone script
sys.path.insert(0, str(Path(__file__).parent))
from helpers import load_auth_scenario  # noqa: E402

DEDUP_DATASET = "dedup-eval"
SYNTHESIS_DATASET = "synthesis-eval"


def _serialize_scenario(prompt: str, responses: list) -> dict:
    """Serialize a scenario into a Langfuse dataset item input."""
    return {
        "prompt": prompt,
        "agent_responses": [
            {
                "agent_id": r.agent_id,
                "provider": r.provider,
                "model": r.model,
                "content": r.content,
            }
            for r in responses
        ],
    }


def seed() -> None:
    client = Langfuse()

    prompt, responses = load_auth_scenario()
    item_input = _serialize_scenario(prompt, responses)

    # --- Dedup dataset ---
    client.create_dataset(
        name=DEDUP_DATASET,
        description="Eval scenarios for the dedup prompt: extracts findings and disagreements from agent responses.",
    )
    client.create_dataset_item(
        dataset_name=DEDUP_DATASET,
        input=item_input,
        expected_output={
            "min_findings": 3,
            "has_disagreement": True,
            "expected_disagreement_terms": [["jwt", "token"], ["session", "cookie"]],
            "attribution_map": {"jwt": "architect", "session": "pragmatist"},
        },
        metadata={"scenario": "auth_module"},
    )
    print(f"Seeded {DEDUP_DATASET} with auth_module scenario")

    # --- Synthesis dataset ---
    client.create_dataset(
        name=SYNTHESIS_DATASET,
        description="Eval scenarios for the synthesis prompt: produces final recommendation from findings.",
    )
    client.create_dataset_item(
        dataset_name=SYNTHESIS_DATASET,
        input=item_input,
        expected_output={
            "min_word_count": 200,
            "max_word_count": 2000,
            "agent_positions": {
                "architect": ["jwt", "token"],
                "pragmatist": ["session", "cookie"],
                "reliability": ["rate limit", "audit", "security"],
            },
        },
        metadata={"scenario": "auth_module"},
    )
    print(f"Seeded {SYNTHESIS_DATASET} with auth_module scenario")

    client.flush()
    print("Done.")


if __name__ == "__main__":
    seed()
