from __future__ import annotations

import asyncio

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from codemind.config import Settings
from codemind.exceptions import StorageError
from codemind.models import CodeChunk

log = structlog.get_logger()

_COLLECTION = "codemind_chunks"


class VectorStore:
    def __init__(self, config: Settings) -> None:
        self._qdrant_path = str(config.data_dir / "qdrant")
        self._dim = config.embedding_dim
        self._client: AsyncQdrantClient | None = None
        self._ready = False

    async def ensure_ready(self) -> None:
        """Pre-open Qdrant client and verify collection. Call during warmup."""
        await self._ensure_collection()

    async def _ensure_collection(self) -> None:
        if self._ready:
            return
        if self._client is None:
            # Run synchronous Qdrant init (portalocker + disk I/O) in a thread
            # so the event loop is never blocked while waiting for the file lock.
            _path = self._qdrant_path
            self._client = await asyncio.to_thread(
                lambda: AsyncQdrantClient(path=_path)
            )
        try:
            collections = await self._client.get_collections()
            names = {c.name for c in collections.collections}
            if _COLLECTION not in names:
                await self._client.create_collection(
                    collection_name=_COLLECTION,
                    vectors_config=VectorParams(size=self._dim, distance=Distance.COSINE),
                )
                log.info("vector_store.collection_created", collection=_COLLECTION, dim=self._dim)
            self._ready = True
        except Exception as e:
            raise StorageError(f"Failed to initialize Qdrant collection: {e}") from e

    async def upsert(
        self,
        chunks: list[CodeChunk],
        embeddings: list[list[float]],
    ) -> None:
        await self._ensure_collection()
        points = [
            PointStruct(
                id=int(chunk.chunk_id, 16),
                vector=embedding,
                payload={
                    "chunk_id": chunk.chunk_id,
                    "file_path": chunk.file_path,
                    "language": chunk.language,
                    "chunk_type": chunk.chunk_type,
                    "name": chunk.name,
                },
            )
            for chunk, embedding in zip(chunks, embeddings)
        ]
        try:
            await self._client.upsert(collection_name=_COLLECTION, points=points)
            log.debug("vector_store.upserted", count=len(points))
        except Exception as e:
            raise StorageError(f"Qdrant upsert failed: {e}") from e

    async def search(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: dict | None = None,
    ) -> list[tuple[str, float]]:
        await self._ensure_collection()
        qdrant_filter: Filter | None = None
        if filters:
            qdrant_filter = Filter(
                must=[
                    FieldCondition(key=k, match=MatchValue(value=v))
                    for k, v in filters.items()
                ]
            )
        try:
            result = await self._client.query_points(
                collection_name=_COLLECTION,
                query=query_embedding,
                query_filter=qdrant_filter,
                limit=top_k,
                with_payload=True,
            )
            return [(hit.payload["chunk_id"], hit.score) for hit in result.points]
        except Exception as e:
            raise StorageError(f"Qdrant search failed: {e}") from e

    async def delete_by_file(self, file_path: str) -> int:
        await self._ensure_collection()
        try:
            scroll_filter = Filter(
                must=[FieldCondition(key="file_path", match=MatchValue(value=file_path))]
            )
            results, _ = await self._client.scroll(
                collection_name=_COLLECTION,
                scroll_filter=scroll_filter,
                limit=10000,
                with_payload=False,
                with_vectors=False,
            )
            count = len(results)
            if results:
                await self._client.delete(
                    collection_name=_COLLECTION,
                    points_selector=[r.id for r in results],
                )
                log.debug("vector_store.deleted", file_path=file_path, count=count)
            return count
        except Exception as e:
            raise StorageError(f"Qdrant delete failed: {e}") from e
