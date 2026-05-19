"""Job status and type enums."""

from enum import Enum


class JobStatus(str, Enum):
    """Job status states."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    CONVERTING = "converting"
    TRANSCRIBING = "transcribing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(str, Enum):
    """Job types."""

    DOWNLOAD = "download"
    TRANSCRIBE = "transcribe"
