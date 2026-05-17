# CodeMind MCP — 项目开发规格书

> 一份"既能交给 Claude Code 直接施工、又能让你自己看懂全貌"的总分式开发文档。
>
> **版本**：v1.1（Final）  **预计周期**：14 天（含评估与开源）  **角色**：个人独立开发

---

## 写在前面 — 怎么用这份文档

这份文档分为六个部分，结构是先总后分：

1. **Part 1（总）**：项目是什么、为什么做、整体长什么样。读完你应该能用三句话向别人介绍这个项目。
2. **Part 2（分·设计）**：每个模块的详细设计与决策依据。读完你应该理解每个技术选型的"为什么"。
3. **Part 3（分·执行）**：14 天逐日任务清单。读完你应该知道明天从哪一行代码开始。
4. **Part 4（分·协作）**：怎么把这份文档拆给 Claude Code，每个阶段给什么 prompt。
5. **Part 5（分·产出）**：评估方案、简历文案、面试问答。
6. **Part 6（分·风险）**：可能踩的坑和备选方案。

**对你（人）的使用建议**：先完整读 Part 1 和 Part 2.1—2.3，建立心理模型；之后开发时把 Part 3 当作日历，Part 4 当作 prompt 仓库。

**对 Claude Code 的使用建议**：每个 Phase 开始时把对应的 Part 2 模块设计 + Part 3 的当日任务一起喂给它，**不要把整份文档一次性丢给它**——会失焦。

---

# Part 1 · 总览

## 1.1 项目愿景

**一句话**：CodeMind 是一个让 Claude / Cursor 真正"读懂"你私有代码仓库的 MCP Server。

**问题**：通用 LLM 对你的私有代码库一无所知。即使你把代码贴给它，它也只能看到当前窗口里的内容——看不到这个函数被谁调用、这个类继承自哪里、相似逻辑在仓库另一个角落是怎么写的。

**解法**：通过 Model Context Protocol（MCP）协议，把代码库的检索、定位、引用查找等能力封装为一组工具，让 LLM 在对话过程中按需调用。LLM 保留了通用推理能力，同时获得了对特定 codebase 的深度访问能力。

**为什么有价值**：
- 对你个人：每天用 Cursor / Claude Desktop 写代码时就会用到，吃自己的狗粮
- 对面试：直接命中"AI 编程工具 + Agent + 工程落地"三大热点
- 对长期：MCP 生态刚起步，做一个扎实的开源 server 有真实社会价值

## 1.2 用户故事

```
作为一名开发者，我希望在 Claude Desktop 中提问：
  "我们项目里 JWT 校验的逻辑在哪里？最近一次改动是谁做的？"

Claude 应该能：
  1. 调用 semantic_search 找到相关代码片段
  2. 调用 get_function_by_name 拿到完整的函数定义
  3. 调用 get_git_blame 拿到最后修改人和 commit
  4. 综合后给出一个准确、可追溯、不幻觉的回答
```

## 1.3 核心功能清单（MVP）

| 能力 | MCP Tool 名 | 输入 | 输出 |
|------|------------|------|------|
| 混合语义检索 | `semantic_search` | query, top_k, language? | 代码片段列表（含文件路径、行号、得分） |
| 函数查询 | `get_function_by_name` | function_name, file? | 函数完整源码 + 签名 + docstring |
| 引用查找 | `find_references` | symbol_name | 该符号在仓库中所有引用位置 |
| 文件浏览 | `list_files` | dir?, language?, pattern? | 文件列表 + 元信息 |
| Git 追溯 | `get_git_blame` | file, line_range? | 每行的 author / commit / date |

**非目标**（V1 明确不做，避免范围膨胀）：
- ❌ 代码生成 / 修改建议（这是 LLM 客户端的责任）
- ❌ 跨仓库联邦检索
- ❌ 实时 IDE 集成（用 Claude Desktop 接入即可演示）
- ❌ 鉴权 / 多租户（本地工具，单用户）

## 1.4 系统架构总图

