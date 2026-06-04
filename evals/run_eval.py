"""Evaluation harness: Recall@1/3/5 + MRR against eval_set.jsonl."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import typer

app = typer.Typer(name="run_eval", help="Run CodeMind retrieval evaluation.")


def _compute_chunk_id(file_path: str, start_line: int) -> str:
    """Matches indexer convention: sha256(file_path:start_line)[:16]."""
    return hashlib.sha256(f"{file_path}:{start_line}".encode()).hexdigest()[:16]


def _load_flat_yaml(path: Path) -> dict[str, str]:
    """Parse a flat key: value YAML file (no nesting, no external deps)."""
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip()
    return result


def _recall_at_k(gold_ids: set[str], retrieved: list[str], k: int) -> float:
    return 1.0 if any(gid in retrieved[:k] for gid in gold_ids) else 0.0


def _mrr(gold_ids: set[str], retrieved: list[str]) -> float:
    for rank, cid in enumerate(retrieved, start=1):
        if cid in gold_ids:
            return 1.0 / rank
    return 0.0


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"R@1": 0.0, "R@3": 0.0, "R@5": 0.0, "MRR": 0.0, "n": 0}
    return {
        "R@1": round(sum(r["r1"] for r in rows) / n, 3),
        "R@3": round(sum(r["r3"] for r in rows) / n, 3),
        "R@5": round(sum(r["r5"] for r in rows) / n, 3),
        "MRR": round(sum(r["mrr"] for r in rows) / n, 3),
        "n": n,
    }


async def _run(
    repo_path: Path,
    eval_set_path: Path,
    config_path: Path | None,
    top_k: int,
) -> None:
    import structlog

    # Silence structlog noise during eval — keep only warnings+
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )

    # Apply YAML config overrides (maps key → CODEMIND_KEY env var)
    if config_path:
        for k, v in _load_flat_yaml(config_path).items():
            os.environ[f"CODEMIND_{k.upper()}"] = v

    from codemind.config import Settings
    from codemind.models import SearchQuery
    from codemind.retrieval.retriever import Retriever
    from codemind.storage.metadata_store import MetadataStore

    data_dir = repo_path / ".codemind"
    settings = Settings(repo_path=repo_path, data_dir=data_dir)

    metadata_store = MetadataStore(settings)
    retriever = Retriever(metadata_store, settings)

    typer.echo("Initializing retriever (loading embedding model)…")
    await retriever.initialize()
    typer.echo("Ready.\n")

    # Load eval set
    raw_lines = eval_set_path.read_text(encoding="utf-8").splitlines()
    items = [json.loads(line) for line in raw_lines if line.strip()]
    typer.echo(f"Loaded {len(items)} eval items from {eval_set_path}\n")

    per_item: list[dict[str, Any]] = []
    for item in items:
        gold_ids = {
            _compute_chunk_id(gp["file_path"], gp["start_line"])
            for gp in item["gold_passages"]
        }
        language = item.get("language")
        query = SearchQuery(query=item["question"], top_k=top_k, language=language)
        try:
            results = await retriever.search(query)
            retrieved_ids = [r.chunk.chunk_id for r in results]
        except Exception as exc:
            typer.echo(f"  ERROR [{item['id']}]: {exc}", err=True)
            retrieved_ids = []

        row: dict[str, Any] = {
            "id": item["id"],
            "intent_type": item["intent_type"],
            "question": item["question"][:80],
            "r1": _recall_at_k(gold_ids, retrieved_ids, 1),
            "r3": _recall_at_k(gold_ids, retrieved_ids, 3),
            "r5": _recall_at_k(gold_ids, retrieved_ids, 5),
            "mrr": _mrr(gold_ids, retrieved_ids),
            "retrieved_top3": retrieved_ids[:3],
        }
        per_item.append(row)
        marker = "OK" if row["r5"] else "--"
        typer.echo(f"  {marker} [{item['id']}] R@5={row['r5']:.0f}  MRR={row['mrr']:.2f}  {item['question'][:60]}")

    # Aggregate metrics
    overall = _aggregate(per_item)
    by_intent = {
        intent: _aggregate([r for r in per_item if r["intent_type"] == intent])
        for intent in ["locate", "understand", "compare"]
    }

    # Print summary table
    typer.echo("")
    typer.echo(f"{'Intent':<12} {'R@1':>6} {'R@3':>6} {'R@5':>6} {'MRR':>6} {'n':>4}")
    typer.echo("-" * 44)
    typer.echo(
        f"{'overall':<12} {overall['R@1']:>6.3f} {overall['R@3']:>6.3f}"
        f" {overall['R@5']:>6.3f} {overall['MRR']:>6.3f} {overall['n']:>4}"
    )
    for intent, metrics in by_intent.items():
        typer.echo(
            f"  {intent:<10} {metrics['R@1']:>6.3f} {metrics['R@3']:>6.3f}"
            f" {metrics['R@5']:>6.3f} {metrics['MRR']:>6.3f} {metrics['n']:>4}"
        )

    # Save results
    results_dir = eval_set_path.parent / "results"
    results_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    cfg_name = config_path.stem if config_path else "default"
    result_file = results_dir / f"{ts}_{cfg_name}.json"
    result_file.write_text(
        json.dumps(
            {
                "timestamp": ts,
                "config": cfg_name,
                "repo_path": str(repo_path),
                "overall": overall,
                "by_intent": by_intent,
                "per_item": per_item,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    typer.echo(f"\nResults saved → {result_file}")


@app.command()
def main(
    repo_path: Path = typer.Option(
        ...,
        "--repo-path",
        help="Path to the indexed repository (must contain .codemind/)",
        envvar="CODEMIND_EVAL_REPO_PATH",
    ),
    eval_set: Path = typer.Option(
        Path("evals/eval_set.jsonl"),
        "--eval-set",
        help="Path to eval_set.jsonl",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="YAML config file with Settings overrides (key: value)",
    ),
    top_k: int = typer.Option(
        5,
        "--top-k",
        help="Maximum number of results to retrieve per query",
    ),
) -> None:
    asyncio.run(_run(repo_path, eval_set, config, top_k))


if __name__ == "__main__":
    app()
