from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

import structlog
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from codemind.config import Settings
from codemind.exceptions import StorageError
from codemind.models import CodeChunk, FileMeta

log = structlog.get_logger()


def _tokenize(chunk: CodeChunk) -> str:
    text = " ".join(filter(None, [chunk.name, chunk.signature or "", chunk.code]))
    return " ".join(re.findall(r"[a-zA-Z0-9_]+", text))


class MetadataStore:
    def __init__(self, config: Settings) -> None:
        db_path = config.data_dir / "metadata.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{db_path}", echo=False)
        self._meta = MetaData()

        self._files_tbl = Table(
            "files",
            self._meta,
            Column("path", String, primary_key=True),
            Column("language", String, nullable=False),
            Column("content_hash", String, nullable=False),
            Column("last_indexed_at", DateTime, nullable=False),
            Column("chunk_count", Integer, nullable=False),
        )

        self._chunks_tbl = Table(
            "chunks",
            self._meta,
            Column("chunk_id", String, primary_key=True),
            Column("file_path", String, ForeignKey("files.path"), nullable=False),
            Column("language", String, nullable=False),
            Column("chunk_type", String, nullable=False),
            Column("name", String, nullable=False),
            Column("signature", Text),
            Column("docstring", Text),
            Column("code", Text, nullable=False),
            Column("start_line", Integer, nullable=False),
            Column("end_line", Integer, nullable=False),
            Column("parent_name", String),
            Column("tokens", Text, nullable=False),
        )

        self._meta.create_all(self._engine)

    # ── private sync helpers ──────────────────────────────────────────────────

    def _sync_save_chunk(self, chunk: CodeChunk) -> None:
        tokens = _tokenize(chunk)
        stmt = sqlite_insert(self._chunks_tbl).values(
            chunk_id=chunk.chunk_id,
            file_path=chunk.file_path,
            language=chunk.language,
            chunk_type=chunk.chunk_type,
            name=chunk.name,
            signature=chunk.signature,
            docstring=chunk.docstring,
            code=chunk.code,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            parent_name=chunk.parent_name,
            tokens=tokens,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["chunk_id"],
            set_={
                "file_path": stmt.excluded.file_path,
                "language": stmt.excluded.language,
                "chunk_type": stmt.excluded.chunk_type,
                "name": stmt.excluded.name,
                "signature": stmt.excluded.signature,
                "docstring": stmt.excluded.docstring,
                "code": stmt.excluded.code,
                "start_line": stmt.excluded.start_line,
                "end_line": stmt.excluded.end_line,
                "parent_name": stmt.excluded.parent_name,
                "tokens": stmt.excluded.tokens,
            },
        )
        with self._engine.begin() as conn:
            conn.execute(stmt)
        log.debug("metadata_store.saved_chunk", chunk_id=chunk.chunk_id, file_path=chunk.file_path)

    def _row_to_chunk(self, row) -> CodeChunk:
        return CodeChunk(
            chunk_id=row.chunk_id,
            file_path=row.file_path,
            language=row.language,
            chunk_type=row.chunk_type,
            name=row.name,
            signature=row.signature,
            docstring=row.docstring,
            code=row.code,
            start_line=row.start_line,
            end_line=row.end_line,
            parent_name=row.parent_name,
        )

    def _row_to_file_meta(self, row) -> FileMeta:
        last_indexed_at = row.last_indexed_at
        if isinstance(last_indexed_at, str):
            last_indexed_at = datetime.fromisoformat(last_indexed_at)
        if last_indexed_at.tzinfo is None:
            last_indexed_at = last_indexed_at.replace(tzinfo=timezone.utc)
        return FileMeta(
            path=row.path,
            language=row.language,
            content_hash=row.content_hash,
            last_indexed_at=last_indexed_at,
            chunk_count=row.chunk_count,
        )

    # ── public async interface (§2.4) ─────────────────────────────────────────

    async def save_chunk(self, chunk: CodeChunk) -> None:
        try:
            await asyncio.to_thread(self._sync_save_chunk, chunk)
        except Exception as e:
            raise StorageError(f"Failed to save chunk {chunk.chunk_id}: {e}") from e

    async def get_chunk(self, chunk_id: str) -> CodeChunk | None:
        def _sync() -> CodeChunk | None:
            with self._engine.connect() as conn:
                row = conn.execute(
                    select(self._chunks_tbl).where(
                        self._chunks_tbl.c.chunk_id == chunk_id
                    )
                ).first()
            return self._row_to_chunk(row) if row else None

        try:
            return await asyncio.to_thread(_sync)
        except Exception as e:
            raise StorageError(f"Failed to get chunk {chunk_id}: {e}") from e

    async def get_chunks_by_file(self, file_path: str) -> list[CodeChunk]:
        def _sync() -> list[CodeChunk]:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    select(self._chunks_tbl).where(
                        self._chunks_tbl.c.file_path == file_path
                    )
                ).fetchall()
            return [self._row_to_chunk(r) for r in rows]

        try:
            return await asyncio.to_thread(_sync)
        except Exception as e:
            raise StorageError(f"Failed to get chunks for {file_path}: {e}") from e

    async def delete_by_file(self, file_path: str) -> int:
        def _sync() -> int:
            with self._engine.begin() as conn:
                result = conn.execute(
                    delete(self._chunks_tbl).where(
                        self._chunks_tbl.c.file_path == file_path
                    )
                )
                return result.rowcount

        try:
            count = await asyncio.to_thread(_sync)
            log.debug("metadata_store.deleted_chunks", file_path=file_path, count=count)
            return count
        except Exception as e:
            raise StorageError(f"Failed to delete chunks for {file_path}: {e}") from e

    async def get_all_tokens(self) -> dict[str, list[str]]:
        def _sync() -> dict[str, list[str]]:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    select(self._chunks_tbl.c.chunk_id, self._chunks_tbl.c.tokens)
                ).fetchall()
            return {r.chunk_id: r.tokens.split() for r in rows}

        try:
            return await asyncio.to_thread(_sync)
        except Exception as e:
            raise StorageError(f"Failed to load tokens: {e}") from e

    async def get_file_meta(self, path: str) -> FileMeta | None:
        def _sync() -> FileMeta | None:
            with self._engine.connect() as conn:
                row = conn.execute(
                    select(self._files_tbl).where(self._files_tbl.c.path == path)
                ).first()
            return self._row_to_file_meta(row) if row else None

        try:
            return await asyncio.to_thread(_sync)
        except Exception as e:
            raise StorageError(f"Failed to get file meta for {path}: {e}") from e

    async def save_file_meta(self, meta: FileMeta) -> None:
        def _sync() -> None:
            stmt = sqlite_insert(self._files_tbl).values(
                path=meta.path,
                language=meta.language,
                content_hash=meta.content_hash,
                last_indexed_at=meta.last_indexed_at,
                chunk_count=meta.chunk_count,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["path"],
                set_={
                    "language": stmt.excluded.language,
                    "content_hash": stmt.excluded.content_hash,
                    "last_indexed_at": stmt.excluded.last_indexed_at,
                    "chunk_count": stmt.excluded.chunk_count,
                },
            )
            with self._engine.begin() as conn:
                conn.execute(stmt)

        try:
            await asyncio.to_thread(_sync)
            log.debug("metadata_store.saved_file_meta", path=meta.path)
        except Exception as e:
            raise StorageError(f"Failed to save file meta for {meta.path}: {e}") from e

    async def list_files(
        self,
        language: str | None = None,
        directory: str | None = None,
        pattern: str | None = None,
    ) -> list[FileMeta]:
        def _sync() -> list[FileMeta]:
            stmt = select(self._files_tbl)
            if language is not None:
                stmt = stmt.where(self._files_tbl.c.language == language)
            if directory is not None:
                stmt = stmt.where(self._files_tbl.c.path.like(f"{directory}%"))
            if pattern is not None:
                sql_pattern = pattern.replace("**", "%").replace("*", "%")
                stmt = stmt.where(self._files_tbl.c.path.like(sql_pattern))
            with self._engine.connect() as conn:
                rows = conn.execute(stmt).fetchall()
            return [self._row_to_file_meta(r) for r in rows]

        try:
            return await asyncio.to_thread(_sync)
        except Exception as e:
            raise StorageError(f"Failed to list files: {e}") from e

    async def get_all_file_paths(self) -> list[str]:
        def _sync() -> list[str]:
            with self._engine.connect() as conn:
                rows = conn.execute(select(self._files_tbl.c.path)).fetchall()
            return [r.path for r in rows]

        try:
            return await asyncio.to_thread(_sync)
        except Exception as e:
            raise StorageError(f"Failed to get file paths: {e}") from e

    async def find_by_name(
        self,
        name: str,
        file_path: str | None = None,
    ) -> list[CodeChunk]:
        def _sync() -> list[CodeChunk]:
            stmt = select(self._chunks_tbl).where(self._chunks_tbl.c.name == name)
            if file_path is not None:
                stmt = stmt.where(self._chunks_tbl.c.file_path == file_path)
            with self._engine.connect() as conn:
                rows = conn.execute(stmt).fetchall()
            return [self._row_to_chunk(r) for r in rows]

        try:
            return await asyncio.to_thread(_sync)
        except Exception as e:
            raise StorageError(f"Failed to find chunks by name '{name}': {e}") from e

    async def search_in_code(
        self,
        symbol: str,
        language: str | None = None,
    ) -> list[CodeChunk]:
        def _sync() -> list[CodeChunk]:
            stmt = select(self._chunks_tbl).where(
                self._chunks_tbl.c.code.like(f"%{symbol}%")
            )
            if language is not None:
                stmt = stmt.where(self._chunks_tbl.c.language == language)
            with self._engine.connect() as conn:
                rows = conn.execute(stmt).fetchall()
            return [self._row_to_chunk(r) for r in rows]

        try:
            return await asyncio.to_thread(_sync)
        except Exception as e:
            raise StorageError(f"Failed to search code for symbol '{symbol}': {e}") from e

    # ── private helper for BM25Retriever ─────────────────────────────────────

    async def _get_language_map(self) -> dict[str, str]:
        def _sync() -> dict[str, str]:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    select(self._chunks_tbl.c.chunk_id, self._chunks_tbl.c.language)
                ).fetchall()
            return {r.chunk_id: r.language for r in rows}

        try:
            return await asyncio.to_thread(_sync)
        except Exception as e:
            raise StorageError(f"Failed to get language map: {e}") from e