```
┌─────────────────────────────────────────────────────────────────┐
│                  Claude Desktop / Cursor (Client)                │
│                  ─ via MCP over stdio ─                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ JSON-RPC
┌──────────────────────────▼──────────────────────────────────────┐
│                       CodeMind MCP Server                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Tool Layer:  search │ get_func │ refs │ files │ blame   │   │
│  └──────────────────────┬───────────────────────────────────┘   │
│  ┌──────────────────────▼───────────────────────────────────┐   │
│  │              Retrieval Engine                             │   │
│  │   ┌──────────┐  ┌──────────┐  ┌────────────────────┐    │   │
│  │   │  Sparse  │  │  Dense   │  │      Reranker      │    │   │
│  │   │  (BM25)  │  │ (BGE-M3) │  │ (BGE-reranker-v2)  │    │   │
│  │   └────┬─────┘  └────┬─────┘  └─────────┬──────────┘    │   │
│  │        └─────RRF─────┘                  │               │   │
│  └──────────────────────┬──────────────────┴───────────────┘   │
│  ┌──────────────────────▼───────────────────────────────────┐   │
│  │  Index Layer:  Qdrant (vectors) │ SQLite (metadata/BM25) │   │
│  └──────────────────────▲───────────────────────────────────┘   │
│  ┌──────────────────────┴───────────────────────────────────┐   │
│  │  Indexing Pipeline:                                       │   │
│  │   File Watcher → Tree-sitter Parser → AST Chunker         │   │
│  │   → Embedder → Vector Store + BM25 Index                  │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
                           │
                  ┌────────▼────────┐
                  │   Local File    │
                  │   System (Repo) │
                  └─────────────────┘
```

## 1.5 技术栈总览

| 层 | 选型 | 版本 | 理由 |
|----|------|------|------|
| 语言 | Python | 3.11+ | MCP 官方 SDK 主力支持；生态最全 |
| 包管理 | uv | latest | 比 poetry 快 10×，新项目首选 |
| MCP SDK | `mcp`（官方） | latest | Anthropic 官方维护 |
| AST 解析 | tree-sitter + tree-sitter-languages | latest | 业界标准，多语言一份 API |
| Embedding | BGE-M3 | latest | 中英双语 + 代码效果好，本地可跑 |
| 向量库 | Qdrant（embedded） | latest | 本地模式零运维，性能足够 |
| 稀疏检索 | rank-bm25 | latest | 简单可靠 |
| 重排 | BGE-reranker-v2-m3 | latest | 轻量，cross-encoder 质量足 |
| 元数据 | SQLite + SQLAlchemy | 3.x / 2.x | 标准库 + 优秀 ORM |
| Git | GitPython | latest | git blame 等操作的标准库 |
| 配置 | pydantic-settings | v2 | 类型安全的配置管理 |
| 日志 | structlog | latest | 结构化日志，调 LLM 时排错方便 |
| 测试 | pytest + pytest-asyncio | latest | — |
| Lint | ruff + mypy | latest | 现代 Python 工具链 |
| 部署 | Docker + docker-compose | — | 一键启动 |

## 1.6 时间线总览

```
Week 1: 底层引擎 ─────────────────────────────────────
  D1   ─ 环境 + MCP Hello World
  D2   ─ Tree-sitter 集成 + 解析骨架
  D3-4 ─ AST 切分策略 + 单元测试
  D5   ─ Embedder + Qdrant 集成
  D6   ─ BM25 索引 + 元数据存储
  D7   ─ 索引 pipeline 串联 + 增量更新

Week 2: Agent 能力 + 评估 + 收尾 ─────────────────────
  D8   ─ 5 个 MCP Tool 实装
  D9   ─ Hybrid 检索 + Rerank
  D10  ─ Claude Desktop 接入 + 端到端联调
  D11  ─ Eval set 构建（50 条）+ baseline 跑通
  D12  ─ 三组对照实验
  D13  ─ README / Demo 视频 / Docker
  D14  ─ 开源发布 + 技术博客
```

---

# Part 2 · 详细设计

## 2.1 需求规格

### 2.1.1 功能性需求

