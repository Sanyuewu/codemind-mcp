from __future__ import annotations

import asyncio
import time

import structlog

from codemind.indexing.embedder import Embedder
from codemind.storage.vector_store import VectorStore

log = structlog.get_logger()


class DenseRetriever:
    def __init__(self, embedder: Embedder, vector_store: VectorStore) -> None:
        self._embedder = embedder
        self._vector_store = vector_store

    async def search(
        self,
        query: str,
        top_k: int,
        filters: dict | None = None,
    ) -> list[tuple[str, float]]:
        start = time.monotonic()
        embedding = await asyncio.to_thread(self._embedder.encode, [query])
        results = await self._vector_store.search(embedding[0], top_k, filters)
        duration_ms = round((time.monotonic() - start) * 1000)
        log.debug("retrieval.dense", query=query[:80], candidates=len(results), duration_ms=duration_ms)
        return results
