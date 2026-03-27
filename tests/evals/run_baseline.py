"""Baseline runner: run evals N times, aggregate scores, save to Langfuse datasets.

Usage:
    uv run --extra eval python tests/evals/run_baseline.py              # 5 runs (default)
    uv run --extra eval python tests/evals/run_baseline.py --runs 10    # custom
"""

from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import anyio
import click
from rich.console import Console
from rich.table import Table

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from langfuse import Langfuse

from agent_debate.orchestrator import Orchestrator
from agent_debate.prompts import build_dedup_prompt, build_synthesis_prompt
from agent_debate.types import AgentResponse

# Import helpers and scoring via sys.path since this runs as a standalone script
sys.path.insert(0, str(Path(__file__).parent))
from helpers import call_llm, get_commit_sha  # noqa: E402
from scoring import (  # noqa: E402
    TOKEN_BUDGETS,
    score_agent_references,
    score_agent_refs,
    score_balance,
    score_clear_recommendation,
    score_disagreement_detected,
    score_disagreement_quality,
    score_faithfulness,
    score_finding_attribution,
    score_has_findings,
    score_has_sections,
    score_no_duplicates,
    score_severity_distribution,
    score_token_budget,
    score_total_orchestrator_tokens,
    score_valid_json,
    score_valid_severities,
    score_word_count,
)
from seed_datasets import DEDUP_DATASET, SYNTHESIS_DATASET  # noqa: E402

BASELINES_DIR = Path(__file__).parent / "baselines"

console = Console()


def _deserialize_responses(item_input: dict) -> tuple[str, list[AgentResponse]]:
    """Reconstruct prompt and AgentResponse objects from a dataset item."""
    prompt = item_input["prompt"]
    responses = [
        AgentResponse(
            agent_id=r["agent_id"],
            provider=r["provider"],
            model=r["model"],
            round_number=1,
            content=r["content"],
        )
        for r in item_input["agent_responses"]
    ]
    return prompt, responses


async def _run_dedup_eval(
    prompt: str,
    responses: list[AgentResponse],
    expected_output: dict | None,
) -> tuple[str, dict[str, int] | None, list[tuple[str, float, str]]]:
    """Run one dedup eval iteration. Returns (raw_output, usage, scores)."""
    dedup_prompt = build_dedup_prompt(prompt, responses)
    raw, usage = await call_llm(dedup_prompt, model="haiku")
    findings, disagreements = Orchestrator._parse_dedup_response(raw)

    valid_ids = {r.agent_id for r in responses}
    expected = expected_output or {}

    scores = [
        # Structural
        score_valid_json(raw),
        score_has_findings(findings),
        score_agent_refs(findings, valid_ids),
        score_valid_severities(findings),
        # Quality
        score_disagreement_detected(disagreements),
        score_no_duplicates(findings),
        score_disagreement_quality(
            disagreements,
            expected.get("expected_disagreement_terms", []),
        ),
        score_severity_distribution(findings),
        score_finding_attribution(
            findings,
            expected.get("attribution_map", {}),
        ),
        # Efficiency
        score_token_budget(usage, TOKEN_BUDGETS["dedup_output"], "dedup"),
    ]
    return raw, usage, scores


