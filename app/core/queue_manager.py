"""Priority-based download queue manager."""

import asyncio
import heapq
import logging
from datetime import datetime
from typing import Callable, Optional, Awaitable

from ..config import get_settings
from .job_store import get_job_store

logger = logging.getLogger(__name__)


class DownloadQueueManager:
    """
    Priority-based download queue with concurrent job processing.

    Priority levels: 1 (lowest) to 10 (highest).
    Jobs with higher priority are processed first.
    Within the same priority, jobs are processed in FIFO order.
    """

    def __init__(self, max_concurrent: Optional[int] = None):
        settings = get_settings()
        self._max_concurrent = max_concurrent or settings.max_concurrent_queue_jobs
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

        # Priority queue: list of (-priority, timestamp, job_id)
        # Using negative priority for max-heap behavior with heapq (min-heap)
        self._queue: list[tuple[int, float, str]] = []
        self._queue_lock = asyncio.Lock()

        # Track processing jobs
        self._processing: dict[str, asyncio.Task] = {}

        # Job processor callback
        self._processor: Optional[Callable[[str], Awaitable[None]]] = None

        # Queue state
        self._running = False
        self._process_task: Optional[asyncio.Task] = None

    def set_processor(self, processor: Callable[[str], Awaitable[None]]):
        """Set the job processor callback."""
        self._processor = processor

    async def start(self):
        """Start the queue processing loop."""
        if self._running:
            logger.warning("Queue manager already running")
            return

        self._running = True
        self._process_task = asyncio.create_task(self._process_loop())
        logger.info(f"Queue manager started with max_concurrent={self._max_concurrent}")

    async def stop(self):
        """Stop the queue processing loop."""
        self._running = False

        # Cancel the process loop
        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass

        # Wait for processing jobs to complete (with timeout)
        if self._processing:
            logger.info(f"Waiting for {len(self._processing)} jobs to complete...")
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._processing.values(), return_exceptions=True),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for jobs to complete")

        logger.info("Queue manager stopped")

    async def enqueue(self, job_id: str, priority: int = 5) -> None:
        """
        Add a job to the queue.

        Args:
            job_id: The job ID to queue
            priority: Priority level 1-10 (default 5)
        """
        priority = max(1, min(10, priority))  # Clamp to 1-10
        timestamp = datetime.utcnow().timestamp()

        async with self._queue_lock:
            # Check if already in queue
            for _, _, existing_id in self._queue:
                if existing_id == job_id:
                    logger.debug(f"Job {job_id} already in queue")
                    return

            # Add to priority queue (negative priority for max-heap)
            heapq.heappush(self._queue, (-priority, timestamp, job_id))
            logger.info(f"Enqueued job {job_id} with priority {priority}")

    async def update_priority(self, job_id: str, new_priority: int) -> bool:
        """
        Update a job's priority in the queue.

        Args:
            job_id: The job ID to update
            new_priority: New priority level 1-10

        Returns:
            True if the job was found and updated
        """
        new_priority = max(1, min(10, new_priority))

        async with self._queue_lock:
            # Find and remove the job
            found_idx = None
            old_timestamp = None
            for idx, (_, ts, jid) in enumerate(self._queue):
                if jid == job_id:
                    found_idx = idx
                    old_timestamp = ts
                    break

            if found_idx is None:
                return False

            # Remove old entry
            self._queue.pop(found_idx)
            heapq.heapify(self._queue)

            # Add with new priority (keep original timestamp for FIFO within priority)
            heapq.heappush(self._queue, (-new_priority, old_timestamp, job_id))
            logger.info(f"Updated job {job_id} priority to {new_priority}")

            # Update in database
            job_store = get_job_store()
            job_store.update_priority(job_id, new_priority)

            return True

    async def remove(self, job_id: str) -> bool:
        """Remove a job from the queue."""
        async with self._queue_lock:
            for idx, (_, _, jid) in enumerate(self._queue):
                if jid == job_id:
                    self._queue.pop(idx)
                    heapq.heapify(self._queue)
                    logger.info(f"Removed job {job_id} from queue")
                    return True
        return False

    async def _process_loop(self):
        """Main processing loop."""
        while self._running:
            try:
                # Get next job from queue
                job_id = await self._get_next_job()

                if job_id:
                    # Acquire semaphore for concurrent limit
                    await self._semaphore.acquire()

                    # Start processing in background
                    task = asyncio.create_task(self._process_job(job_id))
                    self._processing[job_id] = task

                    # Add callback to release semaphore and cleanup
                    task.add_done_callback(
                        lambda t, jid=job_id: self._on_job_complete(jid)
                    )
                else:
                    # No jobs in queue, wait a bit
                    await asyncio.sleep(1.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Queue processing error: {e}")
                await asyncio.sleep(1.0)

    async def _get_next_job(self) -> Optional[str]:
        """Get the next job from the queue."""
        async with self._queue_lock:
            if not self._queue:
                return None

            _, _, job_id = heapq.heappop(self._queue)
            return job_id

    async def _process_job(self, job_id: str):
        """Process a single job."""
        try:
            logger.info(f"Processing job {job_id}")

            if self._processor:
                await self._processor(job_id)
            else:
                logger.warning(f"No processor set for job {job_id}")

        except Exception as e:
            logger.exception(f"Error processing job {job_id}: {e}")

    def _on_job_complete(self, job_id: str):
        """Callback when a job completes."""
        self._processing.pop(job_id, None)
        self._semaphore.release()
        logger.debug(f"Job {job_id} completed processing")

    def get_queue_status(self) -> dict:
        """Get current queue status."""
        # Get jobs from queue
        queue_jobs = []
        for neg_priority, timestamp, job_id in sorted(self._queue):
            queue_jobs.append({
                "job_id": job_id,
                "priority": -neg_priority,
                "queued_at": datetime.fromtimestamp(timestamp).isoformat(),
            })

        return {
            "pending": len(self._queue),
            "processing": len(self._processing),
            "processing_jobs": list(self._processing.keys()),
            "max_concurrent": self._max_concurrent,
            "jobs": queue_jobs,
        }

    @property
    def is_running(self) -> bool:
        """Check if the queue manager is running."""
        return self._running


# Global instance
_queue_manager: Optional[DownloadQueueManager] = None


def get_queue_manager() -> DownloadQueueManager:
    """Get or create the global queue manager instance."""
    global _queue_manager
    if _queue_manager is None:
        _queue_manager = DownloadQueueManager()
    return _queue_manager


async def start_queue_manager():
    """Start the global queue manager."""
    manager = get_queue_manager()
    await manager.start()


async def stop_queue_manager():
    """Stop the global queue manager."""
    global _queue_manager
    if _queue_manager:
        await _queue_manager.stop()
        _queue_manager = None
