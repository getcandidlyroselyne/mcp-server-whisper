"""Whisper MCP server - Minimal server setup with tool registration."""

from contextlib import asynccontextmanager

from fastmcp import FastMCP

# Absolute imports are required here because fastmcp inspect loads this file
# directly (not as part of the package), so relative imports would fail.
# The package is installed via uv sync, so absolute imports resolve correctly.
from mcp_server_whisper.config import get_config
from mcp_server_whisper.infrastructure import FileSystemRepository, OpenAIClientWrapper, SecurePathResolver
from mcp_server_whisper.services import AudioService, FileService, TranscriptionService, TTSService
from mcp_server_whisper.tools import register_all_tools


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Initialize and tear down shared services for the lifetime of the server.

    If configuration is missing or invalid the server still starts; individual
    tool calls will raise a descriptive error in that case.
    """
    try:
        config = get_config()
        audio_path = config.audio_files_path

        file_repo = FileSystemRepository(audio_path)
        openai_client = OpenAIClientWrapper(api_key=config.openai_api_key)
        path_resolver = SecurePathResolver(audio_path)

        yield {
            "file_service": FileService(file_repo),
            "audio_service": AudioService(file_repo, path_resolver),
            "transcription_service": TranscriptionService(file_repo, openai_client, path_resolver),
            "tts_service": TTSService(file_repo, openai_client, path_resolver),
        }
    except Exception as e:
        # Server starts successfully so the MCP handshake works; tools will
        # surface this error when called without valid configuration.
        yield {"_config_error": str(e)}


mcp = FastMCP("whisper", lifespan=lifespan)

# Register tools at module level so fastmcp inspect can discover all tools.
register_all_tools(mcp)


def main() -> None:
    """Run main entrypoint."""
    mcp.run()


if __name__ == "__main__":
    main()
