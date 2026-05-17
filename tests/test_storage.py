"""Integration tests for Embedder + VectorStore + MetadataStore + BM25Retriever."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from codemind.config import Settings
from codemind.indexing.embedder import Embedder, chunk_to_text
from codemind.models import CodeChunk, FileMeta
from codemind.retrieval.sparse import BM25Retriever
from codemind.storage.metadata_store import MetadataStore
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


# ---------------------------------------------------------------------------
# MetadataStore + BM25Retriever
# ---------------------------------------------------------------------------

_FILE_PATHS = {
    "src/auth.py": "python",
    "src/db.py": "python",
    "src/cache.py": "python",
}


def _save_meta_and_chunks(store: MetadataStore, chunks: list[CodeChunk], file_map: dict) -> None:
    async def _run():
        for fp, lang in file_map.items():
            await store.save_file_meta(FileMeta(
                path=fp, language=lang, content_hash="0" * 64,
                last_indexed_at=datetime.now(timezone.utc), chunk_count=1,
            ))
        for chunk in chunks:
            await store.save_chunk(chunk)
    asyncio.run(_run())


def test_metadata_save_and_bm25_search(three_chunks, tmp_path):
    cfg = Settings(repo_path=tmp_path, data_dir=tmp_path / ".codemind4")

    async def _run():
        store = MetadataStore(cfg)
        for fp, lang in _FILE_PATHS.items():
            await store.save_file_meta(FileMeta(
                path=fp, language=lang, content_hash="0" * 64,
                last_indexed_at=datetime.now(timezone.utc), chunk_count=1,
            ))
        for chunk in three_chunks:
            await store.save_chunk(chunk)

        retriever = BM25Retriever(store)
        await retriever.initialize()

        results = retriever.search("verify_token", top_k=3)
        assert len(results) >= 1, f"Expected at least 1 BM25 result, got {len(results)}"
        chunk_ids = [r[0] for r in results]
        assert three_chunks[0].chunk_id in chunk_ids, (
            f"Expected {three_chunks[0].chunk_id!r} in top-3, got {chunk_ids}"
        )
        # BM25 returns 0.0 for docs not containing the query term — only check top-1
        assert results[0][1] > 0.0, (
            f"Top BM25 score must be positive, got {results[0][1]}"
        )

    asyncio.run(_run())


def test_bm25_language_filter(three_chunks, tmp_path):
    ts_chunk = CodeChunk(
        chunk_id="d" * 16,
        file_path="src/utils.ts",
        language="typescript",
        chunk_type="function",
        name="verify_token",
        signature="function verify_token(token: string): object",
        docstring=None,
        code="function verify_token(token: string): object { return {}; }",
        start_line=1,
        end_line=1,
    )
    all_chunks = three_chunks + [ts_chunk]
    file_map = {**_FILE_PATHS, "src/utils.ts": "typescript"}

    cfg = Settings(repo_path=tmp_path, data_dir=tmp_path / ".codemind5")

    async def _run():
        store = MetadataStore(cfg)
        for fp, lang in file_map.items():
            await store.save_file_meta(FileMeta(
                path=fp, language=lang, content_hash="0" * 64,
                last_indexed_at=datetime.now(timezone.utc), chunk_count=1,
            ))
        for chunk in all_chunks:
            await store.save_chunk(chunk)

        retriever = BM25Retriever(store)
        await retriever.initialize()

        results_py = retriever.search("verify_token", top_k=4, language="python")
        ids = [r[0] for r in results_py]
        assert ts_chunk.chunk_id not in ids, (
            "TypeScript chunk must not appear in python-filtered results"
        )
        assert three_chunks[0].chunk_id in ids, (
            f"Python verify_token chunk {three_chunks[0].chunk_id!r} must appear in results"
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
