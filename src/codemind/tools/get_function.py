from __future__ import annotations

import structlog
from mcp.types import TextContent, Tool

from codemind.config import Settings
from codemind.exceptions import CodeMindError
from codemind.retrieval.retriever import Retriever
from codemind.storage.metadata_store import MetadataStore

log = structlog.get_logger()

TOOL = Tool(
    name="get_function_by_name",
    description=(
        "Retrieves the complete, verbatim source code of a specific function or\n"
        "method using its exact symbol name. Returns the full implementation,\n"
        "including signatures, docstrings, and internal logic.\n"
        "\n"
        "OPTIMAL USE CASES (When to use):\n"
        "- Deep diving into a specific component's implementation details.\n"
        "- Extracting the complete logic block after identifying a target symbol\n"
        "  via semantic_search.\n"
        '- The user explicitly requests the code for "function X".\n'
        "\n"
        "ANTI-PATTERNS (Do NOT use when):\n"
        "- The target name is ambiguous, partial, or described in natural language\n"
        "  → fall back to semantic_search."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "function_name": {
                "type": "string",
                "description": "Exact function or method name",
            },
            "file_path": {
                "type": "string",
                "description": "Optional. Restrict search to a specific file",
            },
        },
        "required": ["function_name"],
    },
)


async def handle(
    arguments: dict,
    retriever: Retriever,
    metadata_store: MetadataStore,
    settings: Settings,
) -> list[TextContent]:
    function_name = arguments["function_name"]
    file_path = arguments.get("file_path")
    try:
        results = await retriever.find_function(function_name, file_path=file_path)

        if not results:
            return [TextContent(
                type="text",
                text=f'No function named "{function_name}" found in the index.',
            )]

        lines = [f'Found {len(results)} results for function "{function_name}":\n']
        for i, c in enumerate(results, 1):
            lines.append(
                f"### {i}. `{c.name}` · `{c.file_path}` · "
                f"lines {c.start_line}–{c.end_line}\n"
            )
            lines.append(f"```{c.language}\n{c.code}\n```\n")

        return [TextContent(type="text", text="\n".join(lines))]

    except CodeMindError as e:
        log.warning("tool.failed", tool_name="get_function_by_name", error=str(e))
        error_type = type(e).__name__
        return [TextContent(
            type="text",
            text=(
                f"**Error [{error_type}]**: {e}\n\n"
                "Suggested fix: ensure the repository has been indexed first:\n"
                "  codemind index /path/to/repo"
            ),
        )]
