"""Ingestion service: executes /v1/ingestions jobs (migration Slice 3).

One ingestion job flows through the store's real stage statuses
(downloading → converting/transcribing → completed) on a single job row.
The service reads everything it needs from the job row itself
(source_url, requested_outputs, processing settings), so a restart can
re-drive the job without in-memory context.
"""

import logging
from enum import Enum
from typing import Optional

from sift_core.fetch.downloader import DownloaderFactory
from ..store import JobStatus, get_job_store
from .workflow import WorkflowProcessor

logger = logging.getLogger(__name__)

# Outputs the /v1 API accepts today. "claims" rides on the existing
# knowledge auto-extract pipeline after transcription completes.
ALLOWED_OUTPUTS = ("media", "transcript", "speakers", "claims")


def _safe_metadata_dict(metadata) -> Optional[dict]:
    """AudioMetadata carries enum fields; make it JSON-serializable."""
    if metadata is None:
        return None
    out = {}
    for key, value in vars(metadata).items():
        out[key] = value.value if isinstance(value, Enum) else value
    return out


def find_cached_transcript(store, source, outputs) -> Optional[str]:
    """Return the asset_id when the canonical source already has a
    transcript artifact satisfying the requested outputs."""
    if source is None or "transcript" not in outputs and "speakers" not in outputs:
        return None
    asset = store.get_asset_by_fingerprint(source.fingerprint)
    if not asset:
        return None
    artifact = store.get_latest_transcript_artifact(asset["asset_id"])
    if not artifact:
        return None
    if "speakers" in outputs and not artifact["diarization_enabled"]:
        return None
    return asset["asset_id"]


async def run_ingestion_job(job_id: str) -> None:
    """Background runner for one ingestion job. Terminal states only —
    every failure path lands in status=failed with an error message."""
    store = get_job_store()
    job = store.get_job(job_id)
    if not job:
        logger.error(f"[{job_id}] Ingestion job vanished before start")
        return

    outputs = job.get("requested_outputs") or ["transcript"]
    url = job.get("source_url")
    processor = WorkflowProcessor(store)

    try:
        want_transcript = "transcript" in outputs or "speakers" in outputs

        if not want_transcript:
            # Media-only: the existing two-phase download/convert workflow.
            await processor.process_download(
                job_id,
                url,
                job.get("platform") or "auto",
                output_format=job.get("output_format") or "m4a",
                quality=job.get("quality") or "high",
            )
            return

        # Transcript path: acquire raw audio, then run the transcription
        # workflow (which handles diarization, blob + artifact dual-write,
        # and knowledge enqueue for "claims").
        store.set_status(job_id, JobStatus.DOWNLOADING, progress=0.05)
        downloader = DownloaderFactory.get_downloader(url)
        result = await downloader.download(
            url=url, output_format="m4a", quality="high"
        )
        if not result.success or not result.file_path:
            raise RuntimeError(result.error or "Download failed")

        store.update_job(
            job_id,
            raw_file_path=str(result.file_path),
            content_info=_safe_metadata_dict(result.metadata),
        )

        await processor.process_transcription(
            job_id,
            result.file_path,
            model_size=job.get("model_size") or "base",
            language=job.get("language"),
            output_format=job.get("transcription_format") or "json",
            diarize="speakers" in outputs,
        )

    except Exception as e:
        logger.exception(f"[{job_id}] Ingestion failed")
        # process_* already set FAILED on their own paths; this covers
        # acquisition errors and keeps the terminal-state guarantee.
        current = store.get_job(job_id)
        if current and current["status"] != JobStatus.FAILED.value:
            store.set_status(job_id, JobStatus.FAILED, error=str(e))
