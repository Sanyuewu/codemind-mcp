from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── 路径 ──────────────────────────────────
    repo_path: Path = Field(description="待索引的代码仓库根路径")
    data_dir: Path = Field(
        default=Path("./.codemind"),
        description="索引数据存储目录（vector db + sqlite）"
    )

    # ── Embedding ─────────────────────────────
    embedding_model: str = Field(default="BAAI/bge-m3")
    embedding_dim: int = Field(default=1024)
    embedding_batch_size: int = Field(default=32)
    embedding_device: Literal["cpu", "cuda", "mps"] = Field(default="cpu")

    # ── Reranker ──────────────────────────────
    reranker_model: str = Field(default="BAAI/bge-reranker-v2-m3")
    enable_reranker: bool = Field(default=True)

    # ── 检索参数 ──────────────────────────────
    bm25_top_k: int = Field(default=20)
    dense_top_k: int = Field(default=20)
    rrf_k: int = Field(default=60, description="RRF 公式中的 k 参数")
    rerank_input_top_k: int = Field(default=10, description="送入 reranker 的候选数")

    # ── 索引 ──────────────────────────────────
    supported_languages: list[str] = Field(
        default=["python", "typescript", "java", "go"]
    )
    max_file_size_kb: int = Field(default=500, description="超过则跳过")
    exclude_patterns: list[str] = Field(default=[
        "**/node_modules/**", "**/__pycache__/**", "**/.venv/**",
        "**/dist/**", "**/build/**", "**/*.min.js", "**/*.pyi",
    ])

    # ── 超时 ──────────────────────────────────
    retrieval_timeout_ms: int = Field(default=8000)
    embedding_timeout_ms: int = Field(default=5000)

    # ── 日志 ──────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    log_format: Literal["json", "console"] = Field(default="console")

    model_config = {"env_prefix": "CODEMIND_", "env_file": ".env"}
