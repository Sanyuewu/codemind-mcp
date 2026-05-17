# CodeMind MCP — 接口契约文档

> 本文档定义所有**跨模块边界**的契约。Claude Code 实现任何模块时必须严格遵守。
>
> **版本**：v1.1（Final）
>
> **使用方法**：每次让 Claude Code 实现新模块时，把本文档对应章节 + 主 Spec 对应章节一起作为 prompt 上下文。

---

## §1 · 核心数据模型（src/codemind/models.py）

> 所有跨模块数据传递必须使用以下模型，**禁止裸 dict**。

```python
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
```

---

## §2 · 模块间接口

### §2.1 Indexer

```python
# src/codemind/indexing/indexer.py
class Indexer:
    async def index_repository(
        self,
        repo_path: Path,
        force_rebuild: bool = False,
    ) -> IndexResult: ...

    async def update_file(self, file_path: Path) -> int:
        """
        单文件增量更新。
        返回：新建或更新的 chunk 数。
        """
```

### §2.2 Retriever（对外门面，tool 层唯一入口）

```python
# src/codemind/retrieval/retriever.py
class Retriever:
    async def search(self, query: SearchQuery) -> list[RetrievedChunk]: ...

    async def get_chunk_by_id(self, chunk_id: str) -> CodeChunk | None: ...

    async def find_function(
        self,
        name: str,
        file_path: str | None = None,
    ) -> list[CodeChunk]:
        """精确名字匹配，可选文件范围过滤。"""

    async def find_references(
        self,
        symbol: str,
        language: str | None = None,
    ) -> list[Reference]: ...
```

### §2.3 VectorStore

```python
# src/codemind/storage/vector_store.py
class VectorStore:
    async def upsert(
        self,
        chunks: list[CodeChunk],
        embeddings: list[list[float]],
    ) -> None: ...

    async def search(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: dict | None = None,  # e.g. {"language": "python"}
    ) -> list[tuple[str, float]]:     # [(chunk_id, score), ...]
        ...

    async def delete_by_file(self, file_path: str) -> int:
        """返回删除的向量数。"""
```

### §2.4 MetadataStore

```python
# src/codemind/storage/metadata_store.py
class MetadataStore:
    async def save_chunk(self, chunk: CodeChunk) -> None: ...
    async def get_chunk(self, chunk_id: str) -> CodeChunk | None: ...
    async def get_chunks_by_file(self, file_path: str) -> list[CodeChunk]: ...
    async def delete_by_file(self, file_path: str) -> int: ...
    async def get_all_tokens(self) -> dict[str, list[str]]:
        """返回 {chunk_id: token_list}，供 BM25 索引加载使用。"""

    async def get_file_meta(self, path: str) -> FileMeta | None: ...
    async def save_file_meta(self, meta: FileMeta) -> None: ...
    async def list_files(
        self,
        language: str | None = None,
        directory: str | None = None,
        pattern: str | None = None,
    ) -> list[FileMeta]: ...
    async def get_all_file_paths(self) -> list[str]: ...
```

---

## §3 · 错误处理策略

### §3.1 异常体系（src/codemind/exceptions.py）

```python
class CodeMindError(Exception):
    """所有自定义异常的基类。"""

class IndexingError(CodeMindError):
    """索引过程中的错误（单文件失败不应中断整个索引）。"""

class ParserError(IndexingError):
    """Tree-sitter 解析失败。"""

class RetrievalError(CodeMindError):
    """检索失败（应被 tool 层捕获并返回结构化错误给 LLM）。"""

class StorageError(CodeMindError):
    """持久化层错误。"""

class ConfigError(CodeMindError):
    """配置错误（必须在启动时尽早抛出，不允许延迟暴露）。"""
```

### §3.2 处理规则

| 场景 | 处理策略 |
|------|---------|
| 单文件解析失败 | log warning + 记录到 `IndexResult.errors`，**继续索引下一个文件** |
| 整个仓库无法访问 | 抛 `IndexingError`，索引终止 |
| 向量库查询失败 | tool 层捕获，返回结构化错误字符串给 LLM（见 §9） |
| Embedding 模型未加载 | 启动时检查，失败则抛 `ConfigError` 并 exit |
| 配置项缺失或非法 | pydantic-settings 启动校验，失败立刻 exit |
| Tool 参数非法 | MCP 协议层 schema 自动拦截，无需额外处理 |

