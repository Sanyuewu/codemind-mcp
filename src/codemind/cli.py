from __future__ import annotations

import asyncio
import os
from pathlib import Path

import typer

app = typer.Typer(name="codemind", help="CodeMind MCP - Intelligent Code Search")


@app.command()
def index(
    repo_path: Path = typer.Argument(..., help="Path to the repository to index"),
    force: bool = typer.Option(False, "--force", help="Force full reindex"),
) -> None:
    """Index a code repository for semantic search."""
    asyncio.run(_async_index(repo_path.resolve(), force))


async def _async_index(repo_path: Path, force: bool) -> None:
    from codemind.config import Settings
    from codemind.indexing.embedder import Embedder
    from codemind.indexing.indexer import Indexer
    from codemind.storage.metadata_store import MetadataStore
    from codemind.storage.vector_store import VectorStore

    data_dir = (
        Path(os.environ["CODEMIND_DATA_DIR"])
        if "CODEMIND_DATA_DIR" in os.environ
        else repo_path / ".codemind"
    )
    config = Settings(repo_path=repo_path, data_dir=data_dir)

    typer.echo(f"Indexing {repo_path} ...")
    indexer = Indexer(
        config,
        MetadataStore(config),
        VectorStore(config),
        Embedder(config),
    )
    result = await indexer.index_repository(repo_path, force_rebuild=force)

    typer.echo(f"\n  total_files  : {result.total_files}")
    typer.echo(f"  indexed      : {result.indexed_files}")
    typer.echo(f"  skipped      : {result.skipped_files}")
    typer.echo(f"  total_chunks : {result.total_chunks}")
    typer.echo(f"  duration     : {result.duration_seconds:.1f}s")
    if result.errors:
        typer.echo(f"  errors ({len(result.errors)}):")
        for e in result.errors:
            typer.echo(f"    - {e}")


@app.command()
def serve() -> None:
    """Start the CodeMind MCP server."""
    from codemind.server import main

    asyncio.run(main())
