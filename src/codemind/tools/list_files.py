from __future__ import annotations

import structlog
from mcp.types import TextContent, Tool

from codemind.config import Settings
from codemind.exceptions import CodeMindError
from codemind.retrieval.retriever import Retriever
from codemind.storage.metadata_store import MetadataStore

log = structlog.get_logger()

TOOL = Tool(
    name="list_files",
    description=(
        "Explores the repository's file topology. Returns a mapped list of indexed\n"
        "files, detailing their language types and chunk metrics. Supports granular\n"
        "filtering by directory boundaries or glob patterns.\n"
        "\n"
        "OPTIMAL USE CASES (When to use):\n"
        "- Establishing a high-level macro understanding of the project's layout\n"
        "  and module distribution.\n"
        "- Locating specific categories of files before initiating deeper code\n"
        '  searches (e.g., finding all test_*.py files).'
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Optional. Subdirectory to list (relative to repo root)",
            },
            "language": {
                "type": "string",
                "enum": ["python", "typescript", "java", "go"],
                "description": "Optional language filter",
            },
            "pattern": {
                "type": "string",
                "description": 'Optional glob (e.g., "**/test_*.py")',
            },
        },
    },
)


async def handle(
    arguments: dict,
    retriever: Retriever,
    metadata_store: MetadataStore,
    settings: Settings,
) -> list[TextContent]:
    language = arguments.get("language")
    directory = arguments.get("directory")
    pattern = arguments.get("pattern")
    try:
        files = await metadata_store.list_files(
            language=language,
            directory=directory,
            pattern=pattern,
        )

        if not files:
            return [TextContent(
                type="text",
                text="No indexed files found matching the given filters.",
            )]

        lines = [f"Found {len(files)} indexed files:\n"]
        lines.append("| File | Language | Chunks |")
        lines.append("|------|----------|--------|")
        for f in files:
            lines.append(f"| {f.path} | {f.language} | {f.chunk_count} |")

        return [TextContent(type="text", text="\n".join(lines))]

    except CodeMindError as e:
        log.warning("tool.failed", tool_name="list_files", error=str(e))
        error_type = type(e).__name__
        return [TextContent(
            type="text",
            text=(
                f"**Error [{error_type}]**: {e}\n\n"
                "Suggested fix: ensure the repository has been indexed first:\n"
                "  codemind index /path/to/repo"
            ),
        )]
