"""Integration tests for Embedder + VectorStore."""
from __future__ import annotations

import asyncio

import pytest

from codemind.config import Settings
from codemind.indexing.embedder import Embedder, chunk_to_text
from codemind.models import CodeChunk
from codemind.storage.vector_store import VectorStore


@pytest.fixture(scope="module")
def config(tmp_path_factory):
    root = tmp_path_factory.mktemp("codemind")
    return Settings(repo_path=root, data_dir=root / ".codemind")


@pytest.fixture(scope="module")
def embedder(config):
    return Embedder(config)


@pytest.fixture
def three_chunks():
    return [
        CodeChunk(
            chunk_id="a" * 16,
            file_path="src/auth.py",
            language="python",
            chunk_type="function",
            name="verify_token",
            signature="def verify_token(token: str) -> dict",
            docstring='"""Verify a JWT token and return its payload."""',
            code=(
                "def verify_token(token: str) -> dict:\n"
                '    """Verify a JWT token and return its payload."""\n'
                "    header, payload, sig = token.split('.')\n"
                "    return decode_base64(payload)\n"
            ),
            start_line=1,
            end_line=5,
        ),
        CodeChunk(
            chunk_id="b" * 16,
            file_path="src/db.py",
            language="python",
            chunk_type="function",
            name="connect_database",
            signature="def connect_database(url: str) -> Connection",
            docstring='"""Open a database connection to the given URL."""',
            code=(
                "def connect_database(url: str) -> Connection:\n"
                '    """Open a database connection to the given URL."""\n'
                "    engine = create_engine(url)\n"
                "    return engine.connect()\n"
            ),
            start_line=1,
            end_line=5,
        ),
        CodeChunk(
            chunk_id="c" * 16,
            file_path="src/cache.py",
            language="python",
            chunk_type="function",
            name="get_cached_value",
            signature="def get_cached_value(key: str) -> str | None",
            docstring='"""Retrieve a value from the in-memory cache by key."""',
            code=(
                "def get_cached_value(key: str) -> str | None:\n"
                '    """Retrieve a value from the in-memory cache by key."""\n'
                "    return _CACHE.get(key)\n"
            ),
            start_line=1,
            end_line=4,
        ),
    ]


def test_upsert_and_search(config, embedder, three_chunks, tmp_path):
    store = VectorStore(Settings(repo_path=tmp_path, data_dir=tmp_path / ".codemind"))

    async def _run():
        texts = [chunk_to_text(c) for c in three_chunks]
        embeddings = embedder.encode(texts)
        await store.upsert(three_chunks, embeddings)

        query_text = chunk_to_text(three_chunks[0])
        query_embedding = embedder.encode([query_text])[0]
        results = await store.search(query_embedding, top_k=1)

        assert len(results) == 1, f"Expected 1 result, got {len(results)}"
        assert results[0][0] == three_chunks[0].chunk_id, (
            f"Top-1 chunk_id {results[0][0]!r} != {three_chunks[0].chunk_id!r}"
        )
        assert results[0][1] > 0.9, (
            f"Self-similarity score {results[0][1]:.4f} is unexpectedly low"
        )

    asyncio.run(_run())


def test_delete_by_file(config, embedder, three_chunks, tmp_path):
    store = VectorStore(Settings(repo_path=tmp_path, data_dir=tmp_path / ".codemind2"))

    async def _run():
        texts = [chunk_to_text(c) for c in three_chunks]
        embeddings = embedder.encode(texts)
        await store.upsert(three_chunks, embeddings)

        count = await store.delete_by_file("src/auth.py")
        assert count == 1, f"Expected 1 deleted vector, got {count}"

        query_embedding = embedder.encode([chunk_to_text(three_chunks[0])])[0]
        results = await store.search(query_embedding, top_k=3)
        chunk_ids = [r[0] for r in results]
        assert three_chunks[0].chunk_id not in chunk_ids, (
            "Deleted chunk still appears in search results"
        )

    asyncio.run(_run())


def test_search_with_language_filter(config, embedder, three_chunks, tmp_path):
    store = VectorStore(Settings(repo_path=tmp_path, data_dir=tmp_path / ".codemind3"))

    async def _run():
        texts = [chunk_to_text(c) for c in three_chunks]
        embeddings = embedder.encode(texts)
        await store.upsert(three_chunks, embeddings)

        query_embedding = embedder.encode([chunk_to_text(three_chunks[0])])[0]
        results = await store.search(
            query_embedding, top_k=3, filters={"language": "python"}
        )
        assert len(results) == 3, (
            f"Expected 3 python results, got {len(results)}"
        )
        returned_ids = {r[0] for r in results}
        expected_ids = {c.chunk_id for c in three_chunks}
        assert returned_ids == expected_ids, (
            f"Filter returned unexpected chunk_ids: {returned_ids}"
        )

    asyncio.run(_run())