**F1 - 多语言代码索引**
- 支持 Python / TypeScript / Java / Go（V1 范围）
- 通过 tree-sitter 做 AST 解析
- 切分粒度：函数级、类级（Python/Java）、interface/struct 级（TS/Go）

**F2 - 增量索引**
- 基于文件内容哈希检测变更（覆盖 untracked 修改）
- 单文件变更后索引更新延迟 < 2s
- 首次全量索引一个 10 万行仓库 < 5 min

**F3 - 五类 MCP Tool**
- 严格遵守 MCP 协议
- 工具描述 / 参数 schema 必须人类可读
- 错误返回结构化信息，让 LLM 能 retry

**F4 - 混合检索**
- BM25 + Dense 双路召回
- RRF 融合
- Cross-encoder 重排

**F5 - 评估能力**
- 50 条 eval set
- 自动跑出 Recall@1/3/5 + MRR
- 支持对比多个配置

### 2.1.2 非功能性需求

| 维度 | 目标 |
|------|------|
| 性能 | 单次 semantic_search < 500ms（10 万行库） |
| 资源 | 无 GPU 可跑（CPU + ONNX Runtime） |
| 隐私 | 代码不出本机（embedding 模型本地化） |
| 可移植 | Docker 一键起，跨 macOS / Linux |
| 可观测 | 每次 tool 调用记录耗时与命中情况 |

## 2.2 总体架构与模块划分

代码按"**关注点分离**"分为四个独立子包，相互之间通过明确的接口契约通信：

```
src/codemind/
├── indexing/       # 输入 → 索引：解析、切分、嵌入、写入
├── storage/        # 持久化层：向量库 + 元数据库
├── retrieval/      # 索引 → 候选：稀疏、稠密、融合、重排
├── tools/          # MCP 工具实现（薄薄一层，调用 retrieval）
└── server.py       # MCP server 入口
```

**设计原则**：
- `tools/` 不允许直接访问 `storage/`，必须通过 `retrieval/` 的接口
- `retrieval/` 不关心索引怎么建的，只消费 `storage/` 的查询接口
- `indexing/` 不知道下游怎么用，只负责"把代码变成向量+元数据"

> 📚 **学习要点**：这种分层是 DDD（Domain-Driven Design）思想的简化版。任何一层换实现（比如 Qdrant 换 Milvus、BGE 换 OpenAI Embedding）都不需要改其他层。

## 2.3 模块详解

### 2.3.1 Indexing 模块

**职责**：把一个本地代码仓库变成可被检索的索引。

```
indexing/
├── parser.py    # Tree-sitter 解析封装
├── chunker.py   # AST 感知切分
├── embedder.py  # Embedding 生成
└── indexer.py   # 编排（orchestrator）
```

**切分策略（核心算法）**：

```
对每个支持的文件：
  1. 用 tree-sitter 解析得到 AST
  2. 提取所有 function_definition / class_definition / method_definition 节点
  3. 对每个节点生成一个 CodeChunk
  4. 特殊处理：
     - 注释紧贴函数上方：归到函数 chunk
     - import / module-level code：合并为一个 "module" chunk
     - 函数过长（>500 行）：标记 TODO，V1 不拆
```

**为什么这样切**：
- 函数是代码的最小语义单元，按行/字符切会把函数切碎
- 函数名 + 签名 + docstring 可以作为 embedding 的"语义增强"输入
- chunk 边界对齐 AST 让 `get_function_by_name` 可以直接复用 chunk

> 📚 **学习要点**：检索效果好坏，70% 取决于切分策略。代码场景 AST 切分是公认的 SOTA。

### 2.3.2 Storage 模块

**职责**：持久化向量 + 元数据，提供原子的读写接口。

```
storage/
├── vector_store.py    # Qdrant 封装
└── metadata_store.py  # SQLite + SQLAlchemy
```

**存储分工**：
- Qdrant：存 embedding 向量 + 必要的 payload 过滤字段
- SQLite：存完整的 CodeChunk（含源代码文本）+ BM25 tokens + 文件元信息

> 📚 **学习要点**：向量库只存向量 + 过滤字段；完整代码内容存关系库。这样 vector store 保持小巧，BM25 也能高效跑在 SQLite 上。

