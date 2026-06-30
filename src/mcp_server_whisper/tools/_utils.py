"""Shared utilities for MCP tool implementations."""

from fastmcp import Context


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
