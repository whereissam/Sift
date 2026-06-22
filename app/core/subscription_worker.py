"""Background worker for processing subscriptions."""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import re

from ..config import get_settings
from .subscription_store import (
    get_subscription_store,
    SubscriptionStore,
    SubscriptionItemStatus,
)
from .subscription_fetcher import get_fetcher
from .downloader import DownloaderFactory
from .url_validator import safe_stream


def _is_direct_audio_url(url: str) -> bool:
    """Check if URL is a direct audio file link."""
    audio_extensions = ('.mp3', '.m4a', '.aac', '.ogg', '.wav', '.flac', '.opus')
    # Check URL path for audio extension
    path = url.split('?')[0].lower()
    return any(path.endswith(ext) for ext in audio_extensions)


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
    sanitized = re.sub(r'\s+', '_', sanitized)
    return sanitized[:100]


async def _download_direct_audio(
    url: str,
    output_dir: Path,
    title: Optional[str] = None,
    output_format: str = "m4a",
) -> Optional[Path]:
    """Download audio directly from URL."""
    try:
        # Determine filename
        if title:
            base_name = _sanitize_filename(title)
        else:
            # Extract from URL
            base_name = url.split('/')[-1].split('?')[0]
            base_name = re.sub(r'\.[^.]+$', '', base_name)  # Remove extension

        # Get extension from URL
        url_path = url.split('?')[0].lower()
        ext = '.mp3'  # Default
        for e in ['.mp3', '.m4a', '.aac', '.ogg', '.wav', '.flac', '.opus']:
            if url_path.endswith(e):
                ext = e
                break

        output_path = output_dir / f"{base_name}{ext}"

        logger.info(f"Direct downloading: {url[:80]}...")

        # SSRF protection: validate (and re-validate redirects) before streaming.
        try:
            async with safe_stream(url, timeout=300.0) as resp:
                resp.raise_for_status()
                with open(output_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=8192):
                        f.write(chunk)
        except ValueError as e:
            logger.warning(f"Blocked direct download for {url[:80]}: {e}")
            return None

        # Convert format if needed (but skip mp3->m4a as it requires re-encoding)
        # MP3 and M4A are both widely compatible, so we keep the original format
        needs_conversion = (
            output_format
            and f".{output_format}" != ext
            and not (ext == '.mp3' and output_format == 'm4a')  # Skip mp3->m4a
            and not (ext == '.m4a' and output_format == 'mp3')  # Skip m4a->mp3 remux
        )

        if needs_conversion:
            from .converter import AudioConverter
            converter = AudioConverter()
            if converter.is_ffmpeg_available():
                logger.info(f"Converting to {output_format}...")
                try:
                    converted_path = await converter.convert(
                        input_path=output_path,
                        output_format=output_format,
                        quality="high",
                        keep_original=False,
                    )
                    output_path = converted_path
                except Exception as e:
                    logger.warning(f"Conversion failed, keeping original: {e}")

        logger.info(f"Direct download complete: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Direct download failed: {e}")
        return None

logger = logging.getLogger(__name__)

# Global worker instance
_worker: Optional["SubscriptionWorker"] = None