### 2.3.3 Retrieval 模块

**职责**：给一个 query，返回最相关的 chunks。

```
retrieval/
├── sparse.py    # BM25
├── dense.py     # Vector search
├── hybrid.py    # RRF 融合
├── rerank.py    # Cross-encoder
└── retriever.py # 对外门面
```

**Hybrid 流程**：

```
query
  ├──> BM25 检索 top 20  ──┐
  │                        ├──> RRF 融合 ── top 10 ──> Reranker ──> top K
  └──> Dense 检索 top 20  ──┘
```

**RRF 融合公式**：

```
score(d) = Σ over retrievers r:  1 / (k + rank_r(d))
# k=60；排名越靠前贡献越大；对不同检索器的分数尺度天然鲁棒
```

> 📚 **学习要点**：RRF 是 hybrid 检索的事实标准，无需调参权重。Elasticsearch、Vespa、Weaviate 都内置了它。

### 2.3.4 Tools 模块（MCP 工具实现）

**职责**：把 retrieval 能力封装成 LLM 友好的 tool。每个 tool 是一个独立文件：

```python
# tools/search.py 骨架
TOOL_DEFINITION = Tool(
    name="semantic_search",
    description="...",    # 严格使用 contracts.md §6 文本，不修改
    inputSchema={...},
)

async def handle_semantic_search(
    arguments: dict,
    retriever: Retriever
) -> list[TextContent]:
    results = await retriever.search(SearchQuery(**arguments))
    return [TextContent(type="text", text=format_results(results))]
```

**Tool description 的具体文本统一在 `contracts.md §6` 管理**。Claude Code 不得自行修改。

### 2.3.5 Server 模块

```python
# server.py
async def main():
    server = Server("codemind")
    retriever = build_retriever()

    @server.list_tools()
    async def list_tools():
        return [TOOL_SEARCH, TOOL_GET_FUNC, TOOL_REFS, TOOL_LIST_FILES, TOOL_BLAME]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        return await TOOL_HANDLERS[name](arguments, retriever)

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
```

## 2.4 数据流（端到端）

**索引阶段**：

```
git ls-files / Path.rglob → 过滤支持的语言 + exclude_patterns
  → 对每个文件，检查 content_hash 是否变更
      → 变更则：删旧 chunks → parse → AST chunk
                → embed(signature + docstring + code)
                → qdrant.upsert + metadata_store.write
  → 更新 file_meta（hash、时间戳）
```

**查询阶段**：

```
LLM 调 semantic_search(query="JWT 校验逻辑", top_k=5)
  → MCP server 接收 JSON-RPC
  → handle_semantic_search:
      BM25 top 20 + Dense top 20 → RRF top 10 → Reranker top 5
      → 格式化为 Markdown 返回
  → LLM 拿到结果，决定下一步
```

## 2.5 项目目录结构

```
codemind-mcp/
├── pyproject.toml
├── uv.lock
├── README.md
├── LICENSE                       # MIT
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
│
├── src/
│   └── codemind/
│       ├── __init__.py
│       ├── server.py
│       ├── config.py
│       ├── models.py             # 所有跨模块 Pydantic 模型（见 contracts §1）
│       ├── exceptions.py         # 异常体系（见 contracts §3）
│       ├── cli.py                # codemind index / codemind serve
│       │
│       ├── indexing/
│       │   ├── __init__.py
│       │   ├── parser.py
│       │   ├── chunker.py
│       │   ├── embedder.py
│       │   └── indexer.py
│       │
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── vector_store.py
│       │   └── metadata_store.py
│       │
│       ├── retrieval/
│       │   ├── __init__.py
│       │   ├── sparse.py
│       │   ├── dense.py
│       │   ├── hybrid.py
│       │   ├── rerank.py
│       │   └── retriever.py
│       │
│       └── tools/
│           ├── __init__.py
│           ├── search.py
│           ├── get_function.py
│           ├── find_references.py
│           ├── list_files.py
│           └── git_blame.py
│
├── tests/
│   ├── __init__.py
│   ├── fixtures/
│   │   └── mini_repo/            # 5 个文件，四种语言，供所有测试使用
│   ├── test_chunker.py
│   ├── test_retriever.py
│   ├── test_tools.py
│   └── test_e2e.py
│
├── evals/
│   ├── eval_set.jsonl
│   ├── run_eval.py
│   ├── configs/
│   │   ├── baseline_fixedwindow.yaml
│   │   ├── baseline_bm25.yaml
│   │   ├── baseline_dense.yaml
│   │   ├── hybrid.yaml
│   │   └── hybrid_rerank.yaml
│   └── results/
│
└── docs/
    ├── contracts.md              # 接口契约（见同名文件）
    ├── decisions.md              # 开发期偏离记录
    └── eval-report.md            # 评估实验报告
```

