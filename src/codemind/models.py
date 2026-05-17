from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════
# 索引层
# ══════════════════════════════════════════════

class CodeChunk(BaseModel):
    """
    索引时由 chunker 产出，是系统中所有代码片段的标准载体。
    任何模块不得在此模型以外自定义代码片段结构。
    """
    chunk_id: str = Field(
        description="稳定哈希: sha256(file_path + ':' + str(start_line))[:16]"
    )
    file_path: str = Field(description="相对仓库根的 POSIX 路径，不含前导 '/'")
    language: Literal["python", "typescript", "java", "go"]
    chunk_type: Literal["function", "class", "method", "module"]
    name: str = Field(description="函数名/类名；module chunk 为 '<module>'")
    signature: str | None = Field(default=None, description="函数签名，无则 None")
    docstring: str | None = Field(default=None)
    code: str = Field(description="完整代码文本，含函数上方紧贴的注释")
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    parent_name: str | None = Field(
        default=None,
        description="所属类名（当 chunk_type 为 'method' 时必须填写）"
    )


class IndexResult(BaseModel):
    """indexer.index_repository() 的返回值。"""
    total_files: int
    indexed_files: int
    skipped_files: int
    total_chunks: int
    duration_seconds: float
    errors: list[str] = Field(default_factory=list)


# ══════════════════════════════════════════════
# 检索层
# ══════════════════════════════════════════════

class SearchQuery(BaseModel):
    """传入 retriever.search() 的查询参数。"""
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)
    language: Literal["python", "typescript", "java", "go"] | None = None
    chunk_types: list[Literal["function", "class", "method", "module"]] | None = None


class RetrievedChunk(BaseModel):
    """retriever 的统一输出。tool 层只消费这个，不直接读 storage。"""
    chunk: CodeChunk
    score: float = Field(description="融合后归一化分数，范围 [0, 1]")
    retrieval_method: Literal["bm25", "dense", "hybrid", "rerank"]
    debug_info: dict = Field(
        default_factory=dict,
        description="调试用，可含 bm25_score / dense_score / rerank_score"
    )


class Reference(BaseModel):
    """find_references 工具的单条结果。"""
    file_path: str
    line_number: int
    line_content: str
    enclosing_function: str | None = Field(
        default=None,
        description="包裹该引用的函数名；不在任何函数内则为 None"
    )


# ══════════════════════════════════════════════
# 元数据层
# ══════════════════════════════════════════════

class FileMeta(BaseModel):
    """文件级元数据，存于 SQLite files 表。"""
    path: str
    language: str
    content_hash: str = Field(description="sha256(file_content)，用于增量检测")
    last_indexed_at: datetime
    chunk_count: int


# ══════════════════════════════════════════════
# Git 层
# ══════════════════════════════════════════════

class BlameLine(BaseModel):
    """git_blame 工具的单行结果。"""
    line_number: int
    content: str
    author: str
    commit_hash: str
    commit_date: datetime
    commit_message: str = Field(description="只保留 commit message 的第一行")
