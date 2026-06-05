"""Fixed-window chunker for ablation experiments (Experiment 1: AST vs fixed window)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from codemind.indexing.parser import get_language
from codemind.models import CodeChunk


def _chunk_id(file_path: str, start_line: int) -> str:
    return hashlib.sha256(f"{file_path}:{start_line}".encode()).hexdigest()[:16]


def fixed_window_chunk_file(
    path: Path,
    rel_path: str,
    window: int = 50,
    stride: int = 40,
) -> list[CodeChunk]:
    """Split a source file into overlapping fixed-size line windows.

    Each window produces one CodeChunk with chunk_type="window".
    chunk_id uses the same formula as the AST chunker so the eval
    harness can use existing infrastructure.
    """
    language = get_language(path)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return []

    chunks: list[CodeChunk] = []
    start_idx = 0
    while start_idx < len(lines):
        end_idx = min(start_idx + window, len(lines))
        start_line = start_idx + 1  # 1-indexed
        end_line = end_idx
        code = "\n".join(lines[start_idx:end_idx])
        tokens = " ".join(re.findall(r"[a-zA-Z0-9_]+", code.lower()))
        chunks.append(
            CodeChunk(
                chunk_id=_chunk_id(rel_path, start_line),
                file_path=rel_path,
                language=language,
                chunk_type="module",
                name=f"window_{start_line}",
                signature=None,
                docstring=None,
                code=code,
                start_line=start_line,
                end_line=end_line,
                parent_name=None,
            )
        )
        start_idx += stride
        if end_idx >= len(lines):
            break
    return chunks