async def _run_synthesis_eval(
    prompt: str,
    responses: list[AgentResponse],
    expected_output: dict | None,
) -> tuple[str, str, dict | None, dict | None, list[tuple[str, float, str]]]:
    """Run one synthesis eval iteration (dedup + synthesis chain).

    Returns (dedup_raw, synthesis_raw, dedup_usage, synthesis_usage, scores).
    """
    expected = expected_output or {}

    # Phase 1: dedup
    dedup_prompt = build_dedup_prompt(prompt, responses)
    dedup_raw, dedup_usage = await call_llm(dedup_prompt, model="haiku")
    findings, disagreements = Orchestrator._parse_dedup_response(dedup_raw)

    # Format findings for synthesis
    findings_lines = []
    for f in findings:
        agents = ", ".join(f.agents)
        findings_lines.append(
            f"- **[{f.severity.upper()}]** {f.topic} (flagged by: {agents})\n"
            f"  {f.description}"
        )
    findings_text = (
        "\n\n".join(findings_lines) if findings_lines else "No findings extracted."
    )

    # Phase 2: synthesis
    synthesis_prompt = build_synthesis_prompt(
        user_prompt=prompt,
        responses=responses,
        findings_text=findings_text,
        disagreements=disagreements,
    )
    synthesis_raw, synthesis_usage = await call_llm(synthesis_prompt, model="sonnet")

    agent_ids = {r.agent_id for r in responses}

    # Build agent responses text for faithfulness judge
    agent_responses_text = "\n\n---\n\n".join(
        f"**{r.agent_id}** ({r.provider}/{r.model}):\n{r.content}"
        for r in responses
    )

    # Run faithfulness judge (async LLM call)
    faithfulness = await score_faithfulness(
        agent_responses_text, synthesis_raw, call_llm
    )

    scores = [
        # Structural
        score_has_sections(synthesis_raw),
        score_agent_references(synthesis_raw, agent_ids),
        score_word_count(synthesis_raw),
        # Quality
        score_clear_recommendation(synthesis_raw),
        score_balance(synthesis_raw, expected.get("agent_positions", {})),
        faithfulness,
        # Efficiency
        score_token_budget(synthesis_usage, TOKEN_BUDGETS["synthesis_output"], "synthesis"),
        score_total_orchestrator_tokens(
            dedup_usage, synthesis_usage, TOKEN_BUDGETS["total_orchestrator"]
        ),
    ]
    return dedup_raw, synthesis_raw, dedup_usage, synthesis_usage, scores


def _aggregate_scores(
    all_scores: list[list[tuple[str, float, str]]],
) -> dict[str, dict]:
    """Aggregate scores across N runs into mean/stddev/values."""
    by_name: dict[str, list[float]] = {}
    for run_scores in all_scores:
        for name, value, _ in run_scores:
            by_name.setdefault(name, []).append(value)

    result = {}
    for name, values in by_name.items():
        result[name] = {
            "mean": round(statistics.mean(values), 4),
            "stddev": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
            "values": [round(v, 4) for v in values],
        }
    return result


def _aggregate_token_usage(
    all_usage: list[dict[str, int | None]],
) -> dict[str, dict]:
    """Aggregate token usage dicts across N runs."""
    by_key: dict[str, list[int]] = {}
    for usage in all_usage:
        if usage is None:
            continue
        for key, val in usage.items():
            if isinstance(val, int):
                by_key.setdefault(key, []).append(val)

    result = {}
    for key, values in by_key.items():
        result[key] = {
            "mean": round(statistics.mean(values), 1),
            "stddev": round(statistics.stdev(values), 1) if len(values) > 1 else 0.0,
            "values": values,
        }
    return result


def _print_results(aggregated: dict[str, dict], num_runs: int, run_name: str) -> None:
    """Print a Rich table of baseline results."""
    table = Table(title=f"Baseline: {run_name} ({num_runs} runs)")
    table.add_column("Metric", style="cyan")
    table.add_column("Mean", justify="right", style="green")
    table.add_column("Stddev", justify="right", style="yellow")
    table.add_column("Min", justify="right")
    table.add_column("Max", justify="right")

    for name, stats in sorted(aggregated.items()):
        values = stats["values"]
        table.add_row(
            name,
            f"{stats['mean']:.2f}",
            f"{stats['stddev']:.2f}",
            f"{min(values):.2f}",
            f"{max(values):.2f}",
        )

    console.print()
    console.print(table)