**绝对禁止**：
- ❌ `try: ... except: pass`（吞错误）
- ❌ `except Exception as e: print(e)`（非结构化）
- ❌ retrieval 路径上不带超时

---

## §4 · 配置项完整清单（src/codemind/config.py）

```python
from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path
from typing import Literal


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
    retrieval_timeout_ms: int = Field(default=2000)
    embedding_timeout_ms: int = Field(default=5000)

    # ── 日志 ──────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    log_format: Literal["json", "console"] = Field(default="console")

    class Config:
        env_prefix = "CODEMIND_"
        env_file = ".env"
```

`.env.example` 必须列出所有配置项及注释：

```dotenv
# Required
CODEMIND_REPO_PATH=/path/to/your/repo

# Optional (defaults shown)
CODEMIND_DATA_DIR=./.codemind
CODEMIND_EMBEDDING_MODEL=BAAI/bge-m3
CODEMIND_EMBEDDING_DIM=1024
CODEMIND_EMBEDDING_BATCH_SIZE=32
CODEMIND_EMBEDDING_DEVICE=cpu
CODEMIND_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
CODEMIND_ENABLE_RERANKER=true
CODEMIND_BM25_TOP_K=20
CODEMIND_DENSE_TOP_K=20
CODEMIND_RRF_K=60
CODEMIND_RERANK_INPUT_TOP_K=10
CODEMIND_MAX_FILE_SIZE_KB=500
CODEMIND_RETRIEVAL_TIMEOUT_MS=2000
CODEMIND_EMBEDDING_TIMEOUT_MS=5000
CODEMIND_LOG_LEVEL=INFO
CODEMIND_LOG_FORMAT=console
```

---

## §5 · 日志规范

### §5.1 日志级别

| 级别 | 用于 |
|------|------|
| DEBUG | 单文件解析、单次 embedding、单个 BM25 候选 |
| INFO | Tool 调用、索引开始/结束、用户可见状态变化 |
| WARNING | 单文件失败、配置 fallback、超时 |
| ERROR | 不可恢复错误、需要用户介入 |

### §5.2 关键事件的结构化字段（字段名不可随意更改）

```python
# Tool 调用
log.info("tool.invoked",  tool_name="semantic_search", query="...", top_k=5)
log.info("tool.completed", tool_name="semantic_search", duration_ms=234, result_count=5)
log.warning("tool.failed", tool_name="semantic_search", error="RetrievalError: ...")

# 检索
log.debug("retrieval.bm25",   query="...", candidates=20, duration_ms=12)
log.debug("retrieval.dense",  query="...", candidates=20, duration_ms=89)
log.debug("retrieval.rerank", input_count=10, output_count=5, duration_ms=145)

# 索引
log.info("indexing.started",    repo_path="...", file_count=234)
log.info("indexing.file_done",  file_path="...", chunk_count=12, duration_ms=56)
log.warning("indexing.file_failed", file_path="...", error="ParserError: ...")
log.info("indexing.completed",  indexed=234, skipped=10, errors=2, duration_s=145.2)
```

---

## §6 · 五个 MCP Tool 的最终描述文本

> ⚠️ **这是简历核心 artifact，Claude Code 不得修改任何措辞。**
> 如需调整，只能由开发者本人在此文档中更新后同步到代码。

### §6.1 semantic_search

```yaml
name: semantic_search
description: |
  Executes a hybrid retrieval (Dense Semantic + BM25 Keyword) across the
  indexed codebase to extract the most contextually relevant code chunks
  (functions, classes, or modules).

  OPTIMAL USE CASES (When to use):
  - Conceptual inquiries (e.g., "How is user authentication implemented?",
    "Where is the retry logic for database connections?").
  - Exploring unknown architectural patterns using natural language descriptions.
  - Discovering code when the exact symbol names are unknown.

  ANTI-PATTERNS (Do NOT use when):
  - You already know the exact function/class name → use get_function_by_name
    instead for full precision.
  - You need to map the directory structure → use list_files instead.
  - You are tracking historical code changes → use get_git_blame instead.

inputSchema:
  query:        string (required) — Natural language description of what to find
  top_k:        integer (default 5, max 20)
  language:     enum [python, typescript, java, go] — Optional filter
  chunk_types:  array of enum [function, class, method] — Optional filter
```

