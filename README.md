# CodeMind MCP

**Let Claude search and understand your private codebase — locally, privately, fast.**

CodeMind is a local [MCP](https://modelcontextprotocol.io) server that indexes your code with
hybrid BM25 + dense embeddings and exposes five semantic-search tools to Claude Desktop (or any
MCP-compatible client). Your code never leaves your machine.

![Python ≥3.12](https://img.shields.io/badge/python-%E2%89%A53.12-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)
![MCP](https://img.shields.io/badge/protocol-MCP-purple)
[![CI](https://github.com/Sanyuewu/codemind-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/Sanyuewu/codemind-mcp/actions/workflows/ci.yml)

---

## Demo

*Demo GIF coming soon.*

> **Quick preview**: Ask Claude *"Where is the `jsonable_encoder` function?"*
> and CodeMind returns the exact file, line number, and source code in under 500 ms —
> even across a 100 k-line private monorepo.

---

## Why CodeMind?

| Problem | CodeMind's answer |
|---------|------------------|
| Claude doesn't know your private code | Local index — your code stays on your machine |
| Semantic search misses exact function names | Hybrid BM25 + BGE-M3 dense retrieval |
| Results are noisy / wrong file returned | BGE-reranker-v2-m3 cross-encoder reranking |
| One giant "search" tool is hard to use | Five atomic tools matched to developer intent |

---

## Features

- **Hybrid retrieval** — BM25 (keyword) + BGE-M3 (semantic) fused with Reciprocal Rank Fusion
- **Cross-encoder reranking** — BGE-reranker-v2-m3 re-scores top candidates for precision
- **Intent-aware routing** — locate queries ("where is X defined") automatically get a wider candidate pool; semantic queries keep tight precision
- **AST-aware chunking** — tree-sitter extracts function/class/method boundaries; no arbitrary line splits
- **Five specialized tools** — `semantic_search`, `get_function_by_name`, `find_references`, `list_files`, `get_git_blame`
- **Incremental indexing** — re-indexes only changed files; content-hash based
- **Multi-language** — Python, TypeScript, Java, Go
- **100% local** — Qdrant embedded + SQLite; nothing sent to the cloud

---

## Quick Start

### Prerequisites

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/) — `pip install uv`
- Git

### 1. Clone and install

```bash
git clone https://github.com/Sanyuewu/codemind-mcp.git
cd codemind-mcp
uv sync
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — set CODEMIND_REPO_PATH to your project's root
```

Minimum required setting:

```env
CODEMIND_REPO_PATH=/absolute/path/to/your/project
```

### 3. Index your codebase

```bash
uv run codemind index /absolute/path/to/your/project
```

First run downloads the BGE-M3 embedding model (~2 GB). Subsequent runs are incremental.

Progress is printed to stderr; the index is stored in `<repo>/.codemind/`.

```
Indexing /your/project ...
embedder.loaded  device=cpu  model=BAAI/bge-m3
indexing.started file_count=843
...
indexing.completed indexed=843 skipped=0 errors=0 total_chunks=4217 duration_s=312.4
```

### 4. Connect to Claude Desktop

Add the following to your Claude Desktop MCP config
(`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS,
`%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "codemind": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/codemind-mcp", "python", "main.py"],
      "env": {
        "CODEMIND_REPO_PATH": "/absolute/path/to/your/project"
      }
    }
  }
}
```

Restart Claude Desktop. You should see **CodeMind MCP** listed in the tools panel.

---

## Available Tools

| Tool | What it does |
|------|-------------|
| `semantic_search` | Natural-language search across indexed code using hybrid retrieval + reranking |
| `get_function_by_name` | Look up a specific function or class by exact name (fast, BM25-based) |
| `find_references` | Find all call sites and usages of a symbol across the codebase |
| `list_files` | List indexed files with optional path filter |
| `get_git_blame` | Show git blame for a file range to understand ownership and history |

---

## Evaluation Results

Tested on a 50-question eval set targeting the FastAPI codebase (1 119 files, 7 182 chunks), three intent categories: locate / understand / compare.

**Retrieval mode ablation** (Hybrid+Rerank with intent-aware routing is the production default):

| Config | R@1 | R@3 | R@5 | MRR |
|--------|-----|-----|-----|-----|
| BM25-only | 0.140 | 0.180 | 0.300 | 0.187 |
| Dense-only | 0.180 | 0.300 | 0.400 | 0.255 |
| Hybrid | 0.180 | 0.380 | 0.460 | 0.276 |
| Hybrid+Rerank | 0.240 | 0.400 | 0.560 | 0.350 |
| **Hybrid+Rerank + Intent Routing** | **0.260** | **0.420** | **0.600** | **0.373** |

Intent routing routes locate-type queries to a larger reranker candidate pool, improving locate R@5 from 0.45 → 0.55 with no regression on understand (0.60) or compare (0.70).

Full ablation report (chunking strategy, retrieval modes, tool design): [`docs/eval-report.md`](docs/eval-report.md)

---

## Architecture

```
Claude Desktop
     │  MCP stdio
     ▼
 CodeMind Server (server.py)
     │
     ├─ semantic_search ──► Retriever
     │                         ├─ BM25Retriever (rank-bm25, SQLite tokens)
     │                         ├─ DenseRetriever (BGE-M3 → Qdrant)
     │                         ├─ RRF Fusion
     │                         └─ Reranker (BGE-reranker-v2-m3)
     │
     ├─ get_function_by_name ──► MetadataStore (SQLite)
     ├─ find_references ──────► MetadataStore
     ├─ list_files ───────────► MetadataStore
     └─ get_git_blame ────────► git CLI
```

**Indexing pipeline**: `git ls-files` → tree-sitter AST chunking → BGE-M3 embeddings → Qdrant upsert + SQLite metadata

---

## Docker Deployment

### Build the image

```bash
docker build -t codemind-mcp .
```

### Index your codebase

```bash
docker run --rm \
  -v /path/to/your/repo:/repo:ro \
  -v $(pwd)/codemind-data:/data \
  -e CODEMIND_REPO_PATH=/repo \
  -e CODEMIND_DATA_DIR=/data \
  codemind-mcp uv run codemind index /repo
```

Or with docker-compose:

```bash
REPO_PATH=/path/to/your/repo docker compose run --rm index
```

### Connect Claude Desktop (Docker)

```json
{
  "mcpServers": {
    "codemind": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/path/to/your/repo:/repo:ro",
        "-v", "/path/to/codemind-data:/data",
        "-e", "CODEMIND_REPO_PATH=/repo",
        "-e", "CODEMIND_DATA_DIR=/data",
        "codemind-mcp"
      ]
    }
  }
}
```

---

## Configuration Reference

All settings are read from `.env` (or environment variables). Prefix: `CODEMIND_`.

| Variable | Default | Description |
|----------|---------|-------------|
| `CODEMIND_REPO_PATH` | **required** | Absolute path to the repository to index |
| `CODEMIND_DATA_DIR` | `./.codemind` | Where to store the vector index and SQLite DB |
| `CODEMIND_EMBEDDING_MODEL` | `BAAI/bge-m3` | HuggingFace embedding model (2 GB, highest recall) |
| `CODEMIND_EMBEDDING_DEVICE` | `cpu` | `cpu`, `cuda`, or `mps` |
| `CODEMIND_ENABLE_RERANKER` | `true` | Enable BGE cross-encoder reranking |
| `CODEMIND_ENABLE_BM25` | `true` | Enable BM25 sparse retrieval |
| `CODEMIND_ENABLE_DENSE` | `true` | Enable dense semantic retrieval |
| `CODEMIND_BM25_TOP_K` | `20` | BM25 candidate count |
| `CODEMIND_DENSE_TOP_K` | `20` | Dense candidate count |
| `CODEMIND_RERANK_INPUT_TOP_K` | `10` | Candidates sent to the reranker |
| `CODEMIND_MAX_FILE_SIZE_KB` | `500` | Skip files larger than this |
| `CODEMIND_RETRIEVAL_TIMEOUT_MS` | `20000` | Per-query timeout (ms) |
| `CODEMIND_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `CODEMIND_LOG_FORMAT` | `console` | `console` (human) or `json` (structured) |

**Lightweight mode** (faster indexing, lower recall):

```env
CODEMIND_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
CODEMIND_EMBEDDING_DIM=384
CODEMIND_ENABLE_RERANKER=false
```

---

## Development

```bash
# Install with dev dependencies
uv sync --dev

# Run tests
uv run pytest

# Type check
uv run python -m mypy src

# Re-index after code changes
uv run codemind index /path/to/repo --force
```

---

## License

MIT — see [LICENSE](LICENSE).