## 2.6 工程规范

- 全文 type hint，`mypy --strict` 通过
- 公开 API 写 docstring（Google style）
- 异步 I/O 优先（tools / indexing / retrieval 全部 `async def`）
- 数据结构用 Pydantic v2，禁止裸 dict 跨模块传递
- Commit：Conventional Commits 规范
- Lint：`ruff check && ruff format && mypy` 每次 commit 前自动跑

---

# Part 3 · 执行计划

## 3.1 Day-by-day 任务清单

### Phase 1 — 引擎打底（Week 1）

**D1（4h）— 环境与 Hello World**
- [ ] `uv init codemind-mcp && uv add mcp pydantic-settings structlog`
- [ ] 写最简 MCP server：注册一个 `echo` tool，跑通
- [ ] Claude Desktop 配置 `claude_desktop_config.json` 接入本地 server
- [ ] 在 Claude Desktop 里验证 echo 工具可调
- [ ] 提交：`feat: scaffold MCP server with echo tool`

**D2（6h）— Tree-sitter 集成**
- [ ] `uv add tree-sitter tree-sitter-languages`
- [ ] 实现 `parser.py`：给定文件路径返回 AST，先跑通 Python
- [ ] 单元测试：解析一个真实 .py 文件，断言能找到所有函数节点
- [ ] 提交：`feat(indexing): tree-sitter parser for python`

**D3-D4（10h）— AST 切分器**
- [ ] 实现 `chunker.py`：从 AST 抽函数/类/方法节点
- [ ] CodeChunk Pydantic 模型（字段对齐 contracts.md §1）
- [ ] 扩展到 TS / Java / Go
- [ ] 单测：每种语言一个 fixture，断言 chunk 数量、类型、name、parent_name、行号
- [ ] 边界 case：嵌套函数、装饰器、类内方法
- [ ] 提交：`feat(indexing): AST-aware chunker for 4 languages`

**D5（6h）— Embedder + 向量库**
- [ ] `uv add sentence-transformers qdrant-client`
- [ ] 实现 `embedder.py`：BGE-M3 加载 + encode（CPU + ONNX）
- [ ] 实现 `vector_store.py`：Qdrant 本地模式，upsert / search 接口
- [ ] 集成测试：3 个 chunk 嵌入后能检索回来
- [ ] 提交：`feat(storage): qdrant vector store + bge-m3 embedder`

**D6（5h）— BM25 + 元数据存储**
- [ ] `uv add rank-bm25 sqlalchemy`
- [ ] 实现 `metadata_store.py`：SQLAlchemy 模型 + CRUD
- [ ] 实现 `sparse.py`：BM25 索引（启动时从 SQLite 加载，常驻内存）
- [ ] 单测：BM25 能正确召回关键词优先于无关高频词
- [ ] 提交：`feat(storage): bm25 sparse retrieval + metadata store`

**D7（5h）— 索引 Pipeline + 增量更新**
- [ ] 实现 `indexer.py`：编排 parse → chunk → embed → store
- [ ] CLI：`codemind index <repo_path>` 全量索引
- [ ] 增量：content_hash 检测变更，只重建涉及文件；磁盘消失的文件删除其 chunks
- [ ] 对自己的某个项目跑一次完整索引，记录耗时
- [ ] 提交：`feat(indexing): end-to-end pipeline with incremental update`

