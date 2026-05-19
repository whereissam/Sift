"""Two-phase workflow for download, convert, and transcribe."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .job_store import JobStore, JobStatus, JobType, get_job_store
from .downloader import DownloaderFactory
from .converter import AudioConverter
from .base import AudioMetadata, Platform

logger = logging.getLogger(__name__)


class WorkflowProcessor:
    """Handles two-phase download/convert/transcribe workflows."""

    def __init__(self, job_store: Optional[JobStore] = None):
        self.job_store = job_store or get_job_store()

    async def process_download(
        self,
        job_id: str,
        url: str,
        platform: str,
        output_format: str = "m4a",
        quality: str = "high",
    ) -> dict:
        """
        Two-phase download workflow:
        1. Download raw file
        2. Convert to target format (keeps original until done)
        """
        job = self.job_store.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        try:
            # Phase 1: Download
            if job["status"] in [JobStatus.PENDING.value, JobStatus.DOWNLOADING.value]:
                await self._phase_download(job_id, url, platform)
                job = self.job_store.get_job(job_id)

            # Phase 2: Convert (if needed)
            if job["status"] == JobStatus.CONVERTING.value:
                await self._phase_convert(job_id, output_format, quality)
                job = self.job_store.get_job(job_id)

            return job

        except Exception as e:
            logger.exception(f"Workflow error for job {job_id}")
            self.job_store.set_status(job_id, JobStatus.FAILED, error=str(e))
            raise

    async def _phase_download(self, job_id: str, url: str, platform: str):
        """Phase 1: Download raw file."""
        logger.info(f"[{job_id}] Phase 1: Downloading from {platform}")
        self.job_store.set_status(job_id, JobStatus.DOWNLOADING, progress=0.1)

        try:
            downloader = DownloaderFactory.get_downloader(url)

            # Download to raw format (don't convert yet)
            result = await downloader.download(
                url=url,
                output_format="m4a",  # Keep original format
                quality="high",
            )

            if not result.success:
                raise Exception(result.error or "Download failed")

            # Save raw file path and content info (including fields for metadata tagging)
            self.job_store.update_job(
                job_id,
                raw_file_path=str(result.file_path),
                content_info={
                    "title": result.metadata.title if result.metadata else "Unknown",
                    "creator_name": result.metadata.creator_name if result.metadata else None,
                    "creator_username": result.metadata.creator_username if result.metadata else None,
                    "duration_seconds": result.metadata.duration_seconds if result.metadata else None,
                    "platform": platform,
                    # Additional fields for metadata tagging
                    "artwork_url": result.metadata.artwork_url if result.metadata else None,
                    "show_name": result.metadata.show_name if result.metadata else None,
                    "description": result.metadata.description if result.metadata else None,
                    "published_at": result.metadata.published_at.isoformat() if result.metadata and result.metadata.published_at else None,
                    "content_id": result.metadata.content_id if result.metadata else None,
                },
                status=JobStatus.CONVERTING.value,
                progress=0.5,
            )

            logger.info(f"[{job_id}] Download complete: {result.file_path}")

        except Exception as e:
            logger.error(f"[{job_id}] Download failed: {e}")
            raise

    async def _phase_convert(self, job_id: str, output_format: str, quality: str):
        """Phase 2: Convert to target format."""
        job = self.job_store.get_job(job_id)
        raw_path = Path(job["raw_file_path"])

        if not raw_path.exists():
            raise FileNotFoundError(f"Raw file not found: {raw_path}")

        logger.info(f"[{job_id}] Phase 2: Converting to {output_format}")

        try:
            # Skip conversion if already in target format
            if raw_path.suffix.lower() == f".{output_format}":
                converted_path = raw_path
                logger.info(f"[{job_id}] Already in target format, skipping conversion")
            else:
                converter = AudioConverter()
                converted_path = await converter.convert(
                    input_path=raw_path,
                    output_format=output_format,
                    quality=quality,
                )

            # Embed metadata tags if content info is available
            content_info = job.get("content_info", {})
            embed_metadata = job.get("embed_metadata", True)

            if embed_metadata and content_info:
                await self._embed_metadata(converted_path, content_info)

            # Calculate file size
            file_size_mb = converted_path.stat().st_size / (1024 * 1024)

            # Update job with converted file path
            self.job_store.update_job(
                job_id,
                converted_file_path=str(converted_path),
                file_size_mb=file_size_mb,
            )

            # Mark as completed
            self.job_store.set_status(job_id, JobStatus.COMPLETED)

            # Clean up raw file if different from converted
            if raw_path != converted_path and raw_path.exists():
                raw_path.unlink()
                logger.info(f"[{job_id}] Cleaned up raw file")

            logger.info(f"[{job_id}] Conversion complete: {converted_path}")

        except Exception as e:
            logger.error(f"[{job_id}] Conversion failed: {e}")
            # Keep raw file for retry
            raise

    async def _embed_metadata(self, file_path: Path, content_info: dict):
        """Embed metadata tags into the audio file."""
        from .metadata_tagger import MetadataTagger

        # Build AudioMetadata from content_info
        platform_str = content_info.get("platform", "")
        try:
            platform = Platform(platform_str)
        except ValueError:
            platform = Platform.YOUTUBE  # Default fallback

        # Parse published_at if it's a string
        published_at = None
        if content_info.get("published_at"):
            try:
                published_at = datetime.fromisoformat(content_info["published_at"])
            except (ValueError, TypeError):
                pass

        metadata = AudioMetadata(
            platform=platform,
            content_id=content_info.get("content_id", "unknown"),
            title=content_info.get("title", "Unknown"),
            creator_name=content_info.get("creator_name"),
            creator_username=content_info.get("creator_username"),
            duration_seconds=content_info.get("duration_seconds"),
            description=content_info.get("description"),
            artwork_url=content_info.get("artwork_url"),
            published_at=published_at,
            show_name=content_info.get("show_name"),
        )

        tagger = MetadataTagger()
        success = await tagger.tag_file(file_path, metadata)
        if success:
            logger.info(f"Embedded metadata tags into {file_path.name}")
        else:
            logger.warning(f"Failed to embed metadata into {file_path.name}")

    async def process_transcription(
        self,
        job_id: str,
        audio_path: Path,
        model_size: str = "base",
        language: Optional[str] = None,
        output_format: str = "text",
        translate: bool = False,
        diarize: bool = False,
        num_speakers: Optional[int] = None,
    ) -> dict:
        """
        Transcription workflow with checkpointing and optional diarization.

        Args:
            job_id: Job identifier
            audio_path: Path to audio file
            model_size: Whisper model size
            language: Language code (auto-detect if None)
            output_format: Output format (text, srt, vtt, json, dialogue)
            translate: Translate to English
            diarize: Enable speaker diarization
            num_speakers: Exact number of speakers (if known)
        """
        from .transcriber import AudioTranscriber, TranscriptionSegment

        job = self.job_store.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        logger.info(f"[{job_id}] Starting transcription: {audio_path.name}")
        self.job_store.set_status(job_id, JobStatus.TRANSCRIBING, progress=0.1)

        try:
            transcriber = AudioTranscriber(model_size=model_size)
            task = "translate" if translate else "transcribe"

            result = await transcriber.transcribe(
                audio_path=audio_path,
                language=language,
                task=task,
                vad_filter=True,
                job_id=job_id,
                output_format=output_format,
            )

            if not result.success:
                raise Exception(result.error or "Transcription failed")

            segments = result.segments

            # Run diarization if requested
            if diarize:
                try:
                    from .diarizer import SpeakerDiarizer

                    if SpeakerDiarizer.is_available():
                        logger.info(f"[{job_id}] Running speaker diarization...")
                        diarizer = SpeakerDiarizer()
                        speaker_segments = await diarizer.diarize(
                            audio_path,
                            num_speakers=num_speakers,
                        )

                        # Assign speakers to transcription segments
                        diarized = diarizer.assign_speakers_to_segments(
                            segments, speaker_segments
                        )

                        # Convert back to TranscriptionSegment with speaker labels
                        segments = [
                            TranscriptionSegment(
                                start=d.start,
                                end=d.end,
                                text=d.text,
                                speaker=d.speaker,
                            )
                            for d in diarized
                        ]
                        logger.info(f"[{job_id}] Diarization complete")
                    else:
                        logger.warning(
                            f"[{job_id}] Diarization requested but pyannote not available"
                        )
                except Exception as e:
                    logger.error(f"[{job_id}] Diarization failed: {e}")
                    # Continue without diarization

            # Format output
            if output_format == "srt":
                if diarize and any(s.speaker for s in segments):
                    formatted = transcriber.format_as_srt_with_speakers(segments)
                else:
                    formatted = transcriber.format_as_srt(segments)
            elif output_format == "vtt":
                formatted = transcriber.format_as_vtt(segments)
            elif output_format == "dialogue":
                formatted = transcriber.format_as_dialogue(segments)
            else:
                formatted = result.text

            # Save results
            self.job_store.update_job(
                job_id,
                transcription_result={
                    "text": result.text,
                    "language": result.language,
                    "language_probability": result.language_probability,
                    "duration_seconds": result.duration,
                    "segments": [
                        {
                            "start": s.start,
                            "end": s.end,
                            "text": s.text,
                            "speaker": s.speaker,
                        }
                        for s in segments
                    ],
                    "formatted_output": formatted,
                    "output_format": output_format,
                    "diarized": diarize and any(s.speaker for s in segments),
                },
            )

            self.job_store.set_status(job_id, JobStatus.COMPLETED)
            logger.info(f"[{job_id}] Transcription complete")

            return self.job_store.get_job(job_id)

        except Exception as e:
            logger.error(f"[{job_id}] Transcription failed: {e}")
            self.job_store.set_status(job_id, JobStatus.FAILED, error=str(e))
            raise

    async def retry_job(self, job_id: str) -> dict:
        """Retry a failed or interrupted job from its last successful phase."""
        job = self.job_store.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        status = job["status"]
        job_type = job["job_type"]

        logger.info(f"[{job_id}] Retrying job (status: {status}, type: {job_type})")

        if job_type == JobType.DOWNLOAD.value:
            # Determine which phase to resume from
            if job.get("raw_file_path") and Path(job["raw_file_path"]).exists():
                # Raw file exists, resume from conversion
                self.job_store.set_status(job_id, JobStatus.CONVERTING)
                return await self.process_download(
                    job_id=job_id,
                    url=job["source_url"],
                    platform=job["platform"],
                    output_format=job["output_format"],
                    quality=job["quality"],
                )
            else:
                # Need to re-download
                self.job_store.set_status(job_id, JobStatus.DOWNLOADING)
                return await self.process_download(
                    job_id=job_id,
                    url=job["source_url"],
                    platform=job["platform"],
                    output_format=job["output_format"],
                    quality=job["quality"],
                )

        elif job_type == JobType.TRANSCRIBE.value:
            # Resume transcription (checkpoints handled by transcriber)
            audio_path = Path(job.get("raw_file_path") or job.get("converted_file_path", ""))
            if not audio_path.exists():
                raise FileNotFoundError(f"Audio file not found: {audio_path}")

            self.job_store.set_status(job_id, JobStatus.TRANSCRIBING)
            return await self.process_transcription(
                job_id=job_id,
                audio_path=audio_path,
                model_size=job.get("model_size", "base"),
                language=job.get("language"),
                output_format=job.get("transcription_format", "text"),
            )

        else:
            raise ValueError(f"Unknown job type: {job_type}")


async def recover_unfinished_jobs():
    """Recover and resume all unfinished jobs on startup."""
    job_store = get_job_store()
    processor = WorkflowProcessor(job_store)

    unfinished = job_store.get_unfinished_jobs()
    if not unfinished:
        logger.info("No unfinished jobs to recover")
        return

    logger.info(f"Found {len(unfinished)} unfinished jobs to recover")

    for job in unfinished:
        job_id = job["job_id"]
        try:
            logger.info(f"Recovering job {job_id} (status: {job['status']})")
            await processor.retry_job(job_id)
        except Exception as e:
            logger.error(f"Failed to recover job {job_id}: {e}")
            job_store.set_status(job_id, JobStatus.FAILED, error=f"Recovery failed: {e}")