### §6.2 get_function_by_name

```yaml
name: get_function_by_name
description: |
  Retrieves the complete, verbatim source code of a specific function or
  method using its exact symbol name. Returns the full implementation,
  including signatures, docstrings, and internal logic.

  OPTIMAL USE CASES (When to use):
  - Deep diving into a specific component's implementation details.
  - Extracting the complete logic block after identifying a target symbol
    via semantic_search.
  - The user explicitly requests the code for "function X".

  ANTI-PATTERNS (Do NOT use when):
  - The target name is ambiguous, partial, or described in natural language
    → fall back to semantic_search.

inputSchema:
  function_name:  string (required) — Exact function or method name
  file_path:      string — Optional. Restrict search to a specific file
```

### §6.3 find_references

```yaml
name: find_references
description: |
  Scans the repository to locate all references and invocations of a
  specified symbol (function, class, or variable). Returns the exact file
  path, line number, and the enclosing caller context to build a dependency
  graph.

  OPTIMAL USE CASES (When to use):
  - Constructing mental call graphs (e.g., "Who calls this function?",
    "Where is this class instantiated?").
  - Assessing the blast radius and impact of modifying a specific component.
  - Understanding a generic utility function's role by observing its
    downstream usage.

inputSchema:
  symbol:    string (required) — Function, class, or variable name
  language:  enum [python, typescript, java, go] — Optional filter
```

### §6.4 list_files

```yaml
name: list_files
description: |
  Explores the repository's file topology. Returns a mapped list of indexed
  files, detailing their language types and chunk metrics. Supports granular
  filtering by directory boundaries or glob patterns.

  OPTIMAL USE CASES (When to use):
  - Establishing a high-level macro understanding of the project's layout
    and module distribution.
  - Locating specific categories of files before initiating deeper code
    searches (e.g., finding all test_*.py files).

inputSchema:
  directory:  string — Optional. Subdirectory to list (relative to repo root)
  language:   enum [python, typescript, java, go] — Optional filter
  pattern:    string — Optional glob (e.g., "**/test_*.py")
```

### §6.5 get_git_blame

```yaml
name: get_git_blame
description: |
  Retrieves line-level Git provenance and historical context for a specified
  file. Outputs the author, precise timestamp, commit hash, and summary
  commit message for the target line range.

  OPTIMAL USE CASES (When to use):
  - Identifying the original author or domain expert for a specific code block.
  - Understanding the historical "why" behind a specific implementation or
    bug fix.
  - Resolving context gaps by tracing when a specific line of code was
    introduced.

inputSchema:
  file_path:   string (required) — File path relative to repo root
  start_line:  integer — Optional, default 1
  end_line:    integer — Optional, default end of file
```

---

## §7 · 测试约束

### §7.1 哪些模块必须有单测

| 模块 | 优先级 | 关键 case |
|------|--------|----------|
| `chunker.py` | ★★★ 必须 | 每语言一个 fixture 文件；断言 chunk 数、类型、name、parent_name、行号 |
| `parser.py` | ★★ 必须 | 损坏文件、空文件的 fallback |
| `sparse.py` | ★★ 必须 | 关键词精确匹配优先于无关高频词 |
| `hybrid.py` | ★★★ 必须 | 同一 doc 在两个 retriever 都出现时分数高于只出现一次 |
| `retriever.py` | ★★ 必须 | 端到端：插入 3 个已知 chunk → 用相关 query 能召回正确的那个 |
| `tools/*.py` | ★ 推荐 | schema 验证 + 错误返回格式 |

### §7.2 集成测试（test_e2e.py）

必须包含至少一个端到端测试：