### Phase 2 — Agent 化与评估（Week 2）

**D8（6h）— 5 个 MCP Tool 实装**
- [ ] `semantic_search`（最重要，先做）
- [ ] `get_function_by_name`（查 metadata_store）
- [ ] `find_references`（tree-sitter 找 identifier 所有出现）
- [ ] `list_files`（遍历 metadata_store）
- [ ] `get_git_blame`（GitPython 实现）
- [ ] Tool description **严格使用 contracts.md §6 文本，不修改**
- [ ] 提交：`feat(tools): implement 5 MCP tools`

**D9（5h）— Hybrid 检索 + Rerank**
- [ ] `uv add FlagEmbedding`（含 BGE-reranker）
- [ ] 实现 `hybrid.py`：RRF 融合
- [ ] 实现 `rerank.py`：BGE-reranker-v2-m3
- [ ] 端到端：semantic_search 走完整 pipeline
- [ ] 提交：`feat(retrieval): hybrid search + cross-encoder rerank`

**D10（5h）— Claude Desktop 端到端联调**
- [ ] 在 Claude Desktop 提 10 个真实问题，肉眼评质量
- [ ] 记录 bad cases，找根因
- [ ] 修 2-3 个最影响体验的 bug
- [ ] 录 2 分钟 demo 视频
- [ ] 提交：`fix: address top issues from manual eval`

**D11（5h）— Eval Set 构建**
- [ ] 选 2-3 个开源仓库（建议含 FastAPI）
- [ ] 50 条问答，intent_type 覆盖 locate / understand / compare
- [ ] 对每条标注 gold passages（chunk_id 列表）
- [ ] 提交：`feat(evals): 50-question eval set`

**D12（6h）— 三组对照实验**
- [ ] 实验 1：AST 切分 vs 固定窗口 → Recall@5
- [ ] 实验 2：BM25 / Dense / Hybrid / Hybrid+Rerank → Recall@1,3,5 + MRR
- [ ] 实验 3：万能 tool vs 原子 tool → tool call 成功率 + 幻觉率
- [ ] 写进 `docs/eval-report.md`，生成图表
- [ ] 提交：`docs: evaluation report with three ablation studies`

**D13（5h）— 文档与部署**
- [ ] README：项目介绍 + 快速开始 + demo GIF + 评估结果摘要
- [ ] Dockerfile + docker-compose.yml + `.env.example`
- [ ] 提交：`docs: comprehensive README + docker deployment`

**D14（3h）— 开源 + 博客**
- [ ] 仓库设为 public，topics: `mcp`, `claude`, `code-search`, `rag`
- [ ] 技术博客掘金 + dev.to 双发
- [ ] 向 awesome-mcp-servers 提 PR

## 3.2 验收清单

- [ ] Claude Desktop 中能成功调用全部 5 个 tool
- [ ] 10 万行规模仓库首次索引 < 5 min
- [ ] 单次 semantic_search 端到端 < 500ms
- [ ] eval-report.md 包含三组实验对比表格
- [ ] README 有 demo GIF，第一屏让人看懂"这是干什么的"
- [ ] `uv run pytest` 全绿，覆盖率 > 60%
- [ ] `uv run mypy src` 无报错
- [ ] Docker 从零到可用 < 5 min

---

# Part 4 · 与 Claude Code 协作

## 4.1 推荐协作方式

每天开新 session，保持上下文干净。三层喂内容：

1. **宪法**（contracts.md §10）——每次第一条消息，不变
2. **当日任务**（Part 3 对应 Day）
3. **设计细节**（Part 2 + contracts.md 对应章节）

让它先给计划再写代码，你确认后再执行。

## 4.2 关键 Prompt 模板

### 模板 A — 启动新阶段

```
我在做 CodeMind MCP 项目，今天是 Day X。

【宪法】
（粘贴 contracts.md §10 全文）

【今天的任务】
（粘贴 Part 3 当日 checklist）

【相关设计】
（粘贴 Part 2 对应模块 + contracts.md 对应章节）

请先给我实施计划（不写代码），我确认后你再分步实现。
每完成一个文件，跑对应的测试，确认绿了再继续。
```

