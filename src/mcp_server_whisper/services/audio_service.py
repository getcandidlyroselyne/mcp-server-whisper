"""Audio processing service - orchestrates domain and infrastructure."""

import tempfile
from pathlib import Path
from typing import Union

from ..constants import DEFAULT_MAX_FILE_SIZE_MB, SupportedChatWithAudioFormat
from ..domain import AudioProcessor
from ..infrastructure import FileSystemRepository, GCSPathResolver, GCSStorageRepository, SecurePathResolver
from ..models import AudioProcessingResult

StorageRepo = Union[FileSystemRepository, GCSStorageRepository]
PathResolver = Union[SecurePathResolver, GCSPathResolver]


class AudioService:
    """Service for audio conversion and compression operations."""

    def __init__(self, file_repo: StorageRepo, path_resolver: PathResolver):
        """Initialize the audio service.

        Args:
        ----
            file_repo: Storage repository for I/O operations (local or GCS).
            path_resolver: Path resolver for filename-to-key conversion.

        """
        self.file_repo = file_repo
        self.processor = AudioProcessor()
        self.path_resolver = path_resolver

    async def convert_audio(
        self,
        input_filename: str,
        output_filename: str | None = None,
        target_format: SupportedChatWithAudioFormat = "mp3",
    ) -> AudioProcessingResult:
        """Convert audio file to supported format (mp3 or wav).

        Args:
        ----
            input_filename: Name of input audio file.
            output_filename: Optional name for output file.
            target_format: Target format ('mp3' or 'wav').

        Returns:
        -------
            AudioProcessingResult: Result with name of the converted audio file.

        """
        input_path = self.path_resolver.resolve_input(input_filename)
        output_name = output_filename or f"{Path(input_filename).stem}.{target_format}"
        output_path = self.path_resolver.resolve_output(output_name, f"{Path(input_filename).stem}.{target_format}")

        # Download bytes then load from in-memory buffer (works for both local and GCS)
        audio_bytes = await self.file_repo.read_audio_file(input_path)
        fmt = input_path.suffix[1:] if input_path.suffix else target_format
        audio_data = await self.processor.load_audio_from_bytes(audio_bytes, fmt)

        # pydub requires a real filesystem path for export; use a temp file
        with tempfile.NamedTemporaryFile(suffix=f".{target_format}", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            converted_bytes = await self.processor.convert_audio_format(audio_data, target_format, tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        await self.file_repo.write_audio_file(output_path, converted_bytes)
        return AudioProcessingResult(output_file=output_path.name)

    async def compress_audio(
        self,
        input_filename: str,
        output_filename: str | None = None,
        max_mb: int = DEFAULT_MAX_FILE_SIZE_MB,
    ) -> AudioProcessingResult:
        """Compress audio file if it exceeds size limit.

        Args:
        ----
            input_filename: Name of input audio file.
            output_filename: Optional name for output file.
            max_mb: Maximum file size in MB.

        Returns:
        -------
            AudioProcessingResult: Result with name of the compressed audio file (or original if no compression needed).

        """
        input_path = self.path_resolver.resolve_input(input_filename)
        file_size = await self.file_repo.get_file_size(input_path)
        needs_compression = self.processor.calculate_compression_needed(file_size, max_mb)

        if not needs_compression:
            return AudioProcessingResult(output_file=input_filename)

        print(f"\n[AudioService] File '{input_filename}' size > {max_mb}MB. Attempting compression...")

        # Convert to MP3 first if needed
        if input_path.suffix.lower() != ".mp3":
            print("[AudioService] Converting to MP3 first...")
            conversion_result = await self.convert_audio(input_filename, None, "mp3")
            input_filename = conversion_result.output_file
            input_path = self.path_resolver.resolve_input(input_filename)

        output_name = output_filename or f"compressed_{input_path.stem}.mp3"
        output_path = self.path_resolver.resolve_output(output_name, f"compressed_{input_path.stem}.mp3")

        print(f"[AudioService] Original file: {input_filename}")
        print(f"[AudioService] Output file: {output_name}")

        audio_bytes = await self.file_repo.read_audio_file(input_path)
        audio_data = await self.processor.load_audio_from_bytes(audio_bytes, "mp3")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            compressed_bytes = await self.processor.compress_mp3(audio_data, tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        await self.file_repo.write_audio_file(output_path, compressed_bytes)
        print(f"[AudioService] Compressed file size: {len(compressed_bytes)} bytes")
        return AudioProcessingResult(output_file=output_path.name)

    async def maybe_compress_file(
        self,
        input_filename: str,
        output_filename: str | None = None,
        max_mb: int = DEFAULT_MAX_FILE_SIZE_MB,
    ) -> AudioProcessingResult:
        """Compress file if needed, maintaining backward compatibility.

        This method provides the same interface as the original server.py function.

        Args:
        ----
            input_filename: Name of input audio file.
            output_filename: Optional name for output file.
            max_mb: Maximum file size in MB.

        Returns:
        -------
            AudioProcessingResult: Result with name of the (possibly compressed) audio file.

        """
        return await self.compress_audio(input_filename, output_filename, max_mb)
