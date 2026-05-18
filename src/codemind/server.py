from __future__ import annotations

import asyncio
import logging
import sys
import time

import structlog
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from codemind.config import Settings
from codemind.exceptions import ConfigError
from codemind.retrieval.retriever import Retriever
from codemind.storage.metadata_store import MetadataStore
from codemind.tools import find_references, get_function, git_blame, list_files, search

log = structlog.get_logger()

_retriever: Retriever | None = None
_metadata_store: MetadataStore | None = None
_settings: Settings | None = None


def _configure_logging(settings: Settings) -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer() if settings.log_format == "console"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


server = Server("codemind")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        search.TOOL,
        get_function.TOOL,
        find_references.TOOL,
        list_files.TOOL,
        git_blame.TOOL,
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    assert _retriever is not None
    assert _metadata_store is not None
    assert _settings is not None

    start = time.monotonic()

    if name == "semantic_search":
        log.info(
            "tool.invoked",
            tool_name=name,
            query=arguments.get("query", ""),
            top_k=arguments.get("top_k", 5),
        )
    elif name == "get_function_by_name":
        log.info(
            "tool.invoked",
            tool_name=name,
            function_name=arguments.get("function_name", ""),
            file_path=arguments.get("file_path"),
        )
    elif name == "find_references":
        log.info(
            "tool.invoked",
            tool_name=name,
            symbol=arguments.get("symbol", ""),
            language=arguments.get("language"),
        )
    elif name == "list_files":
        log.info(
            "tool.invoked",
            tool_name=name,
            directory=arguments.get("directory"),
            language=arguments.get("language"),
            pattern=arguments.get("pattern"),
        )
    elif name == "get_git_blame":
        log.info(
            "tool.invoked",
            tool_name=name,
            file_path=arguments.get("file_path", ""),
            start_line=arguments.get("start_line"),
            end_line=arguments.get("end_line"),
        )
    else:
        raise ValueError(f"Unknown tool: {name}")

    result = await _dispatch(name, arguments)

    duration_ms = round((time.monotonic() - start) * 1000)
    log.info("tool.completed", tool_name=name, duration_ms=duration_ms, result_count=len(result))
    return result


async def _dispatch(name: str, arguments: dict) -> list[TextContent]:
    assert _retriever is not None
    assert _metadata_store is not None
    assert _settings is not None

    if name == "semantic_search":
        await _retriever.initialize()  # loads embedding model on first call only
        return await search.handle(arguments, _retriever, _metadata_store, _settings)
    elif name == "get_function_by_name":
        return await get_function.handle(arguments, _retriever, _metadata_store, _settings)
    elif name == "find_references":
        return await find_references.handle(arguments, _retriever, _metadata_store, _settings)
    elif name == "list_files":
        return await list_files.handle(arguments, _retriever, _metadata_store, _settings)
    elif name == "get_git_blame":
        return await git_blame.handle(arguments, _retriever, _metadata_store, _settings)
    else:
        raise ValueError(f"Unknown tool: {name}")


async def main() -> None:
    global _retriever, _metadata_store, _settings

    try:
        settings = Settings()
    except Exception as e:
        raise ConfigError(f"Failed to load settings: {e}") from e

    _configure_logging(settings)
    log.info("server.starting", server="codemind")

    _settings = settings
    _metadata_store = MetadataStore(settings)
    _retriever = Retriever(_metadata_store, settings)
    # Pre-warm thread pool so first tool call (list_files etc.) isn't delayed
    await asyncio.to_thread(lambda: None)
    # Embedding model loaded lazily on first semantic_search call

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
