from __future__ import annotations

import asyncio
import hashlib
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import structlog

from codemind.config import Settings
from codemind.indexing.chunker import chunk_file
from codemind.indexing.embedder import Embedder, chunk_to_text
from codemind.models import FileMeta, IndexResult
from codemind.storage.metadata_store import MetadataStore
from codemind.storage.vector_store import VectorStore

log = structlog.get_logger()

_LANG_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".java": "java",
    ".go": "go",
}


class Indexer:
    def __init__(
        self,
        config: Settings,
        metadata_store: MetadataStore,
        vector_store: VectorStore,
        embedder: Embedder,
    ) -> None:
        self._config = config
        self._metadata_store = metadata_store
        self._vector_store = vector_store
        self._embedder = embedder

    async def index_repository(
        self,
        repo_path: Path,
        force_rebuild: bool = False,
    ) -> IndexResult:
        start = time.monotonic()
        files = await self._discover_files(repo_path)

        log.info("indexing.started", repo_path=str(repo_path), file_count=len(files))

        indexed = 0
        skipped = 0
        total_chunks = 0
        errors: list[str] = []
        indexed_paths: set[str] = set()

        for file_path in files:
            rel_path = file_path.relative_to(repo_path).as_posix()
            indexed_paths.add(rel_path)
            try:
                result = await self._process_file(file_path, rel_path, force_rebuild)
                if result is None:
                    skipped += 1
                else:
                    indexed += 1
                    total_chunks += result
            except Exception as exc:
                log.warning("indexing.file_failed", file_path=rel_path, error=str(exc))
                errors.append(f"{rel_path}: {exc}")

        await self._cleanup_orphans(indexed_paths)

        duration = time.monotonic() - start
        log.info(
            "indexing.completed",
            indexed=indexed,
            skipped=skipped,
            errors=len(errors),
            duration_s=round(duration, 3),
        )

        return IndexResult(
            total_files=len(files),
            indexed_files=indexed,
            skipped_files=skipped,
            total_chunks=total_chunks,
            duration_seconds=round(duration, 3),
            errors=errors,
        )

    async def update_file(self, file_path: Path) -> int:
        rel_path = file_path.relative_to(self._config.repo_path).as_posix()
        result = await self._process_file(file_path, rel_path, force_rebuild=True)
        return result or 0

    async def _discover_files(self, repo_path: Path) -> list[Path]:
        supported_exts = {
            ext for ext, lang in _LANG_EXTENSIONS.items()
            if lang in self._config.supported_languages
        }

        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                ["git", "ls-files"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
            )
            candidates: list[Path] = [
                repo_path / line
                for line in proc.stdout.splitlines()
                if line.strip()
            ]
        except (subprocess.CalledProcessError, FileNotFoundError):
            candidates = list(repo_path.rglob("*"))

        files: list[Path] = []
        for path in candidates:
            if not path.is_file():
                continue
            if path.suffix not in supported_exts:
                continue
            rel = path.relative_to(repo_path).as_posix()
            if any(PurePosixPath(rel).match(pat) for pat in self._config.exclude_patterns):
                continue
            if path.stat().st_size / 1024 > self._config.max_file_size_kb:
                continue
            files.append(path)

        return files

    async def _process_file(
        self,
        file_path: Path,
        rel_path: str,
        force_rebuild: bool,
    ) -> int | None:
        content = file_path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()

        if not force_rebuild:
            stored = await self._metadata_store.get_file_meta(rel_path)
            if stored and stored.content_hash == content_hash:
                return None

        t0 = time.monotonic()

        await self._metadata_store.delete_by_file(rel_path)
        await self._vector_store.delete_by_file(rel_path)

        chunks = chunk_file(file_path)
        texts = [chunk_to_text(c) for c in chunks]
        embeddings = self._embedder.encode(texts)

        for chunk in chunks:
            await self._metadata_store.save_chunk(chunk)
        await self._vector_store.upsert(chunks, embeddings)

        language = chunks[0].language if chunks else _LANG_EXTENSIONS[file_path.suffix]
        await self._metadata_store.save_file_meta(FileMeta(
            path=rel_path,
            language=language,
            content_hash=content_hash,
            last_indexed_at=datetime.now(timezone.utc),
            chunk_count=len(chunks),
        ))

        log.info(
            "indexing.file_done",
            file_path=rel_path,
            chunk_count=len(chunks),
            duration_ms=round((time.monotonic() - t0) * 1000),
        )
        return len(chunks)

    async def _cleanup_orphans(self, indexed_paths: set[str]) -> None:
        stored = set(await self._metadata_store.get_all_file_paths())
        for path in stored - indexed_paths:
            await self._metadata_store.delete_by_file(path)
            await self._vector_store.delete_by_file(path)
            log.info("indexing.file_removed", file_path=path)
