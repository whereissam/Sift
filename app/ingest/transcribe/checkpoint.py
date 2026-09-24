"""Checkpoint management for resumable transcription."""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionCheckpoint:
    """Checkpoint data for resumable transcription."""

    job_id: str
    audio_path: str
    model_size: str
    language: Optional[str]
    task: str  # "transcribe" or "translate"
    output_format: str

    # Progress tracking
    last_end_time: float  # Last processed timestamp in seconds
    segments: list  # List of completed segments [{"start": float, "end": float, "text": str}]

    # Detected info
    detected_language: Optional[str] = None
    language_probability: Optional[float] = None
    total_duration: Optional[float] = None

    # Metadata
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()
        self.updated_at = datetime.utcnow().isoformat()


class CheckpointManager:
    """Manages transcription checkpoints for resume capability."""

    def __init__(self, checkpoint_dir: Optional[Path] = None):
        if checkpoint_dir:
            self.checkpoint_dir = checkpoint_dir
        else:
            from ..settings import get_ingest_settings
            settings = get_ingest_settings()
            self.checkpoint_dir = Path(settings.download_dir) / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _get_checkpoint_path(self, job_id: str) -> Path:
        return self.checkpoint_dir / f"{job_id}.checkpoint.json"

    def save(self, checkpoint: TranscriptionCheckpoint) -> None:
        """Save checkpoint to disk."""
        checkpoint.updated_at = datetime.utcnow().isoformat()
        path = self._get_checkpoint_path(checkpoint.job_id)

        try:
            with open(path, "w") as f:
                json.dump(asdict(checkpoint), f, indent=2)
            logger.debug(f"Saved checkpoint: {checkpoint.job_id} at {checkpoint.last_end_time:.2f}s")
        except Exception as e:
            logger.error(f"Failed to save checkpoint {checkpoint.job_id}: {e}")

    def load(self, job_id: str) -> Optional[TranscriptionCheckpoint]:
        """Load checkpoint from disk."""
        path = self._get_checkpoint_path(job_id)

        if not path.exists():
            return None

        try:
            with open(path) as f:
                data = json.load(f)
            return TranscriptionCheckpoint(**data)
        except Exception as e:
            logger.error(f"Failed to load checkpoint {job_id}: {e}")
            return None

    def delete(self, job_id: str) -> None:
        """Delete checkpoint after successful completion."""
        path = self._get_checkpoint_path(job_id)
        if path.exists():
            path.unlink()
            logger.debug(f"Deleted checkpoint: {job_id}")

    def exists(self, job_id: str) -> bool:
        """Check if checkpoint exists."""
        return self._get_checkpoint_path(job_id).exists()

    def list_checkpoints(self) -> list[str]:
        """List all available checkpoint job IDs."""
        return [
            p.stem.replace(".checkpoint", "")
            for p in self.checkpoint_dir.glob("*.checkpoint.json")
        ]

    def get_resumable_jobs(self) -> list[dict]:
        """Get list of jobs that can be resumed."""
        jobs = []
        for job_id in self.list_checkpoints():
            checkpoint = self.load(job_id)
            if checkpoint:
                jobs.append({
                    "job_id": job_id,
                    "audio_path": checkpoint.audio_path,
                    "progress_seconds": checkpoint.last_end_time,
                    "total_duration": checkpoint.total_duration,
                    "segments_completed": len(checkpoint.segments),
                    "updated_at": checkpoint.updated_at,
                })
        return jobs

    def cleanup_old_checkpoints(self, max_age_hours: int = 24) -> int:
        """Delete checkpoints older than max_age_hours."""
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        deleted = 0

        for job_id in self.list_checkpoints():
            checkpoint = self.load(job_id)
            if checkpoint:
                try:
                    updated = datetime.fromisoformat(checkpoint.updated_at)
                    if updated < cutoff:
                        self.delete(job_id)
                        deleted += 1
                        logger.info(f"Cleaned up old checkpoint: {job_id}")
                except (ValueError, TypeError):
                    # Invalid date, delete it
                    self.delete(job_id)
                    deleted += 1

        return deleted

    def cleanup_all(self) -> int:
        """Delete all checkpoints."""
        deleted = 0
        for job_id in self.list_checkpoints():
            self.delete(job_id)
            deleted += 1
        return deleted

    def get_storage_info(self) -> dict:
        """Get checkpoint storage information."""
        checkpoints = self.list_checkpoints()
        total_size = sum(
            self._get_checkpoint_path(job_id).stat().st_size
            for job_id in checkpoints
            if self._get_checkpoint_path(job_id).exists()
        )
        return {
            "checkpoint_dir": str(self.checkpoint_dir),
            "checkpoint_count": len(checkpoints),
            "total_size_kb": round(total_size / 1024, 2),
        }