1. 索引 `tests/fixtures/mini_repo/`（含 5 个文件，覆盖四种语言）
2. 通过 `retriever.search()` 直接调用（无需启动 MCP server）
3. 断言：
   - 相关 query 能在 top-5 中召回已知函数
   - 不相关 query 不召回错误结果
   - 返回类型严格为 `list[RetrievedChunk]`

### §7.3 严禁

- ❌ `assert True` 或 `assert result is not None`（空断言）
- ❌ mock 一切以至于"测试通过但代码不工作"
- ❌ 测试文件超过 150 行无 fixture 抽取

---

## §8 · 增量索引的精确语义

### §8.1 文件来源

- **优先**：`git ls-files`（只索引 git tracked 文件）
- **fallback**：如果 `repo_path` 不是 git 仓库，用 `Path.rglob()` 遍历

### §8.2 增量检测逻辑

```
对每个候选文件 f:
  current_hash = sha256(f.read_bytes())
  stored = metadata_store.get_file_meta(f.relative_path)

  if stored and stored.content_hash == current_hash:
    skip（计入 skipped_files）
  else:
    await metadata_store.delete_by_file(f.relative_path)
    await vector_store.delete_by_file(f.relative_path)
    await reindex(f)
    await metadata_store.save_file_meta(FileMeta(..., content_hash=current_hash))
```

### §8.3 删除检测

每次全量索引结束时：

```
indexed_paths = set(当前磁盘文件列表)
stored_paths  = set(metadata_store.get_all_file_paths())
orphans       = stored_paths - indexed_paths

for path in orphans:
    await metadata_store.delete_by_file(path)
    await vector_store.delete_by_file(path)
    log.info("indexing.file_removed", file_path=path)
```

---

## §9 · Tool 返回格式

所有 tool 返回 `list[TextContent]`，内容为 Markdown 字符串。

### §9.1 semantic_search / get_function_by_name 成功

```markdown
Found 3 results for "JWT validation logic":

### 1. `verify_token` · `auth/jwt.py` · lines 24–48 · score 0.87

```python
def verify_token(token: str) -> dict | None:
    """Verify a JWT token and return its payload."""
    ...
```

### 2. `JWTBearer.__call__` · `auth/dependencies.py` · lines 12–30 · score 0.72

```python
...
```
```

### §9.2 find_references 成功

```markdown
Found 5 references to `verify_token`:

- `auth/dependencies.py:18` (in `JWTBearer.__call__`)
- `tests/test_auth.py:42` (in `test_verify_token_valid`)
- `api/routes/users.py:67` (in `get_current_user`)
- ...
```

### §9.3 任何 tool 失败

```markdown
**Error [RetrievalError]**: Vector store unreachable.

Suggested fix: ensure the repository has been indexed first:
  codemind index /path/to/repo
```

LLM 看到结构化错误后应能向用户建议正确操作，而非静默失败。

---

## §10 · 给 Claude Code 的宪法（每个新 session 必须粘贴）

```
你在为 CodeMind MCP 项目写代码。以下是不可违反的规则：

1. 所有跨模块数据使用 contracts.md §1 定义的 Pydantic 模型，
   禁止自创字段或省略字段，禁止裸 dict 传递。

2. 所有错误使用 contracts.md §3 的异常体系，
   禁止 try/except: pass，禁止吞错误。

3. 所有配置项必须在 contracts.md §4 的 Settings 类中，
   禁止在代码中散落 hardcode 的配置值。

4. 所有日志事件使用 contracts.md §5 规定的事件名和字段，
   字段名不得随意更改。

5. Tool description 文本严格使用 contracts.md §6 的最终版本，
   不得修改任何措辞，包括大小写和标点。

6. 所有测试必须有真实断言，禁止 assert True 或 assert result is not None。

7. 不引入 contracts.md 与主 Spec 未提到的第三方依赖；
   如需引入，先告诉我理由，等我明确同意后再添加。

如果你认为某条规则应该破例，先告诉我理由，等我明确同意。
未经许可不得自行决定偏离。
```

---

**End of Contracts v1.1 (Final)**
