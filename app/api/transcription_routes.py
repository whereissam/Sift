"""Transcription API routes."""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
import aiofiles

from .auth import verify_api_key
from .schemas import (
    DownloadJob,
    JobStatus,
    TranscribeRequest,
    TranscriptionJob,
    TranscriptionSegment as TranscriptionSegmentSchema,
    TranscriptionOutputFormat,
)
from ..core.downloader import DownloaderFactory

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])

# Import shared stores
from .transcription_store import transcription_jobs
from .download_routes import jobs as download_jobs


async def _process_transcription(job_id: str, request: TranscribeRequest, audio_path: Path):
    """Background task to process transcription with checkpoint and diarization support."""
    from ..core.transcriber import AudioTranscriber, TranscriptionSegment

    job = transcription_jobs[job_id]
    job.status = JobStatus.PROCESSING
    job.progress = 0.1

    enhanced_path = None  # Track enhanced file for cleanup/keeping
    original_audio_path = audio_path  # Track original for cleanup

    try:
        # Apply audio enhancement if requested
        enhance = getattr(request, 'enhance', False)
        if enhance:
            from ..core.enhancer import AudioEnhancer, EnhancementPreset as CoreEnhancementPreset

            enhancer = AudioEnhancer()
            preset_value = getattr(request, 'enhancement_preset', 'medium')
            if hasattr(preset_value, 'value'):
                preset_value = preset_value.value
            preset = CoreEnhancementPreset(preset_value)

            logger.info(f"[{job_id}] Applying {preset.value} audio enhancement...")
            result = await enhancer.enhance(audio_path, preset, keep_original=True)

            if result.success and result.enhanced_path:
                logger.info(f"[{job_id}] Audio enhancement complete: {result.enhanced_path}")
                enhanced_path = result.enhanced_path
                audio_path = result.enhanced_path
            else:
                logger.warning(f"[{job_id}] Audio enhancement failed: {result.error}, continuing with original audio")

        transcriber = AudioTranscriber(model_size=request.model.value)

        task = "translate" if request.translate else "transcribe"
        result = await transcriber.transcribe(
            audio_path=audio_path,
            language=request.language,
            task=task,
            vad_filter=True,
            job_id=job_id,  # Enable checkpointing
            output_format=request.output_format.value,
        )

        if result.success:
            segments = result.segments or []

            # Run diarization if requested
            diarize = getattr(request, 'diarize', False)
            num_speakers = getattr(request, 'num_speakers', None)

            if diarize:
                try:
                    from ..core.diarizer import SpeakerDiarizer

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

            job.text = result.text
            job.segments = [
                TranscriptionSegmentSchema(
                    start=seg.start,
                    end=seg.end,
                    text=seg.text,
                    speaker=seg.speaker,
                )
                for seg in segments
            ]
            job.language = result.language
            job.language_probability = result.language_probability
            job.duration_seconds = result.duration

            # Format output based on requested format
            has_speakers = diarize and any(s.speaker for s in segments)

            if request.output_format == TranscriptionOutputFormat.SRT:
                if has_speakers:
                    job.formatted_output = transcriber.format_as_srt_with_speakers(segments)
                else:
                    job.formatted_output = transcriber.format_as_srt(segments)
            elif request.output_format == TranscriptionOutputFormat.VTT:
                job.formatted_output = transcriber.format_as_vtt(segments)
            elif request.output_format == TranscriptionOutputFormat.JSON:
                job.formatted_output = json.dumps({
                    "text": result.text,
                    "language": result.language,
                    "segments": [
                        {
                            "start": s.start,
                            "end": s.end,
                            "text": s.text,
                            "speaker": s.speaker,
                        }
                        for s in segments
                    ],
                    "diarized": has_speakers,
                }, ensure_ascii=False, indent=2)
            elif request.output_format == TranscriptionOutputFormat.DIALOGUE:
                job.formatted_output = transcriber.format_as_dialogue(segments)
            else:
                job.formatted_output = result.text

            job.output_format = request.output_format

            # Save transcription to file if save_to is specified
            save_to = getattr(request, 'save_to', None)
            if save_to and job.formatted_output:
                try:
                    output_path = Path(save_to).resolve()
                    # Prevent path traversal: must be within download_dir
                    from ..config import get_settings as _get_settings
                    _base_dir = Path(_get_settings().download_dir).resolve()
                    if not str(output_path).startswith(str(_base_dir) + "/") and output_path != _base_dir:
                        raise ValueError(f"save_to must be within the download directory: {_base_dir}")
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(job.formatted_output, encoding='utf-8')
                    job.output_file = str(output_path)
                    logger.info(f"[{job_id}] Saved transcription to {output_path}")
                except Exception as e:
                    logger.error(f"[{job_id}] Failed to save transcription: {e}")

            # Handle enhanced audio file based on keep_enhanced
            keep_enhanced = getattr(request, 'keep_enhanced', False)
            if enhanced_path and enhanced_path.exists():
                if keep_enhanced:
                    job.enhanced_file = str(enhanced_path)
                    logger.info(f"[{job_id}] Keeping enhanced audio: {enhanced_path}")
                else:
                    try:
                        enhanced_path.unlink()
                        logger.info(f"[{job_id}] Deleted enhanced audio file")
                    except Exception as e:
                        logger.warning(f"[{job_id}] Failed to delete enhanced audio: {e}")

            # Handle original audio file based on keep_audio
            keep_audio = getattr(request, 'keep_audio', False)
            if keep_audio:
                job.audio_file = str(original_audio_path)
            else:
                # Delete temp original audio file
                try:
                    if original_audio_path.exists():
                        original_audio_path.unlink()
                        logger.info(f"[{job_id}] Deleted temp audio file")
                except Exception as e:
                    logger.warning(f"[{job_id}] Failed to delete temp audio: {e}")

            job.status = JobStatus.COMPLETED
            job.progress = 1.0
            job.completed_at = datetime.utcnow()
        else:
            job.status = JobStatus.FAILED
            job.error = result.error or "Transcription failed"

    except Exception as e:
        logger.exception(f"Transcription error for job {job_id}")
        job.status = JobStatus.FAILED
        job.error = str(e) if str(e) else "Transcription failed"