class SubscriptionWorker:
    """Background worker that periodically checks subscriptions for new content."""

    def __init__(
        self,
        check_interval: int = 3600,
        max_concurrent: int = 2,
    ):
        self.check_interval = check_interval
        self.max_concurrent = max_concurrent
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def start(self):
        """Start the background worker."""
        if self._running:
            logger.warning("Subscription worker already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"Subscription worker started "
            f"(interval={self.check_interval}s, max_concurrent={self.max_concurrent})"
        )

    async def stop(self):
        """Stop the background worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Subscription worker stopped")

    async def _run_loop(self):
        """Main worker loop."""
        while self._running:
            try:
                await self._check_all_subscriptions()
            except Exception as e:
                logger.exception(f"Error in subscription worker: {e}")

            # Wait for next check interval
            try:
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break

    async def _check_all_subscriptions(self):
        """Check all enabled subscriptions for new content."""
        store = get_subscription_store()
        subscriptions = store.list_subscriptions(enabled_only=True)

        if not subscriptions:
            logger.debug("No enabled subscriptions to check")
            return

        logger.info(f"Checking {len(subscriptions)} subscriptions")

        for sub in subscriptions:
            if not self._running:
                break

            try:
                await self._check_subscription(sub, store)
            except Exception as e:
                logger.error(f"Error checking subscription {sub['id']}: {e}")

    async def _check_subscription(self, sub: dict, store: SubscriptionStore):
        """Check a single subscription for new content."""
        subscription_id = sub["id"]
        logger.debug(f"Checking subscription: {sub['name']} ({subscription_id})")

        try:
            # Fetch items from source
            fetcher = get_fetcher(sub["subscription_type"])
            items = await fetcher.fetch_items(
                source_url=sub["source_url"],
                source_id=sub.get("source_id"),
                limit=sub.get("download_limit", 10) * 2,
            )

            # Add new items to database
            new_items = []
            for item in items:
                existing = store.get_item_by_content_id(subscription_id, item.content_id)
                if not existing:
                    item_id = str(uuid.uuid4())
                    created = store.create_item(
                        item_id=item_id,
                        subscription_id=subscription_id,
                        content_id=item.content_id,
                        content_url=item.content_url,
                        title=item.title,
                        published_at=item.published_at,
                    )
                    if created:
                        new_items.append(created)

            # Update timestamps
            store.set_last_checked(subscription_id)

            if new_items:
                store.set_last_new_content(subscription_id)
                logger.info(
                    f"Found {len(new_items)} new items for subscription: {sub['name']}"
                )

                # Process new items
                await process_subscription_items(
                    subscription_id,
                    limit=sub.get("download_limit", 10),
                )

        except Exception as e:
            logger.error(f"Error checking subscription {subscription_id}: {e}")


async def process_subscription_items(
    subscription_id: str,
    limit: int = 10,
):
    """Process pending items for a subscription."""
    store = get_subscription_store()
    sub = store.get_subscription(subscription_id)

    if not sub:
        logger.error(f"Subscription not found: {subscription_id}")
        return

    # Get pending items
    pending_items = store.get_pending_items(subscription_id, limit=limit)

    if not pending_items:
        logger.debug(f"No pending items for subscription: {subscription_id}")
        return

    logger.info(f"Processing {len(pending_items)} items for subscription: {sub['name']}")

    # Process items
    for item in pending_items:
        try:
            await process_single_item(subscription_id, item["id"])
        except Exception as e:
            logger.error(f"Error processing item {item['id']}: {e}")

    # Cleanup old items if over limit
    await _cleanup_old_items(subscription_id, limit=sub.get("download_limit", 10))


async def process_single_item(subscription_id: str, item_id: str):
    """Process a single subscription item."""
    store = get_subscription_store()
    settings = get_settings()

    sub = store.get_subscription(subscription_id)
    item = store.get_item(item_id)

    if not sub or not item:
        logger.error(f"Subscription or item not found: {subscription_id}/{item_id}")
        return

    logger.info(f"Processing item: {item.get('title', item['content_id'])}")

    # Mark as downloading
    store.set_item_status(item_id, SubscriptionItemStatus.DOWNLOADING)

    try:
        # Determine output directory
        output_dir = sub.get("output_dir")
        if output_dir:
            download_dir = Path(output_dir)
        else:
            download_dir = Path(settings.download_dir) / "subscriptions" / subscription_id

        download_dir.mkdir(parents=True, exist_ok=True)

        content_url = item["content_url"]
        file_path = None

        # Check if this is a direct audio URL (RSS feeds) or a platform URL
        if _is_direct_audio_url(content_url):
            # Download directly via HTTP
            file_path = await _download_direct_audio(
                url=content_url,
                output_dir=download_dir,
                title=item.get("title"),
                output_format=sub.get("output_format", "m4a"),
            )
            if not file_path:
                store.set_item_status(
                    item_id,
                    SubscriptionItemStatus.FAILED,
                    error="Direct download failed",
                )
                logger.error(f"Direct download failed for item {item_id}")
                return
        else:
            # Use platform downloader
            try:
                downloader = DownloaderFactory.get_downloader(content_url)
            except Exception as e:
                store.set_item_status(
                    item_id,
                    SubscriptionItemStatus.FAILED,
                    error=f"No downloader found for URL: {content_url}",
                )
                logger.error(f"No downloader for item {item_id}: {e}")
                return

            result = await downloader.download(
                url=content_url,
                output_format=sub.get("output_format", "m4a"),
                quality=sub.get("quality", "high"),
            )

            if not result.success:
                store.set_item_status(
                    item_id,
                    SubscriptionItemStatus.FAILED,
                    error=result.error or "Download failed",
                )
                logger.error(f"Download failed for item {item_id}: {result.error}")
                return

            file_path = result.file_path

            # Move file to subscription output directory if different
            if file_path and file_path.parent != download_dir:
                import shutil
                new_path = download_dir / file_path.name
                shutil.move(str(file_path), str(new_path))
                file_path = new_path

        # Auto-transcribe if enabled
        transcription_path = None
        if sub.get("auto_transcribe"):
            transcription_path = await _transcribe_item(
                file_path,
                model=sub.get("transcribe_model", "base"),
                language=sub.get("transcribe_language"),
            )

        # Update item status
        store.set_item_status(
            item_id,
            SubscriptionItemStatus.COMPLETED,
            file_path=str(file_path) if file_path else None,
            transcription_path=str(transcription_path) if transcription_path else None,
        )

        # Increment download counter
        store.increment_total_downloaded(subscription_id)

        logger.info(f"Successfully processed item: {item.get('title', item['content_id'])}")

        # Send notification if webhook configured
        await _send_notification(sub, item, file_path, transcription_path)

    except Exception as e:
        logger.exception(f"Error processing item {item_id}: {e}")
        store.set_item_status(
            item_id,
            SubscriptionItemStatus.FAILED,
            error=str(e),
        )


async def _transcribe_item(
    audio_path: Path,
    model: str = "base",
    language: Optional[str] = None,
) -> Optional[Path]:
    """Transcribe an audio file."""
    try:
        from .transcriber import AudioTranscriber

        if not AudioTranscriber.is_available():
            logger.warning("Transcriber not available, skipping auto-transcription")
            return None

        transcriber = AudioTranscriber(model_size=model)
        result = await transcriber.transcribe(
            audio_path=audio_path,
            language=language,
            output_format="text",
        )

        if result.success and result.text:
            # Save transcription to file
            transcript_path = audio_path.with_suffix(".txt")
            transcript_path.write_text(result.text, encoding="utf-8")
            logger.info(f"Transcription saved to: {transcript_path}")
            return transcript_path

        return None

    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return None


async def _cleanup_old_items(subscription_id: str, limit: int):
    """Remove oldest completed items if over the download limit."""
    store = get_subscription_store()

    completed_count = store.count_items(subscription_id, SubscriptionItemStatus.COMPLETED)

    if completed_count <= limit:
        return

    # Get items to delete (oldest first)
    excess = completed_count - limit
    old_items = store.get_oldest_completed_items(subscription_id, excess)

    for item in old_items:
        # Delete files
        for path_field in ["file_path", "transcription_path"]:
            if item.get(path_field):
                try:
                    Path(item[path_field]).unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Failed to delete file: {e}")

        # Delete item from database
        store.delete_item(item["id"])
        logger.info(f"Cleaned up old item: {item.get('title', item['content_id'])}")


async def _send_notification(
    sub: dict,
    item: dict,
    file_path: Optional[Path],
    transcription_path: Optional[Path],
):
    """Send webhook notification for completed download."""
    settings = get_settings()
    webhook_url = settings.subscription_webhook_url

    if not webhook_url:
        return

    try:
        import httpx

        payload = {
            "event": "subscription_item_completed",
            "subscription_id": sub["id"],
            "subscription_name": sub["name"],
            "item_id": item["id"],
            "item_title": item.get("title"),
            "content_url": item["content_url"],
            "file_path": str(file_path) if file_path else None,
            "transcription_path": str(transcription_path) if transcription_path else None,
            "timestamp": datetime.utcnow().isoformat(),
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload, timeout=10.0)
            if resp.status_code >= 400:
                logger.warning(f"Webhook returned status {resp.status_code}")

    except Exception as e:
        logger.error(f"Failed to send webhook notification: {e}")


def get_subscription_worker() -> SubscriptionWorker:
    """Get or create the global subscription worker instance."""
    global _worker
    if _worker is None:
        settings = get_settings()
        _worker = SubscriptionWorker(
            check_interval=settings.subscription_check_interval,
            max_concurrent=settings.subscription_max_concurrent,
        )
    return _worker


async def start_subscription_worker():
    """Start the subscription worker."""
    settings = get_settings()
    if not settings.subscription_worker_enabled:
        logger.info("Subscription worker is disabled")
        return

    worker = get_subscription_worker()
    await worker.start()


async def stop_subscription_worker():
    """Stop the subscription worker."""
    global _worker
    if _worker:
        await _worker.stop()
        _worker = None
