"""MCP tools for Whisper server."""

from fastmcp import Context

from ..infrastructure import MCPServer
from .audio_tools import create_audio_tools
from .file_tools import create_file_tools
from .transcription_tools import create_transcription_tools
from .tts_tools import create_tts_tools


def require_service(ctx: Context, key: str) -> object:
    """Retrieve a service from the lifespan context, raising clearly if config failed.

    Args:
    ----
        ctx: FastMCP request context.
        key: Service key to look up.

    Raises:
    ------
        RuntimeError: If the server was not configured with the required env vars.

    """
    if "_config_error" in ctx.lifespan_context:
        raise RuntimeError(
            f"Server is not configured — set OPENAI_API_KEY and AUDIO_FILES_PATH. "
            f"Config error: {ctx.lifespan_context['_config_error']}"
        )
    return ctx.lifespan_context[key]

__all__ = [
    "create_file_tools",
    "create_audio_tools",
    "create_transcription_tools",
    "create_tts_tools",
]


def register_all_tools(mcp: MCPServer) -> None:
    """Register all MCP tools with the server.

    Args:
    ----
        mcp: FastMCP server instance.

    """
    create_file_tools(mcp)
    create_audio_tools(mcp)
    create_transcription_tools(mcp)
    create_tts_tools(mcp)