async def run_baseline(num_runs: int) -> None:
    client = Langfuse()

    commit_sha = get_commit_sha()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_name = f"baseline-{date_str}-{commit_sha[:7]}"

    console.print(f"[bold]Running baseline:[/bold] {run_name}")
    console.print(f"  Runs: {num_runs}, Commit: {commit_sha[:7]}")

    # Fetch datasets
    try:
        dedup_dataset = client.get_dataset(DEDUP_DATASET)
        synthesis_dataset = client.get_dataset(SYNTHESIS_DATASET)
    except Exception as e:
        console.print(f"[red]Failed to fetch datasets.[/red] Run seed_datasets first:")
        console.print(f"  uv run --extra eval python tests/evals/seed_datasets.py")
        console.print(f"  Error: {e}")
        sys.exit(1)

    all_dedup_scores: list[list[tuple[str, float, str]]] = []
    all_synthesis_scores: list[list[tuple[str, float, str]]] = []
    all_dedup_usage: list[dict[str, int] | None] = []
    all_synthesis_usage: list[dict[str, int] | None] = []

    for i in range(num_runs):
        console.print(f"\n[bold]Run {i + 1}/{num_runs}[/bold]")

        # --- Dedup evals ---
        for item in dedup_dataset.items:
            prompt, responses = _deserialize_responses(item.input)
            scenario = item.metadata.get("scenario", "unknown") if item.metadata else "unknown"
            expected = item.expected_output if item.expected_output else {}

            console.print(f"  dedup [{scenario}] ...", end=" ")
            raw, usage, scores = await _run_dedup_eval(prompt, responses, expected)
            all_dedup_scores.append(scores)
            all_dedup_usage.append(usage)

            # Log to Langfuse
            trace = client.trace(
                name="eval:dedup",
                input=prompt,
                output=raw,
                metadata={
                    "run_name": run_name,
                    "commit_sha": commit_sha,
                    "iteration": i + 1,
                    "scenario": scenario,
                    "model": "haiku",
                },
            )
            trace.generation(
                name="dedup_call",
                model="haiku",
                input=prompt,
                output=raw,
                usage=usage,
            )
            for name, value, comment in scores:
                trace.score(name=name, value=value, comment=comment)
            item.link(trace, run_name=run_name)

            score_summary = ", ".join(f"{n.split('/')[-1]}={v:.1f}" for n, v, _ in scores)
            console.print(f"[green]done[/green] ({score_summary})")

        # --- Synthesis evals ---
        for item in synthesis_dataset.items:
            prompt, responses = _deserialize_responses(item.input)
            scenario = item.metadata.get("scenario", "unknown") if item.metadata else "unknown"
            expected = item.expected_output if item.expected_output else {}

            console.print(f"  synthesis [{scenario}] ...", end=" ")
            dedup_raw, synthesis_raw, dedup_usage, synthesis_usage, scores = (
                await _run_synthesis_eval(prompt, responses, expected)
            )
            all_synthesis_scores.append(scores)
            all_synthesis_usage.append(synthesis_usage)

            # Log to Langfuse
            trace = client.trace(
                name="eval:synthesis",
                input=prompt,
                output=synthesis_raw,
                metadata={
                    "run_name": run_name,
                    "commit_sha": commit_sha,
                    "iteration": i + 1,
                    "scenario": scenario,
                    "dedup_model": "haiku",
                    "synthesis_model": "sonnet",
                },
            )
            trace.generation(
                name="dedup_call",
                model="haiku",
                input=dedup_raw,
                output=dedup_raw,
                usage=dedup_usage,
            )
            trace.generation(
                name="synthesis_call",
                model="sonnet",
                input=synthesis_raw,
                output=synthesis_raw,
                usage=synthesis_usage,
            )
            for name, value, comment in scores:
                trace.score(name=name, value=value, comment=comment)
            item.link(trace, run_name=run_name)

            score_summary = ", ".join(f"{n.split('/')[-1]}={v:.1f}" for n, v, _ in scores)
            console.print(f"[green]done[/green] ({score_summary})")

    client.flush()

    # Aggregate
    all_scores = all_dedup_scores + all_synthesis_scores
    aggregated = _aggregate_scores(all_scores)

    _print_results(aggregated, num_runs, run_name)

    # Save baseline JSON
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    baseline = {
        "run_name": run_name,
        "commit_sha": commit_sha,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "num_runs": num_runs,
        "scores": aggregated,
        "token_usage": {
            "dedup": _aggregate_token_usage(all_dedup_usage),
            "synthesis": _aggregate_token_usage(all_synthesis_usage),
        },
    }
    out_path = BASELINES_DIR / f"{run_name}.json"
    out_path.write_text(json.dumps(baseline, indent=2) + "\n")
    console.print(f"\nBaseline saved to [bold]{out_path}[/bold]")


@click.command()
@click.option("--runs", default=5, help="Number of eval iterations to run.", show_default=True)
def main(runs: int) -> None:
    """Run eval baseline: N iterations with aggregation and Langfuse tracking."""
    anyio.run(run_baseline, runs)


if __name__ == "__main__":
    main()
