from __future__ import annotations

import asyncio

import structlog

from codemind.config import Settings
from codemind.exceptions import ConfigError
from codemind.models import CodeChunk, RetrievedChunk

log = structlog.get_logger()


class Reranker:
    def __init__(self, config: Settings) -> None:
        # FlagEmbedding 1.4.0 is incompatible with transformers 5.x (prepare_for_model removed).
        # CrossEncoder from sentence-transformers (already a dependency) uses the same model
        # and produces equivalent sigmoid-normalized scores in [0, 1].
        try:
            import torch
            from sentence_transformers.cross_encoder import CrossEncoder
            self._model = CrossEncoder(config.reranker_model, max_length=512)
            self._sigmoid = torch.nn.Sigmoid()
        except Exception as e:
            raise ConfigError(
                f"Failed to load reranker model '{config.reranker_model}': {e}"
            ) from e
        log.info("reranker.loaded", model=config.reranker_model)

    async def rerank(self, query: str, chunks: list[CodeChunk]) -> list[RetrievedChunk]:
        pairs = [[query, chunk.code] for chunk in chunks]
        raw_scores: list[float] = await asyncio.to_thread(
            self._model.predict, pairs, activation_fn=self._sigmoid
        )
        ranked = sorted(zip(chunks, raw_scores), key=lambda x: x[1], reverse=True)
        return [
            RetrievedChunk(
                chunk=chunk,
                score=float(score),
                retrieval_method="rerank",
                debug_info={"rerank_score": float(score)},
            )
            for chunk, score in ranked
        ]
