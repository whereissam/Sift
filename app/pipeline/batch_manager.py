"""Batch download manager."""

import asyncio
import logging
import uuid
from typing import Optional

from ..config import get_settings
from ..store import get_job_store, JobType
from .queue_manager import get_queue_manager

logger = logging.getLogger(__name__)


class BatchManager:
    """
    Manages batch download operations.

    Creates and tracks batches of related download jobs.
    """

    def __init__(self):
        self._job_store = get_job_store()

    def create_batch(
        self,
        urls: list[str],
        name: Optional[str] = None,
        priority: int = 5,
        webhook_url: Optional[str] = None,
        output_format: str = "m4a",
        quality: str = "high",
        **kwargs,
    ) -> tuple[str, list[str]]:
        """
        Create a batch of download jobs.

        Args:
            urls: List of URLs to download
            name: Optional name for the batch
            priority: Priority level 1-10 (default 5)
            webhook_url: Optional webhook URL for batch notifications
            output_format: Output format (default m4a)
            quality: Quality preset (default high)
            **kwargs: Additional options passed to job creation

        Returns:
            Tuple of (batch_id, list of job_ids)
        """
        batch_id = str(uuid.uuid4())

        # Create the batch record
        self._job_store.create_batch(
            batch_id=batch_id,
            name=name or f"Batch {batch_id[:8]}",
            total_jobs=len(urls),
            webhook_url=webhook_url,
        )

        job_ids = []
        settings = get_settings()
        effective_webhook = webhook_url or settings.default_webhook_url

        for url in urls:
            job_id = str(uuid.uuid4())

            # Create job with batch association
            self._job_store.create_job(
                job_id=job_id,
                job_type=JobType.DOWNLOAD,
                source_url=url,
                output_format=output_format,
                quality=quality,
                priority=priority,
                batch_id=batch_id,
                webhook_url=effective_webhook,
            )

            job_ids.append(job_id)

        logger.info(f"Created batch {batch_id} with {len(job_ids)} jobs")
        return batch_id, job_ids

    def get_batch_status(self, batch_id: str) -> Optional[dict]:
        """
        Get the status of a batch.

        Args:
            batch_id: The batch ID

        Returns:
            Batch data with status, or None if not found
        """
        # Update stats before returning
        self._job_store.update_batch_stats(batch_id)
        return self._job_store.get_batch(batch_id)

    def get_batch_jobs(self, batch_id: str) -> list[dict]:
        """
        Get all jobs in a batch.

        Args:
            batch_id: The batch ID

        Returns:
            List of job data
        """
        return self._job_store.get_batch_jobs(batch_id)

    def cancel_batch(self, batch_id: str) -> int:
        """
        Cancel all pending jobs in a batch.

        Args:
            batch_id: The batch ID

        Returns:
            Number of jobs cancelled
        """
        from ..store import JobStatus

        jobs = self._job_store.get_batch_jobs(batch_id)
        cancelled = 0

        for job in jobs:
            if job["status"] == JobStatus.PENDING.value:
                self._job_store.set_status(
                    job["job_id"],
                    JobStatus.FAILED,
                    error="Batch cancelled",
                )
                cancelled += 1

        # Update batch stats
        self._job_store.update_batch_stats(batch_id)
        logger.info(f"Cancelled {cancelled} jobs in batch {batch_id}")

        return cancelled

    async def enqueue_batch_jobs(self, batch_id: str) -> int:
        """
        Add all pending jobs in a batch to the processing queue.

        Args:
            batch_id: The batch ID

        Returns:
            Number of jobs enqueued
        """
        jobs = self._job_store.get_batch_jobs(batch_id)
        queue_manager = get_queue_manager()
        enqueued = 0

        for job in jobs:
            if job["status"] == "pending":
                priority = job.get("priority", 5)
                await queue_manager.enqueue(job["job_id"], priority)
                enqueued += 1
                # enqueue never suspends (its lock is uncontended), so yield
                # now and then to let other requests run.
                if enqueued % 100 == 0:
                    await asyncio.sleep(0)

        logger.info(f"Enqueued {enqueued} jobs from batch {batch_id}")
        return enqueued

    def list_batches(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        List all batches.

        Args:
            status: Optional status filter
            limit: Maximum number of batches to return

        Returns:
            List of batch data
        """
        return self._job_store.get_all_batches(status=status, limit=limit)


# Global instance
_batch_manager: Optional[BatchManager] = None


def get_batch_manager() -> BatchManager:
    """Get or create the global batch manager instance."""
    global _batch_manager
    if _batch_manager is None:
        _batch_manager = BatchManager()
    return _batch_manager
