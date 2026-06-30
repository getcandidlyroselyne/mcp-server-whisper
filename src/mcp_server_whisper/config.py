"""Configuration management for MCP Server Whisper."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings

from .exceptions import ConfigurationError


class WhisperConfig(BaseSettings):
    """Configuration for MCP Server Whisper.

    Loads configuration from environment variables with validation.
    Storage is either local filesystem (AUDIO_FILES_PATH) or Google Cloud
    Storage (GCS_BUCKET).  Exactly one must be set.
    """

    openai_api_key: str = Field(
        ...,
        description="OpenAI API key for accessing Whisper and GPT-4o models",
    )

    # --- Local filesystem storage (mutually exclusive with GCS) ---
    audio_files_path: Optional[Path] = Field(
        None,
        description="Path to the local directory containing audio files (set this or GCS_BUCKET)",
    )

    # --- Google Cloud Storage ---
    gcs_bucket: Optional[str] = Field(
        None,
        description="GCS bucket name (e.g. my-audio-bucket). Set this or AUDIO_FILES_PATH.",
    )
    gcs_prefix: str = Field(
        "",
        description="Object key prefix / folder inside the GCS bucket (e.g. 'recordings/')",
    )
    gcs_service_account_json: Optional[str] = Field(
        None,
        description=(
            "Service-account key as a JSON string. "
            "If omitted, Application Default Credentials are used."
        ),
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "arbitrary_types_allowed": True,
    }

    @field_validator("audio_files_path")
    @classmethod
    def validate_audio_path(cls, v: Optional[Path]) -> Optional[Path]:
        """Validate that the audio path exists and is a directory (when provided)."""
        if v is None:
            return v
        resolved_path = v.resolve()
        if not resolved_path.exists():
            raise ConfigurationError(f"Audio path does not exist: {resolved_path}")
        if not resolved_path.is_dir():
            raise ConfigurationError(f"Audio path is not a directory: {resolved_path}")
        return resolved_path

    @model_validator(mode="after")
    def validate_storage_config(self) -> "WhisperConfig":
        """Ensure exactly one storage backend is configured."""
        has_local = self.audio_files_path is not None
        has_gcs = bool(self.gcs_bucket)
        if has_local and has_gcs:
            raise ConfigurationError("Set either AUDIO_FILES_PATH or GCS_BUCKET, not both.")
        if not has_local and not has_gcs:
            raise ConfigurationError(
                "Storage backend is required: set AUDIO_FILES_PATH (local) or GCS_BUCKET (Google Cloud Storage)."
            )
        return self

    @property
    def use_gcs(self) -> bool:
        """Return True when Google Cloud Storage is the configured backend."""
        return bool(self.gcs_bucket)


@lru_cache
def get_config() -> WhisperConfig:
    """Get the application configuration (cached singleton).

    Returns
    -------
        WhisperConfig: The validated configuration object.

    Raises
    ------
        ConfigurationError: If configuration is invalid or missing.

    """
    try:
        return WhisperConfig()  # type: ignore
    except Exception as e:
        raise ConfigurationError(f"Failed to load configuration: {e}") from e


def check_and_get_audio_path() -> Path:
    """Check if the audio path environment variable is set and exists.

    This function maintains backward compatibility with the original implementation.

    Returns
    -------
        Path: The validated audio files path.

    Raises
    ------
        ValueError: If the audio path is not set or doesn't exist.

    """
    audio_path_str = os.getenv("AUDIO_FILES_PATH")
    if not audio_path_str:
        raise ValueError("AUDIO_FILES_PATH environment variable not set")

    audio_path = Path(audio_path_str).resolve()
    if not audio_path.exists():
        raise ValueError(f"Audio path does not exist: {audio_path}")
    return audio_path
