"""WebSocket API routes for real-time transcription."""

import base64
import logging
from typing import Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .auth import verify_api_key
from ..core.realtime_transcriber import RealtimeTranscriptionSession, TranscriptPolisher
from ..core.transcriber import WhisperModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"], dependencies=[Depends(verify_api_key)])


class TranscriptionConfig(BaseModel):
    """Configuration for a realtime transcription session."""

    model: str = "base"
    language: Optional[str] = None
    min_chunk_duration: float = 3.0  # Seconds of audio before processing
    use_context: bool = True  # Use recent transcript as context
    llm_polish: bool = False  # Enable LLM post-processing


@router.get("/transcribe/live/status")
async def live_transcription_status():
    """Check if live transcription is available and LLM polishing is configured."""
    polisher = TranscriptPolisher()
    return {
        "available": True,
        "llm_polish_available": polisher.is_available(),
    }


@router.websocket("/transcribe/live")
async def live_transcription(websocket: WebSocket):
    """
    WebSocket endpoint for real-time audio transcription.

    Protocol:
    ---------
    Client -> Server:
        {"type": "start", "config": {"model": "base", "language": null, "llm_polish": false}}
        {"type": "audio", "data": "<base64-webm-opus>"}
        {"type": "stop"}

    Server -> Client:
        {"type": "connected", "llm_polish_available": true}
        {"type": "language_detected", "language": "en", "probability": 0.98}
        {"type": "partial", "text": "Hello wor"}
        {"type": "segment", "segment": {"start": 0.0, "end": 2.5, "text": "Hello world."}}
        {"type": "complete", "full_text": "...", "segments": [...], "language": "en", "llm_polished": false}
        {"type": "error", "error": "...", "recoverable": true}
    """
    await websocket.accept()
    session: Optional[RealtimeTranscriptionSession] = None

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "start":
                # Initialize new session
                config = data.get("config", {})
                model = config.get("model", "base")

                # Validate model against allowed models
                valid_models = {m.value for m in WhisperModel}
                if model not in valid_models:
                    await websocket.send_json({
                        "type": "error",
                        "error": f"Invalid model '{model}'. Valid: {', '.join(sorted(valid_models))}",
                        "recoverable": False,
                    })
                    continue

                language = config.get("language")
                min_chunk = config.get("min_chunk_duration", 3.0)
                use_context = config.get("use_context", True)
                llm_polish = config.get("llm_polish", False)

                logger.info(
                    f"Starting realtime transcription: model={model}, "
                    f"language={language}, llm_polish={llm_polish}"
                )

                session = RealtimeTranscriptionSession(
                    model_size=model,
                    language=language,
                    min_chunk_duration=min_chunk,
                    use_context_prompt=use_context,
                    enable_llm_polish=llm_polish,
                )

                # Check LLM availability
                polisher = TranscriptPolisher()
                llm_available = polisher.is_available()

                await websocket.send_json({
                    "type": "connected",
                    "message": "Realtime transcription session started",
                    "llm_polish_available": llm_available,
                    "llm_polish_enabled": llm_polish and llm_available,
                })

            elif msg_type == "audio" and session:
                # Process audio chunk
                audio_data = data.get("data")
                if not audio_data:
                    continue

                try:
                    # Decode base64 audio
                    audio_bytes = base64.b64decode(audio_data)

                    # Process and stream results
                    async for result in session.process_audio_chunk(audio_bytes):
                        await websocket.send_json(result)

                except Exception as e:
                    logger.error(f"Error processing audio chunk: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "error": str(e),
                        "recoverable": True,
                    })

            elif msg_type == "stop" and session:
                # Finalize session and return complete result
                logger.info("Stopping realtime transcription session")

                try:
                    result = await session.finalize()
                    await websocket.send_json({
                        "type": "complete",
                        **result,
                    })
                except Exception as e:
                    logger.error(f"Error finalizing session: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "error": str(e),
                        "recoverable": False,
                    })

                break

            elif msg_type == "ping":
                # Keep-alive ping
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "error": str(e),
                "recoverable": False,
            })
        except Exception:
            pass
    finally:
        if session:
            session.cleanup()
            logger.info("Cleaned up transcription session")