@router.post("/transcribe", response_model=TranscriptionJob)
async def start_transcription(
    request: TranscribeRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start a transcription job.

    You can either:
    - Provide a URL to download and transcribe
    - Provide a job_id of a completed download to transcribe

    Supports the same platforms as download (X Spaces, YouTube, Podcasts, etc.)
    """
    # Validate request
    if not request.url and not request.job_id:
        raise HTTPException(
            status_code=400,
            detail="Either 'url' or 'job_id' must be provided",
        )

    audio_path = None
    source_url = request.url
    source_job_id = request.job_id

    # If job_id is provided, get the file from the completed download
    if request.job_id:
        if request.job_id not in download_jobs:
            raise HTTPException(status_code=404, detail="Download job not found")

        download_job = download_jobs[request.job_id]
        if download_job.status != JobStatus.COMPLETED:
            raise HTTPException(
                status_code=400,
                detail=f"Download job not completed (status: {download_job.status.value})",
            )

        file_path = getattr(download_job, "_file_path", None)
        if not file_path or not Path(file_path).exists():
            raise HTTPException(status_code=404, detail="Downloaded file not found")

        audio_path = Path(file_path)
        source_job_id = request.job_id

    # If URL is provided, we need to download first
    elif request.url:
        detected_platform = DownloaderFactory.detect_platform(request.url)
        if not detected_platform:
            raise HTTPException(
                status_code=400,
                detail="Unsupported URL for transcription",
            )

        # Download the audio first
        downloader = DownloaderFactory.get_downloader(request.url)
        result = await downloader.download(
            url=request.url,
            output_format="m4a",
            quality="high",
        )

        if not result.success or not result.file_path:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to download audio: {result.error}",
            )

        audio_path = result.file_path
        source_url = request.url

    # Create transcription job
    job_id = str(uuid.uuid4())
    job = TranscriptionJob(
        job_id=job_id,
        status=JobStatus.PENDING,
        progress=0.0,
        source_url=source_url,
        source_job_id=source_job_id,
        created_at=datetime.utcnow(),
    )
    transcription_jobs[job_id] = job

    # Start background transcription
    background_tasks.add_task(_process_transcription, job_id, request, audio_path)

    return job


@router.get("/transcribe/resumable")
async def list_resumable_transcriptions():
    """List all transcription jobs that can be resumed."""
    from ..core.transcriber import AudioTranscriber

    transcriber = AudioTranscriber()
    jobs = transcriber.get_resumable_jobs()
    return {"resumable_jobs": jobs}


@router.get("/transcribe/{job_id}", response_model=TranscriptionJob)
async def get_transcription_status(job_id: str):
    """Get the status of a transcription job."""
    if job_id not in transcription_jobs:
        raise HTTPException(status_code=404, detail="Transcription job not found")
    return transcription_jobs[job_id]


@router.delete("/transcribe/{job_id}")
async def cancel_transcription(job_id: str):
    """Cancel and remove a transcription job."""
    if job_id not in transcription_jobs:
        raise HTTPException(status_code=404, detail="Transcription job not found")

    del transcription_jobs[job_id]
    return {"status": "deleted", "job_id": job_id}


@router.post("/transcribe/{job_id}/resume", response_model=TranscriptionJob)
async def resume_transcription(
    job_id: str,
    background_tasks: BackgroundTasks,
):
    """Resume a previously interrupted transcription job."""
    from ..core.checkpoint import CheckpointManager

    checkpoint_manager = CheckpointManager()
    checkpoint = checkpoint_manager.load(job_id)

    if not checkpoint:
        raise HTTPException(
            status_code=404,
            detail=f"No checkpoint found for job {job_id}",
        )

    audio_path = Path(checkpoint.audio_path)
    if not audio_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Audio file no longer exists: {checkpoint.audio_path}",
        )

    # Create or update job in memory
    job = TranscriptionJob(
        job_id=job_id,
        status=JobStatus.PENDING,
        progress=checkpoint.last_end_time / checkpoint.total_duration if checkpoint.total_duration else 0,
        source_url=f"resume://{audio_path.name}",
        created_at=datetime.fromisoformat(checkpoint.created_at),
    )
    transcription_jobs[job_id] = job

    # Create mock request from checkpoint
    class ResumeTranscribeRequest:
        def __init__(self):
            self.model = type("Model", (), {"value": checkpoint.model_size})()
            self.output_format = type("Format", (), {"value": checkpoint.output_format})()
            self.language = checkpoint.language
            self.translate = checkpoint.task == "translate"

    request = ResumeTranscribeRequest()

    # Start background transcription (will resume from checkpoint)
    background_tasks.add_task(_process_transcription, job_id, request, audio_path)

    return job


@router.post("/transcribe/upload", response_model=TranscriptionJob)
async def transcribe_uploaded_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    model: str = Form(default="base"),
    output_format: str = Form(default="text"),
    language: str = Form(default=None),
    diarize: str = Form(default="false"),
    num_speakers: str = Form(default=None),
    enhance: str = Form(default="false"),
    enhancement_preset: str = Form(default="medium"),
    keep_enhanced: str = Form(default="false"),
):
    """
    Transcribe an uploaded audio file.

    Supports: mp3, m4a, wav, mp4, webm, ogg, flac
    """
    from ..config import get_settings

    settings = get_settings()

    # Validate file extension - use only the filename, strip any directory components
    allowed_extensions = {".mp3", ".m4a", ".wav", ".mp4", ".webm", ".ogg", ".flac", ".aac"}
    safe_filename = Path(file.filename).name if file.filename else ""
    file_ext = Path(safe_filename).suffix.lower()

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}",
        )

    # Save uploaded file with size limit (500MB)
    MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500MB
    upload_dir = Path(settings.download_dir) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_id = str(uuid.uuid4())
    file_path = upload_dir / f"{file_id}{file_ext}"

    total_size = 0
    async with aiofiles.open(file_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):  # Read in 1MB chunks
            total_size += len(chunk)
            if total_size > MAX_UPLOAD_SIZE:
                await f.close()
                file_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum size: {MAX_UPLOAD_SIZE // (1024*1024)}MB",
                )
            await f.write(chunk)

    # Create transcription job
    job_id = str(uuid.uuid4())

    # Map form values to schema enums
    from .schemas import TranscriptionOutputFormat, WhisperModelSize

    try:
        output_format_enum = TranscriptionOutputFormat(output_format)
    except ValueError:
        output_format_enum = TranscriptionOutputFormat.TEXT

    job = TranscriptionJob(
        job_id=job_id,
        status=JobStatus.PENDING,
        progress=0.0,
        source_url=f"upload://{file.filename}",
        created_at=datetime.utcnow(),
    )
    transcription_jobs[job_id] = job

    # Create a mock request object for the background task
    class UploadTranscribeRequest:
        def __init__(self):
            self.model = WhisperModelSize(model) if model in [e.value for e in WhisperModelSize] else WhisperModelSize.BASE
            self.output_format = output_format_enum
            self.language = language if language else None
            self.translate = False
            self.diarize = diarize.lower() == "true"
            self.num_speakers = int(num_speakers) if num_speakers and num_speakers.isdigit() else None
            self.enhance = enhance.lower() == "true"
            self.enhancement_preset = enhancement_preset
            self.keep_enhanced = keep_enhanced.lower() == "true"

    request = UploadTranscribeRequest()

    # Start background transcription
    background_tasks.add_task(_process_transcription, job_id, request, file_path)

    return job
