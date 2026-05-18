from __future__ import annotations

import structlog
from mcp.types import TextContent, Tool

from codemind.config import Settings
from codemind.exceptions import CodeMindError
from codemind.retrieval.retriever import Retriever
from codemind.storage.metadata_store import MetadataStore

log = structlog.get_logger()

TOOL = Tool(
    name="find_references",
    description=(
        "Scans the repository to locate all references and invocations of a\n"
        "specified symbol (function, class, or variable). Returns the exact file\n"
        "path, line number, and the enclosing caller context to build a dependency\n"
        "graph.\n"
        "\n"
        "OPTIMAL USE CASES (When to use):\n"
        '- Constructing mental call graphs (e.g., "Who calls this function?",\n'
        '  "Where is this class instantiated?").\n'
        "- Assessing the blast radius and impact of modifying a specific component.\n"
        "- Understanding a generic utility function's role by observing its\n"
        "  downstream usage."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Function, class, or variable name",
            },
            "language": {
                "type": "string",
                "enum": ["python", "typescript", "java", "go"],
                "description": "Optional language filter",
            },
        },
        "required": ["symbol"],
    },
)


async def handle(
    arguments: dict,
    retriever: Retriever,
    metadata_store: MetadataStore,
    settings: Settings,
) -> list[TextContent]:
    symbol = arguments["symbol"]
    language = arguments.get("language")
    try:
        refs = await retriever.find_references(symbol, language=language)

        if not refs:
            return [TextContent(
                type="text",
                text=f"Found 0 references to `{symbol}`.",
            )]

        lines = [f"Found {len(refs)} references to `{symbol}`:\n"]
        for ref in refs:
            if ref.enclosing_function:
                lines.append(
                    f"- `{ref.file_path}:{ref.line_number}` (in `{ref.enclosing_function}`)"
                )
            else:
                lines.append(f"- `{ref.file_path}:{ref.line_number}`")

        return [TextContent(type="text", text="\n".join(lines))]

    except CodeMindError as e:
        log.warning("tool.failed", tool_name="find_references", error=str(e))
        error_type = type(e).__name__
        return [TextContent(
            type="text",
            text=(
                f"**Error [{error_type}]**: {e}\n\n"
                "Suggested fix: ensure the repository has been indexed first:\n"
                "  codemind index /path/to/repo"
            ),
        )]
