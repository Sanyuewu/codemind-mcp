from __future__ import annotations

import asyncio
import re
import time
from pathlib import PurePosixPath

import structlog

from codemind.config import Settings
from codemind.exceptions import RetrievalError
from codemind.indexing.embedder import Embedder
from typing import Literal

from codemind.models import CodeChunk, Reference, RetrievedChunk, SearchQuery
from codemind.retrieval.dense import DenseRetriever
from codemind.retrieval.hybrid import reciprocal_rank_fusion
from codemind.retrieval.rerank import Reranker
from codemind.retrieval.sparse import BM25Retriever
from codemind.storage.metadata_store import MetadataStore
from codemind.storage.vector_store import VectorStore

log = structlog.get_logger()


def _apply_source_boost(
    results: list[RetrievedChunk],
    settings: Settings,
) -> list[RetrievedChunk]:
    boosted = [
        RetrievedChunk(
            chunk=rc.chunk,
            score=rc.score * settings.source_boost_factor
            if not any(
                PurePosixPath(rc.chunk.file_path).match(pat)
                for pat in settings.test_doc_patterns
            )
            else rc.score,
            retrieval_method=rc.retrieval_method,
            debug_info=rc.debug_info,
        )
        for rc in results
    ]
    boosted.sort(key=lambda r: r.score, reverse=True)
    return boosted


class Retriever:
    def __init__(self, metadata_store: MetadataStore, settings: Settings) -> None:
        self._metadata_store = metadata_store
        self._settings = settings
        self._vector_store = VectorStore(settings)
        self._bm25 = BM25Retriever(metadata_store)
        self._reranker: Reranker | None = None
        self._embedder: Embedder | None = None
        self._dense: DenseRetriever | None = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._init_lock:
            if not self._initialized:
                if self._settings.enable_dense:
                    self._embedder = await asyncio.to_thread(Embedder, self._settings)
                    self._dense = DenseRetriever(self._embedder, self._vector_store)
                    if self._settings.enable_reranker:
                        self._reranker = await asyncio.to_thread(Reranker, self._settings)
                    # Pre-open Qdrant so _search_impl() only does the actual search
                    await self._vector_store.ensure_ready()
                if self._settings.enable_bm25:
                    await self._bm25.initialize()
                self._initialized = True

    async def search(self, query: SearchQuery) -> list[RetrievedChunk]:
        timeout = self._settings.retrieval_timeout_ms / 1000
        try:
            return await asyncio.wait_for(self._search_impl(query), timeout=timeout)
        except asyncio.TimeoutError:
            log.warning(
                "retrieval.timeout",
                query=query.query[:80],
                timeout_ms=self._settings.retrieval_timeout_ms,
            )
            raise RetrievalError(
                f"Search timed out after {self._settings.retrieval_timeout_ms}ms"
            )

    async def _search_impl(self, query: SearchQuery) -> list[RetrievedChunk]:
        qdrant_filters: dict = {}
        if query.language:
            qdrant_filters["language"] = query.language

        bm25_results: list[tuple[str, float]] = []
        dense_results: list[tuple[str, float]] = []

        tasks = []
        if self._settings.enable_bm25:
            tasks.append(asyncio.create_task(
                asyncio.to_thread(
                    self._bm25.search,
                    query.query,
                    self._settings.bm25_top_k,
                    query.language,
                )
            ))
        if self._settings.enable_dense:
            assert self._dense is not None
            tasks.append(asyncio.create_task(
                self._dense.search(
                    query.query,
                    self._settings.dense_top_k,
                    qdrant_filters or None,
                )
            ))

        results_list = await asyncio.gather(*tasks)
        idx = 0
        if self._settings.enable_bm25:
            bm25_results = results_list[idx]
            idx += 1
        if self._settings.enable_dense:
            dense_results = results_list[idx]

        # Determine fusion strategy and retrieval_method label
        only_bm25 = self._settings.enable_bm25 and not self._settings.enable_dense
        only_dense = self._settings.enable_dense and not self._settings.enable_bm25

        retrieval_method: Literal["bm25", "dense", "hybrid", "rerank"]
        if only_bm25:
            raw_candidates = bm25_results[: self._settings.rerank_input_top_k]
            retrieval_method = "bm25"
        elif only_dense:
            raw_candidates = dense_results[: self._settings.rerank_input_top_k]
            retrieval_method = "dense"
        else:
            raw_candidates = reciprocal_rank_fusion(
                bm25_results, dense_results, self._settings.rrf_k
            )[: self._settings.rerank_input_top_k]
            retrieval_method = "hybrid"

        if not raw_candidates:
            return []

        chunk_ids = [cid for cid, _ in raw_candidates]
        score_map = dict(raw_candidates)

        chunks_raw = await asyncio.gather(
            *[self._metadata_store.get_chunk(cid) for cid in chunk_ids]
        )
        chunks = [c for c in chunks_raw if c is not None]

        if query.chunk_types:
            chunks = [c for c in chunks if c.chunk_type in query.chunk_types]

        if not chunks:
            return []

        if self._reranker is not None:
            start_rr = time.monotonic()
            reranked = await self._reranker.rerank(query.query, chunks)
            duration_ms = round((time.monotonic() - start_rr) * 1000)
            log.debug(
                "retrieval.rerank",
                input_count=len(chunks),
                output_count=len(reranked),
                duration_ms=duration_ms,
            )
            if self._settings.source_boost_factor != 1.0:
                reranked = _apply_source_boost(reranked, self._settings)
            return reranked[: query.top_k]

        max_score = max((score_map[c.chunk_id] for c in chunks), default=1.0)
        if max_score == 0.0:
            max_score = 1.0
        ranked = [
            RetrievedChunk(
                chunk=chunk,
                score=score_map[chunk.chunk_id] / max_score,
                retrieval_method=retrieval_method,
                debug_info={"raw_score": score_map[chunk.chunk_id]},
            )
            for chunk in chunks
        ]
        ranked.sort(key=lambda r: r.score, reverse=True)
        if self._settings.source_boost_factor != 1.0:
            ranked = _apply_source_boost(ranked, self._settings)
        return ranked[: query.top_k]

    async def get_chunk_by_id(self, chunk_id: str) -> CodeChunk | None:
        return await self._metadata_store.get_chunk(chunk_id)

    async def find_function(
        self,
        name: str,
        file_path: str | None = None,
    ) -> list[CodeChunk]:
        return await self._metadata_store.find_by_name(name, file_path)

    async def find_references(
        self,
        symbol: str,
        language: str | None = None,
    ) -> list[Reference]:
        chunks = await self._metadata_store.search_in_code(symbol, language)
        refs: list[Reference] = []
        _symbol_re = re.compile(r"\b" + re.escape(symbol) + r"\b")
        for chunk in chunks:
            for i, line in enumerate(chunk.code.splitlines(), start=0):
                if _symbol_re.search(line):
                    refs.append(
                        Reference(
                            file_path=chunk.file_path,
                            line_number=chunk.start_line + i,
                            line_content=line.strip(),
                            enclosing_function=(
                                chunk.name if chunk.chunk_type != "module" else None
                            ),
                        )
                    )
        return refs
