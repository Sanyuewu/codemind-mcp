from __future__ import annotations

import structlog
from mcp.types import TextContent, Tool

from codemind.config import Settings
from codemind.exceptions import CodeMindError
from codemind.models import SearchQuery
from codemind.retrieval.retriever import Retriever
from codemind.storage.metadata_store import MetadataStore

log = structlog.get_logger()

TOOL = Tool(
    name="semantic_search",
    description=(
        "Executes a hybrid retrieval (Dense Semantic + BM25 Keyword) across the\n"
        "indexed codebase to extract the most contextually relevant code chunks\n"
        "(functions, classes, or modules).\n"
        "\n"
        "OPTIMAL USE CASES (When to use):\n"
        '- Conceptual inquiries (e.g., "How is user authentication implemented?",\n'
        '  "Where is the retry logic for database connections?").\n'
        "- Exploring unknown architectural patterns using natural language descriptions.\n"
        "- Discovering code when the exact symbol names are unknown.\n"
        "\n"
        "ANTI-PATTERNS (Do NOT use when):\n"
        "- You already know the exact function/class name → use get_function_by_name\n"
        "  instead for full precision.\n"
        "- You need to map the directory structure → use list_files instead.\n"
        "- You are tracking historical code changes → use get_git_blame instead."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language description of what to find",
            },
            "top_k": {
                "type": "integer",
                "default": 5,
                "maximum": 20,
                "description": "Number of results to return",
            },
            "language": {
                "type": "string",
                "enum": ["python", "typescript", "java", "go"],
                "description": "Optional language filter",
            },
            "chunk_types": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["function", "class", "method", "module"],
                },
                "description": "Optional chunk type filter",
            },
        },
        "required": ["query"],
    },
)


async def handle(
    arguments: dict,
    retriever: Retriever,
    metadata_store: MetadataStore,
    settings: Settings,
) -> list[TextContent]:
    query_text = arguments["query"]
    try:
        query = SearchQuery(
            query=query_text,
            top_k=arguments.get("top_k", 5),
            language=arguments.get("language"),
            chunk_types=arguments.get("chunk_types"),
        )
        results = await retriever.search(query)

        if not results:
            return [TextContent(type="text", text=f'No results found for "{query_text}".')]

        lines = [f'Found {len(results)} results for "{query_text}":\n']
        for i, rc in enumerate(results, 1):
            c = rc.chunk
            lines.append(
                f"### {i}. `{c.name}` · `{c.file_path}` · "
                f"lines {c.start_line}–{c.end_line} · score {rc.score:.2f}\n"
            )
            lines.append(f"```{c.language}\n{c.code}\n```\n")

        return [TextContent(type="text", text="\n".join(lines))]

    except CodeMindError as e:
        log.warning("tool.failed", tool_name="semantic_search", error=str(e))
        error_type = type(e).__name__
        return [TextContent(
            type="text",
            text=(
                f"**Error [{error_type}]**: {e}\n\n"
                "Suggested fix: ensure the repository has been indexed first:\n"
                "  codemind index /path/to/repo"
            ),
        )]
