from __future__ import annotations

import structlog

from codemind.config import Settings
from codemind.exceptions import ConfigError
from codemind.models import CodeChunk

log = structlog.get_logger()


def chunk_to_text(chunk: CodeChunk) -> str:
    parts = [
        chunk.signature or "",
        chunk.docstring or "",
        chunk.code,
    ]
    return " ".join(p for p in parts if p).strip()


class Embedder:
    def __init__(self, config: Settings) -> None:
        self._batch_size = config.embedding_batch_size
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(
                config.embedding_model,
                device=config.embedding_device,
            )
        except Exception as e:
            raise ConfigError(
                f"Failed to load embedding model '{config.embedding_model}': {e}"
            ) from e
        log.info(
            "embedder.loaded",
            model=config.embedding_model,
            device=config.embedding_device,
        )

    def encode(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._model.encode(
            texts,
            batch_size=self._batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [e.tolist() for e in embeddings]
