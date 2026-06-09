"""Latency benchmark: p50/p95/p99 for the full retrieval pipeline."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import typer

app = typer.Typer(name="bench_latency", help="Measure retrieval latency (p50/p95/p99).")


def _load_flat_yaml(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip()
    return result


async def _run(
    repo_path: Path,
    eval_set_path: Path,
    config_path: Path | None,
    n_runs: int,
    warm_up: int,
    max_queries: int,
    output: Path,
) -> None:
    import structlog

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )

    if config_path:
        for k, v in _load_flat_yaml(config_path).items():
            os.environ[f"CODEMIND_{k.upper()}"] = v

    from codemind.config import Settings
    from codemind.models import SearchQuery
    from codemind.retrieval.retriever import Retriever
    from codemind.storage.metadata_store import MetadataStore

    settings = Settings(repo_path=repo_path)
    metadata_store = MetadataStore(settings)
    retriever = Retriever(metadata_store, settings)

    print("Initializing retriever (loading models)...", file=sys.stderr)
    await retriever.initialize()
    print("Ready.", file=sys.stderr)

    from codemind.exceptions import RetrievalError

    all_questions = [
        json.loads(line)["question"]
        for line in eval_set_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    questions = all_questions[:max_queries] if max_queries > 0 else all_questions

    config_name = config_path.stem if config_path else "default"
    per_query: list[dict] = []

    for i, q in enumerate(questions):
        query = SearchQuery(query=q, top_k=5)
        samples: list[float] = []
        timed_out = False

        # warm-up runs (not recorded, ignore timeouts)
        for _ in range(warm_up):
            try:
                await retriever.search(query)
            except RetrievalError:
                pass

        # timed runs
        for _ in range(n_runs):
            t0 = time.perf_counter()
            try:
                await retriever.search(query)
                samples.append((time.perf_counter() - t0) * 1000)
            except RetrievalError:
                elapsed = (time.perf_counter() - t0) * 1000
                samples.append(elapsed)
                timed_out = True
                break

        median_ms = statistics.median(samples) if samples else 0.0
        per_query.append({
            "id": f"q{i+1:03d}",
            "question": q[:60],
            "median_ms": round(median_ms, 1),
            "timed_out": timed_out,
        })
        flag = " [TIMEOUT]" if timed_out else ""
        print(f"  [{i+1:2d}/{len(questions)}] {median_ms:7.1f} ms  {q[:48]}{flag}", file=sys.stderr)

    n_timed_out = sum(1 for r in per_query if r.get("timed_out"))
    all_medians = [r["median_ms"] for r in per_query]
    all_medians.sort()
    n = len(all_medians)

    def _pct(p: float) -> float:
        idx = min(int(p / 100 * n), n - 1)
        return all_medians[idx]

    result = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "config": config_name,
        "repo_path": str(repo_path),
        "n_queries": n,
        "n_timed_out": n_timed_out,
        "n_runs_per_query": n_runs,
        "warm_up_runs": warm_up,
        "p50_ms": round(_pct(50), 1),
        "p95_ms": round(_pct(95), 1),
        "p99_ms": round(_pct(99), 1),
        "mean_ms": round(statistics.mean(all_medians), 1),
        "per_query": per_query,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nResults → {output}", file=sys.stderr)
    print(f"  p50  = {result['p50_ms']} ms", file=sys.stderr)
    print(f"  p95  = {result['p95_ms']} ms", file=sys.stderr)
    print(f"  p99  = {result['p99_ms']} ms", file=sys.stderr)
    print(f"  mean = {result['mean_ms']} ms", file=sys.stderr)
    if n_timed_out:
        print(f"  timeouts: {n_timed_out}/{n}", file=sys.stderr)


@app.command()
def main(
    repo_path: Path = typer.Option(..., "--repo-path", envvar="CODEMIND_EVAL_REPO_PATH"),
    eval_set: Path = typer.Option(Path("evals/eval_set.jsonl"), "--eval-set"),
    config: Path | None = typer.Option(None, "--config"),
    n_runs: int = typer.Option(1, "--n-runs", help="Timed runs per query"),
    warm_up: int = typer.Option(0, "--warm-up", help="Warm-up runs before timing"),
    max_queries: int = typer.Option(0, "--max-queries", help="Limit to first N queries (0 = all)"),
    output: Path = typer.Option(Path("evals/results/latency_benchmark.json"), "--output"),
) -> None:
    asyncio.run(_run(repo_path, eval_set, config, n_runs, warm_up, max_queries, output))


if __name__ == "__main__":
    app()
