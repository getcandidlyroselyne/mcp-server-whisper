"""Google Cloud Storage repository for audio file management."""

import json
import re
from pathlib import Path
from typing import Optional

import anyio
from openai.types import AudioModel

from ..constants import CHAT_WITH_AUDIO_FORMATS, TRANSCRIBE_AUDIO_FORMATS, AudioChatModel
from ..exceptions import AudioFileError, AudioFileNotFoundError
from ..models import FilePathSupportParams


class GCSStorageRepository:
    """Repository that stores audio files in a Google Cloud Storage bucket.

    Mirrors the interface of FileSystemRepository so that service classes work
    with either backend without modification.

    Args:
    ----
        bucket_name: GCS bucket name.
        prefix: Optional object-key prefix (e.g. ``"recordings/"``).
        service_account_json: Service-account key as a JSON string.
            When *None* the client falls back to Application Default Credentials.

    """

    def __init__(
        self,
        bucket_name: str,
        prefix: str = "",
        service_account_json: Optional[str] = None,
    ) -> None:
        """Initialise the repository and create the GCS client.

        Args:
        ----
            bucket_name: GCS bucket name.
            prefix: Optional object-key prefix (e.g. ``"recordings/"``).
            service_account_json: Service-account key as a JSON string.
                When *None* Application Default Credentials are used.

        """
        from google.cloud import storage  # type: ignore[import-untyped]

        self.bucket_name = bucket_name
        self.prefix = prefix.rstrip("/") + "/" if prefix.strip("/") else ""

        if service_account_json:
            from google.oauth2 import service_account as sa  # type: ignore[import-untyped]

            sa_info = json.loads(service_account_json)
            credentials = sa.Credentials.from_service_account_info(sa_info)
            self._client = storage.Client(credentials=credentials)
        else:
            self._client = storage.Client()

        self._bucket = self._client.bucket(bucket_name)
        # Cache blob modification times populated by list_audio_files()
        self._blob_mtimes: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_file_mtime(self, path: Path) -> float:
        """Return last-modified time (UTC epoch) for a blob key path.

        Falls back to 0.0 when the value is not cached yet.
        """
        return self._blob_mtimes.get(str(path), 0.0)

    # ------------------------------------------------------------------
    # Repository interface
    # ------------------------------------------------------------------

    async def get_audio_file_support(self, file_path: Path) -> FilePathSupportParams:
        """Fetch metadata for a single blob and return model-support info.

        Args:
        ----
            file_path: Path whose string representation is the GCS object key.

        Returns:
        -------
            FilePathSupportParams with metadata sourced from GCS blob attributes.

        """
        blob_name = str(file_path)
        blob = self._bucket.blob(blob_name)

        def _reload() -> None:
            blob.reload()

        await anyio.to_thread.run_sync(_reload)

        file_ext = Path(blob.name).suffix.lower()

        transcription_support: list[AudioModel] | None = (
            ["whisper-1", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"]
            if file_ext in TRANSCRIBE_AUDIO_FORMATS
            else None
        )
        chat_support: list[AudioChatModel] | None = (
            [
                "gpt-4o-audio-preview-2024-10-01",
                "gpt-4o-audio-preview-2024-12-17",
                "gpt-4o-mini-audio-preview-2024-12-17",
            ]
            if file_ext in CHAT_WITH_AUDIO_FORMATS
            else None
        )

        audio_format = file_ext[1:] if file_ext.startswith(".") else file_ext
        modified_time = blob.updated.timestamp() if blob.updated else 0.0
        self._blob_mtimes[blob_name] = modified_time

        return FilePathSupportParams(
            file_name=Path(blob.name).name,
            transcription_support=transcription_support,
            chat_support=chat_support,
            modified_time=modified_time,
            size_bytes=blob.size or 0,
            format=audio_format,
            duration_seconds=None,
        )

    async def get_latest_audio_file(self) -> FilePathSupportParams:
        """Return metadata for the most recently modified audio blob.

        Raises
        ------
            AudioFileNotFoundError: If no supported audio files are found.
            AudioFileError: On unexpected GCS errors.

        """
        try:
            blobs = await self._list_blobs()
            audio_blobs = [
                b
                for b in blobs
                if Path(b.name).suffix.lower() in TRANSCRIBE_AUDIO_FORMATS | CHAT_WITH_AUDIO_FORMATS
            ]
            if not audio_blobs:
                raise AudioFileNotFoundError("No supported audio files found in GCS bucket")

            latest = max(audio_blobs, key=lambda b: b.updated.timestamp() if b.updated else 0.0)
            return await self.get_audio_file_support(Path(latest.name))

        except AudioFileNotFoundError:
            raise
        except Exception as e:
            raise AudioFileError(f"Failed to get latest GCS audio file: {e}") from e

    async def list_audio_files(
        self,
        pattern: Optional[str] = None,
        min_size_bytes: Optional[int] = None,
        max_size_bytes: Optional[int] = None,
        format_filter: Optional[str] = None,
    ) -> list[Path]:
        """List audio blobs matching the given criteria.

        Also caches modification times for use by :meth:`get_file_mtime`.

        Args:
        ----
            pattern: Optional regex to filter blob names.
            min_size_bytes: Minimum blob size.
            max_size_bytes: Maximum blob size.
            format_filter: Audio format extension without leading dot (e.g. ``"mp3"``).

        Returns:
        -------
            list[Path]: Paths whose string representations are GCS object keys.

        """
        blobs = await self._list_blobs()
        result: list[Path] = []

        for blob in blobs:
            file_ext = Path(blob.name).suffix.lower()
            if file_ext not in TRANSCRIBE_AUDIO_FORMATS and file_ext not in CHAT_WITH_AUDIO_FORMATS:
                continue
            if pattern and not re.search(pattern, blob.name):
                continue
            if format_filter and file_ext[1:].lower() != format_filter.lower():
                continue
            blob_size = blob.size or 0
            if min_size_bytes is not None and blob_size < min_size_bytes:
                continue
            if max_size_bytes is not None and blob_size > max_size_bytes:
                continue

            blob_path = Path(blob.name)
            self._blob_mtimes[blob.name] = blob.updated.timestamp() if blob.updated else 0.0
            result.append(blob_path)

        return result

    async def read_audio_file(self, file_path: Path) -> bytes:
        """Download a blob and return its bytes.

        Args:
        ----
            file_path: Path whose string is the GCS object key.

        Returns:
        -------
            bytes: Raw file content.

        Raises:
        ------
            AudioFileNotFoundError: If the blob does not exist.
            AudioFileError: On unexpected GCS errors.

        """
        blob_name = str(file_path)
        blob = self._bucket.blob(blob_name)

        def _download() -> bytes:
            if not blob.exists():
                raise AudioFileNotFoundError(f"File not found in GCS: {blob_name}")
            return blob.download_as_bytes()  # type: ignore[return-value]

        try:
            return await anyio.to_thread.run_sync(_download)
        except AudioFileNotFoundError:
            raise
        except Exception as e:
            raise AudioFileError(f"Failed to read GCS file '{blob_name}': {e}") from e

    async def write_audio_file(self, file_path: Path, content: bytes) -> None:
        """Upload bytes to GCS as a new or updated blob.

        Args:
        ----
            file_path: Path whose string is the GCS object key.
            content: File content to upload.

        Raises:
        ------
            AudioFileError: On unexpected GCS errors.

        """
        blob_name = str(file_path)
        blob = self._bucket.blob(blob_name)

        def _upload() -> None:
            blob.upload_from_string(content)

        try:
            await anyio.to_thread.run_sync(_upload)
        except Exception as e:
            raise AudioFileError(f"Failed to write GCS file '{blob_name}': {e}") from e

    async def get_file_size(self, file_path: Path) -> int:
        """Return the size in bytes of a blob.

        Args:
        ----
            file_path: Path whose string is the GCS object key.

        Returns:
        -------
            int: Blob size in bytes.

        Raises:
        ------
            AudioFileNotFoundError: If the blob does not exist.

        """
        blob_name = str(file_path)
        blob = self._bucket.blob(blob_name)

        def _size() -> int:
            blob.reload()
            if blob.size is None:
                raise AudioFileNotFoundError(f"File not found in GCS: {blob_name}")
            return blob.size  # type: ignore[return-value]

        return await anyio.to_thread.run_sync(_size)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _list_blobs(self) -> list:
        def _list() -> list:
            return list(self._client.list_blobs(self.bucket_name, prefix=self.prefix or None))

        return await anyio.to_thread.run_sync(_list)
