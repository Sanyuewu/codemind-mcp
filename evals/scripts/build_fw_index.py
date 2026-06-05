"""
Build a fixed-window index for Experiment 1 (AST vs fixed window ablation).

Indexes only the 12 FastAPI source files that have gold passages in the eval set,
storing the result in <repo_path>/.codemind_fw/.

Usage:
    uv run python evals/scripts/build_fw_index.py --repo-path E:/DPJ/repos/fastapi
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import typer

app = typer.Typer()

KEY_FILES = [
    "fastapi/routing.py",
    "fastapi/applications.py",
    "fastapi/encoders.py",
    "fastapi/exception_handlers.py",
    "fastapi/background.py",
    "fastapi/datastructures.py",
    "fastapi/security/oauth2.py",
    "fastapi/security/api_key.py",
    "fastapi/security/utils.py",
    "fastapi/dependencies/utils.py",
    "fastapi/openapi/docs.py",
    "fastapi/openapi/utils.py",
]


async def _build(repo_path: Path) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

    from codemind.config import Settings
    from codemind.indexing.embedder import Embedder, chunk_to_text
    from codemind.indexing.fixed_window import fixed_window_chunk_file
    from codemind.models import FileMeta
    from codemind.storage.metadata_store import MetadataStore
    from codemind.storage.vector_store import VectorStore
    from datetime import datetime, timezone
    import hashlib

    data_dir = repo_path / ".codemind_fw"
    data_dir.mkdir(exist_ok=True)

    settings = Settings(repo_path=repo_path, data_dir=data_dir)
    metadata_store = MetadataStore(settings)
    vector_store = VectorStore(settings)

    typer.echo("Loading embedding model...")
    embedder = await asyncio.to_thread(Embedder, settings)
    await vector_store.ensure_ready()

    total_chunks = 0
    for rel_path in KEY_FILES:
        file_path = repo_path / rel_path
        if not file_path.exists():
            typer.echo(f"  SKIP (not found): {rel_path}")
            continue

        chunks = fixed_window_chunk_file(file_path, rel_path=rel_path)
        if not chunks:
            typer.echo(f"  SKIP (no chunks): {rel_path}")
            continue

        texts = [chunk_to_text(c) for c in chunks]
        embeddings = embedder.encode(texts)

        await metadata_store.delete_by_file(rel_path)
        await vector_store.delete_by_file(rel_path)

        for chunk in chunks:
            await metadata_store.save_chunk(chunk)
        await vector_store.upsert(chunks, embeddings)

        content = file_path.read_bytes()
        await metadata_store.save_file_meta(FileMeta(
            path=rel_path,
            language=chunks[0].language,
            content_hash=hashlib.sha256(content).hexdigest(),
            last_indexed_at=datetime.now(timezone.utc),
            chunk_count=len(chunks),
        ))

        total_chunks += len(chunks)
        typer.echo(f"  {rel_path}: {len(chunks)} windows")

    typer.echo(f"\nDone. Total: {total_chunks} windows in {data_dir}")


@app.command()
def main(
    repo_path: Path = typer.Option(..., help="Path to the FastAPI repository root"),
) -> None:
    """Index FastAPI key files with fixed-window chunking for ablation experiment."""
    asyncio.run(_build(repo_path))


if __name__ == "__main__":
    app()