### 模板 B — 设计决策协商

```
我在做 [模块名]，设计文档建议 [方案 A]，但我有个疑问：[问题]。

请：
1. 解释为什么文档推荐 A
2. 列举两个替代方案，各自 trade-off
3. 给出建议（带理由）

不要写代码。
```

### 模板 C — 调 Bug

```
运行 [命令] 时报错：（完整 traceback）

相关代码：（最小复现片段）

请：
1. 假设三个可能根因
2. 给我具体检查命令（我跑完给你看输出）
3. 拿到输出后再下结论，不要立刻改代码
```

### 模板 D — Code Review

```
我刚完成 [模块]，请扮演 senior engineer 做 review：

1. 设计层面：单一职责、过度抽象、紧耦合
2. 实现层面：边界条件、错误处理、性能陷阱
3. 可测试性：哪些地方难测？怎么改造？
4. 命名与可读性

只列问题，不要直接改。
```

## 4.3 防 Claude Code 翻车的检查点

每个 Phase 完成后**人工**确认：

- [ ] 它有没有引入 contracts/spec 未指定的依赖？（检查 `pyproject.toml`）
- [ ] 它有没有简化 RRF 或 rerank 的核心逻辑？
- [ ] 它写的测试是否有真实断言？（不是 `assert True`）
- [ ] Tool description 文本是否与 contracts §6 完全一致？
- [ ] 有没有 secret / 路径硬编码？

---

# Part 5 · 评估与产出物

## 5.1 评估方案

### Eval Set 格式

```json
{
  "id": "q001",
  "question": "JWT 校验的逻辑在哪里实现？",
  "target_repo": "fastapi",
  "intent_type": "locate",
  "language": "python",
  "gold_passages": [
    {
      "file_path": "fastapi/security/oauth2.py",
      "function_name": "OAuth2.__call__",
      "start_line": 120,
      "end_line": 145
    }
  ]
}
```

### 三组对照实验

**实验 1 — 切分策略**：固定 500 token 窗口 vs AST 函数级，指标 Recall@1/3/5 + MRR

**实验 2 — 检索策略阶梯**：BM25 only → Dense only → Hybrid(RRF) → Hybrid+Rerank

**实验 3 — Tool 粒度**：`query_codebase(query, mode)` 万能工具 vs 5 个原子工具，指标：tool call 成功率、每问题平均调用次数、幻觉率（LLM-as-judge）

### LLM-as-judge Prompt

```
You are evaluating whether an AI assistant's answer about a codebase
contains hallucinations.

Question: {question}
Reference code: {gold_passages_code}
AI answer: {answer}

Rate on 1-5 scale:
1. Factual accuracy (matches reference code?)
2. Completeness (covers what was asked?)
3. Hallucination level (1=severe, 5=none)

Return JSON: {"accuracy": int, "completeness": int, "hallucination": int, "reason": str}
```

## 5.2 简历输出物（D14 后填入真实数据）

```
CodeMind: 基于 MCP 协议的代码仓库智能问答工具 | 个人开源项目
GitHub: github.com/<yourname>/codemind-mcp (★ XX) | Blog: <url>

技术栈：Python / Model Context Protocol / Tree-sitter / BGE-M3 /
       BGE-reranker / Qdrant / SQLAlchemy / Docker

• 项目背景：通用 LLM 对私有代码库理解力弱，基于 Anthropic MCP 规范
  开发本地 Code RAG server，接入 Claude Desktop / Cursor 后让 LLM
  具备对特定 codebase 的深度问答、定位、引用追踪能力，全本地化部署
  保护代码隐私。

• AST 感知的语义切分：基于 tree-sitter 解析 Python/Java/TS/Go 四语言
  AST，按函数/类粒度切分并附加签名、docstring 作为 metadata。在自建
  50 条 eval set 上，Recall@5 相比固定窗口切分从 XX% 提升至 XX%。

• 稀疏 + 稠密 + 重排的混合检索：BM25 捕捉精确符号匹配，BGE-M3 捕捉
  语义相似性，RRF 融合后 BGE-reranker-v2-m3 重排。相比纯稠密检索，
  Recall@5 从 XX% 提升至 XX%，MRR 从 X.XX 提升至 X.XX。

• MCP Tool 粒度优化：将代码库能力拆分为 5 个原子工具并通过 JSON
  Schema 精确描述。对照实验表明，原子工具相比单一万能工具，Agent
  调用准确率高 XX%，最终回答幻觉率从 XX% 降至 XX%。

• 增量索引与工程化：基于 content hash 监听文件变更，索引更新延迟 < 2s；
  BGE-M3 ONNX 本地加速，无 GPU 可跑；Docker 一键部署。开发过程 80%
  代码由 Claude Code 协同完成，体现 AI 编程工具深度使用经验。
  开源后 GitHub XX star。
```

