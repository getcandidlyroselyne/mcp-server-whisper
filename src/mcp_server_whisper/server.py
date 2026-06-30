"""Whisper MCP server - Minimal server setup with tool registration."""

from contextlib import asynccontextmanager

from fastmcp import FastMCP

from .config import get_config
from .infrastructure import FileSystemRepository, OpenAIClientWrapper, SecurePathResolver
from .services import AudioService, FileService, TranscriptionService, TTSService


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Initialize and tear down shared services for the lifetime of the server."""
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


mcp = FastMCP("whisper", dependencies=["openai", "pydub", "aiofiles"], lifespan=lifespan)


def main() -> None:
    """Run main entrypoint."""
    from .tools import register_all_tools

    register_all_tools(mcp)
    mcp.run()


if __name__ == "__main__":
    main()
