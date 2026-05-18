from __future__ import annotations

from datetime import datetime, timezone

import git
import structlog
from mcp.types import TextContent, Tool

from codemind.config import Settings
from codemind.exceptions import CodeMindError
from codemind.models import BlameLine
from codemind.retrieval.retriever import Retriever
from codemind.storage.metadata_store import MetadataStore

log = structlog.get_logger()

TOOL = Tool(
    name="get_git_blame",
    description=(
        "Retrieves line-level Git provenance and historical context for a specified\n"
        "file. Outputs the author, precise timestamp, commit hash, and summary\n"
        "commit message for the target line range.\n"
        "\n"
        "OPTIMAL USE CASES (When to use):\n"
        "- Identifying the original author or domain expert for a specific code block.\n"
        '- Understanding the historical "why" behind a specific implementation or\n'
        "  bug fix.\n"
        "- Resolving context gaps by tracing when a specific line of code was\n"
        "  introduced."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "start_line": {
                "type": "integer",
                "description": "Optional, default 1",
            },
            "end_line": {
                "type": "integer",
                "description": "Optional, default end of file",
            },
        },
        "required": ["file_path"],
    },
)


async def handle(
    arguments: dict,
    retriever: Retriever,
    metadata_store: MetadataStore,
    settings: Settings,
) -> list[TextContent]:
    file_path = arguments["file_path"]
    _repo_str = str(settings.repo_path).replace("\\", "/")
    _fp_normalized = file_path.replace("\\", "/")
    if _fp_normalized.startswith(_repo_str):
        file_path = _fp_normalized[len(_repo_str):].lstrip("/")
    start_line = arguments.get("start_line", 1)
    end_line = arguments.get("end_line")

    try:
        repo = git.Repo(settings.repo_path, search_parent_directories=True)
        blame_data = repo.blame("HEAD", file_path)

        blame_lines: list[BlameLine] = []
        line_number = 1
        for commit, file_lines in blame_data:
            for raw_line in file_lines:
                content = (
                    raw_line.decode("utf-8", errors="replace")
                    if isinstance(raw_line, bytes)
                    else raw_line
                )
                blame_lines.append(
                    BlameLine(
                        line_number=line_number,
                        content=content.rstrip("\n"),
                        author=commit.author.name,
                        commit_hash=commit.hexsha[:8],
                        commit_date=datetime.fromtimestamp(
                            commit.authored_date, tz=timezone.utc
                        ),
                        commit_message=commit.message.split("\n")[0],
                    )
                )
                line_number += 1

        actual_end = end_line if end_line is not None else len(blame_lines)
        filtered = [bl for bl in blame_lines if start_line <= bl.line_number <= actual_end]

        if not filtered:
            return [TextContent(
                type="text",
                text=f"No lines found in `{file_path}` for range {start_line}–{actual_end}.",
            )]

        header = (
            f"Git blame for `{file_path}` "
            f"(lines {start_line}–{actual_end}):\n"
        )
        rows = ["| Line | Author | Commit | Date | Message |"]
        rows.append("|------|--------|--------|------|---------|")
        for bl in filtered:
            date_str = bl.commit_date.strftime("%Y-%m-%d")
            rows.append(
                f"| {bl.line_number} | {bl.author} | {bl.commit_hash} "
                f"| {date_str} | {bl.commit_message} |"
            )

        return [TextContent(type="text", text=header + "\n".join(rows))]

    except (git.exc.InvalidGitRepositoryError, git.exc.GitCommandError, git.exc.NoSuchPathError) as e:
        error_msg = str(e)
        log.warning("tool.failed", tool_name="get_git_blame", error=error_msg)
        return [TextContent(
            type="text",
            text=(
                f"**Error [RetrievalError]**: {error_msg}\n\n"
                "Suggested fix: ensure the file path is correct and the repository\n"
                "  has been initialized with git."
            ),
        )]
    except CodeMindError as e:
        log.warning("tool.failed", tool_name="get_git_blame", error=str(e))
        error_type = type(e).__name__
        return [TextContent(
            type="text",
            text=(
                f"**Error [{error_type}]**: {e}\n\n"
                "Suggested fix: ensure the repository has been indexed first:\n"
                "  codemind index /path/to/repo"
            ),
        )]
