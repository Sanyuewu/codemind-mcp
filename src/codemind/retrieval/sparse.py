from __future__ import annotations

import re

import structlog
from rank_bm25 import BM25Okapi

from codemind.models import CodeChunk
from codemind.storage.metadata_store import MetadataStore

log = structlog.get_logger()


class BM25Retriever:
    def __init__(self, metadata_store: MetadataStore) -> None:
        self._store = metadata_store
        self._chunk_ids: list[str] = []
        self._language_map: dict[str, str] = {}
        self._bm25: BM25Okapi | None = None

    async def initialize(self) -> None:
        tokens_map = await self._store.get_all_tokens()
        self._language_map = await self._store._get_language_map()
        self._build_index(tokens_map)
        log.info("retrieval.bm25.initialized", chunks=len(tokens_map))

    def _build_index(self, tokens_map: dict[str, list[str]]) -> None:
        if not tokens_map:
            self._chunk_ids = []
            self._bm25 = None
            return
        self._chunk_ids = list(tokens_map)
        corpus = [tokens_map[cid] for cid in self._chunk_ids]
        self._bm25 = BM25Okapi(corpus)

    def search(
        self,
        query: str,
        top_k: int,
        language: str | None = None,
    ) -> list[tuple[str, float]]:
        if self._bm25 is None:
            return []
        tokens = re.findall(r"[a-zA-Z0-9_]+", query.lower())
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(
            (
                (cid, float(score))
                for cid, score in zip(self._chunk_ids, scores)
                if language is None or self._language_map.get(cid) == language
            ),
            key=lambda x: x[1],
            reverse=True,
        )
        results = ranked[:top_k]
        log.debug("retrieval.bm25", query=query[:80], candidates=len(results))
        return results

    async def update(self, new_chunks: list[CodeChunk]) -> None:
        await self.initialize()
