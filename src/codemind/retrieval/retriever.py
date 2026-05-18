from __future__ import annotations

from codemind.config import Settings
from codemind.models import CodeChunk, Reference, RetrievedChunk, SearchQuery
from codemind.storage.metadata_store import MetadataStore


class Retriever:
    def __init__(self, metadata_store: MetadataStore, settings: Settings) -> None:
        self._metadata_store = metadata_store
        self._settings = settings

    async def search(self, query: SearchQuery) -> list[RetrievedChunk]:
        return []

    async def get_chunk_by_id(self, chunk_id: str) -> CodeChunk | None:
        return None

    async def find_function(
        self,
        name: str,
        file_path: str | None = None,
    ) -> list[CodeChunk]:
        return []

    async def find_references(
        self,
        symbol: str,
        language: str | None = None,
    ) -> list[Reference]:
        return []
