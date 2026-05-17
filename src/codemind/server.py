from __future__ import annotations

import asyncio
import logging
import time

import structlog
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from codemind.config import Settings
from codemind.exceptions import ConfigError

log = structlog.get_logger()


def _configure_logging(settings: Settings) -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.dev.ConsoleRenderer() if settings.log_format == "console"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
    )


server = Server("codemind")

ECHO_TOOL = Tool(
    name="echo",
    description="Echo the input message back to the caller.",
    inputSchema={
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Message to echo"}
        },
        "required": ["message"],
    },
)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [ECHO_TOOL]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    start = time.monotonic()
    log.info("tool.invoked", tool_name=name)

    if name == "echo":
        message = arguments["message"]
        duration_ms = round((time.monotonic() - start) * 1000)
        log.info("tool.completed", tool_name=name, duration_ms=duration_ms, result_count=1)
        return [TextContent(type="text", text=message)]

    raise ValueError(f"Unknown tool: {name}")


async def main() -> None:
    try:
        settings = Settings()
    except Exception as e:
        raise ConfigError(f"Failed to load settings: {e}") from e

    _configure_logging(settings)
    log.info("server.starting", server="codemind")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