## 5.3 面试演练材料

建立 `docs/interview-defense.md`，提前准备这 7 题的 200 字回答：

1. 为什么选 MCP 而不是 LangChain Tool / 自定义 function calling？
2. AST 切分相比固定窗口切分好在哪？反例是什么？
3. Hybrid 检索的本质，BM25 与 Dense 各自适合什么场景？
4. RRF 的数学直觉为什么 work？
5. Tool 粒度怎么决定的？太粗 / 太细各自的问题？
6. Eval set 怎么造的，怎么避免 overfit？
7. 如果代码库扩展到百万行，架构怎么调整？

---

# Part 6 · 风险与备选

## 6.1 已识别风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| BGE-M3 加载慢 / 内存大 | 中 | 中 | ONNX 版本；首次加载缓存磁盘 |
| Tree-sitter 某语言解析报错 | 中 | 低 | 报错时降级为整文件作为一个 module chunk |
| Qdrant 本地模式数据不持久 | 低 | 高 | 显式指定 `path=` 磁盘路径，非 in-memory 模式 |
| MCP SDK 版本接口变动 | 中 | 中 | 锁定版本；遇变更查 changelog |
| 评估集太小导致结果不稳定 | 高 | 中 | 多 seed 跑 3 次取平均；README 写明局限性 |
| 时间超期 | 高 | 中 | 见砍范围预案 |

## 6.2 模块级备选

- **Embedding**：BGE-M3 → `jinaai/jina-embeddings-v2-base-code`（更小、代码友好）
- **向量库**：Qdrant → ChromaDB（更轻）或 LanceDB（文件格式）
- **Reranker**：BGE-reranker-v2-m3 → Cohere Rerank API（不本地化）

## 6.3 砍范围预案

D10 进度落后超过两天时，按顺序砍：

1. 砍 `find_references`（实现复杂，业务价值次于 search）
2. 砍 Java / Go 语言支持（保 Python + TS）
3. 砍实验 1（切分对比），只做实验 2 + 3

**绝对不砍**：semantic_search 完整 pipeline + eval set + README + demo

---

# 附录

## A. 关键资源

- MCP 协议规范：https://modelcontextprotocol.io/
- MCP Python SDK：https://github.com/modelcontextprotocol/python-sdk
- Awesome MCP servers：https://github.com/modelcontextprotocol/servers
- Tree-sitter：https://tree-sitter.github.io/
- BGE-M3：https://huggingface.co/BAAI/bge-m3
- BGE-reranker-v2-m3：https://huggingface.co/BAAI/bge-reranker-v2-m3
- Qdrant Python client：https://github.com/qdrant/qdrant-client

## B. 项目演进路线（V2+）

- V1.1：Call graph 工具（函数调用树）
- V1.2：Test coverage 集成（哪些函数没有测试）
- V2.0：多仓库联邦检索
- V2.1：Watch mode（文件保存后实时增量索引）

## C. 开发决策日志

在 `docs/decisions.md` 记录每一个偏离 Spec 的决策：

```markdown
## YYYY-MM-DD — [标题]
**问题**：...
**决策**：...
**理由**：...
**影响**：修改了 [文件/配置项]
```

---

**End of Spec v1.1 (Final)**
