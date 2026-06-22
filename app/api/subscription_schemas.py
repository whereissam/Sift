"""Pydantic schemas for subscription API requests and responses."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field, field_validator


def _validate_output_dir_scope(value: Optional[str]) -> Optional[str]:
    """Reject output_dir values that resolve outside the configured download dir."""
    if not value:
        return value

    from ..config import get_settings

    download_root = Path(get_settings().download_dir).resolve()
    try:
        resolved = Path(value).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        raise ValueError("Invalid output_dir")

    if resolved != download_root and download_root not in resolved.parents:
        raise ValueError("output_dir must be under the download directory")
    return value


class SubscriptionType(str, Enum):
    """Types of subscriptions."""
    RSS = "rss"
    YOUTUBE_CHANNEL = "youtube_channel"
    YOUTUBE_PLAYLIST = "youtube_playlist"


class SubscriptionPlatform(str, Enum):
    """Supported platforms for subscriptions."""
    PODCAST = "podcast"
    YOUTUBE = "youtube"


class SubscriptionItemStatus(str, Enum):
    """Status states for subscription items."""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class CreateSubscriptionRequest(BaseModel):
    """Request to create a new subscription."""

    name: str = Field(
        ...,
        description="Display name for this subscription",
        min_length=1,
        max_length=200,
    )
    subscription_type: SubscriptionType = Field(
        ...,
        description="Type of subscription",
    )
    source_url: str = Field(
        ...,
        description="URL of the RSS feed, YouTube channel, or playlist",
    )
    auto_transcribe: bool = Field(
        default=False,
        description="Automatically transcribe downloaded content",
    )
    transcribe_model: str = Field(
        default="base",
        description="Whisper model size for transcription",
    )
    transcribe_language: Optional[str] = Field(
        default=None,
        description="Language code for transcription (auto-detect if not specified)",
    )
    download_limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of items to keep downloaded",
    )
    output_format: str = Field(
        default="m4a",
        description="Output audio format",
    )
    quality: str = Field(
        default="high",
        description="Quality preset",
    )
    output_dir: Optional[str] = Field(
        default=None,
        description="Custom output directory for downloads",
    )

    @field_validator("output_dir")
    @classmethod
    def _check_output_dir(cls, v: Optional[str]) -> Optional[str]:
        return _validate_output_dir_scope(v)


class UpdateSubscriptionRequest(BaseModel):
    """Request to update a subscription."""

    name: Optional[str] = Field(
        default=None,
        description="Display name for this subscription",
        min_length=1,
        max_length=200,
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="Whether the subscription is enabled",
    )
    auto_transcribe: Optional[bool] = Field(
        default=None,
        description="Automatically transcribe downloaded content",
    )
    transcribe_model: Optional[str] = Field(
        default=None,
        description="Whisper model size for transcription",
    )
    transcribe_language: Optional[str] = Field(
        default=None,
        description="Language code for transcription",
    )
    download_limit: Optional[int] = Field(
        default=None,
        ge=1,
        le=100,
        description="Maximum number of items to keep downloaded",
    )
    output_format: Optional[str] = Field(
        default=None,
        description="Output audio format",
    )
    quality: Optional[str] = Field(
        default=None,
        description="Quality preset",
    )
    output_dir: Optional[str] = Field(
        default=None,
        description="Custom output directory for downloads",
    )

    @field_validator("output_dir")
    @classmethod
    def _check_output_dir(cls, v: Optional[str]) -> Optional[str]:
        return _validate_output_dir_scope(v)


class SubscriptionResponse(BaseModel):
    """Response containing subscription details."""

    id: str
    name: str
    subscription_type: SubscriptionType
    source_url: Optional[str] = None
    source_id: Optional[str] = None
    platform: SubscriptionPlatform
    enabled: bool = True
    auto_transcribe: bool = False
    transcribe_model: str = "base"
    transcribe_language: Optional[str] = None
    download_limit: int = 10
    output_format: str = "m4a"
    quality: str = "high"
    output_dir: Optional[str] = None
    last_checked_at: Optional[datetime] = None
    last_new_content_at: Optional[datetime] = None
    total_downloaded: int = 0
    created_at: datetime
    updated_at: datetime
    # Computed fields
    pending_count: Optional[int] = None
    completed_count: Optional[int] = None


class SubscriptionListResponse(BaseModel):
    """Response containing list of subscriptions."""

    subscriptions: list[SubscriptionResponse]
    total: int


class SubscriptionItemResponse(BaseModel):
    """Response containing subscription item details."""

    id: str
    subscription_id: str
    content_id: str
    content_url: str
    title: Optional[str] = None
    published_at: Optional[datetime] = None
    status: SubscriptionItemStatus
    job_id: Optional[str] = None
    file_path: Optional[str] = None
    transcription_path: Optional[str] = None
    error: Optional[str] = None
    discovered_at: datetime
    downloaded_at: Optional[datetime] = None


class SubscriptionItemListResponse(BaseModel):
    """Response containing list of subscription items."""

    items: list[SubscriptionItemResponse]
    total: int
    subscription_id: str


class CheckSubscriptionResponse(BaseModel):
    """Response from force-checking a subscription."""

    subscription_id: str
    new_items_found: int
    items_queued: int
    message: str
