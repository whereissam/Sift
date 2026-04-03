"""Model management routes for desktop app — download/check Whisper models."""

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .auth import verify_api_key

router = APIRouter(prefix="/api/models", tags=["models"], dependencies=[Depends(verify_api_key)])

# Default model storage location (inside user data dir)
MODELS_DIR = Path.home() / ".sift" / "models"

WHISPER_MODELS = {
    "tiny": {"size_mb": 75, "description": "Fastest, lowest accuracy"},
    "base": {"size_mb": 142, "description": "Fast, good for clear audio"},
    "small": {"size_mb": 466, "description": "Balanced speed/accuracy"},
    "medium": {"size_mb": 1500, "description": "High accuracy, slower"},
    "large-v3": {"size_mb": 3100, "description": "Best accuracy, requires ~4GB RAM"},
}


class ModelStatus(BaseModel):
    name: str
    downloaded: bool
    size_mb: int
    description: str
    path: str | None = None


class DownloadRequest(BaseModel):
    model_name: str = "base"


class DownloadProgress(BaseModel):
    model_name: str
    status: str  # "downloading", "completed", "error"
    progress: float  # 0.0 - 1.0
    message: str = ""


@router.get("/whisper", response_model=list[ModelStatus])
async def list_whisper_models():
    """List available Whisper models and their download status."""
    result = []
    for name, info in WHISPER_MODELS.items():
        model_dir = MODELS_DIR / "whisper" / name
        downloaded = model_dir.exists() and any(model_dir.iterdir()) if model_dir.exists() else False
        result.append(ModelStatus(
            name=name,
            downloaded=downloaded,
            size_mb=info["size_mb"],
            description=info["description"],
            path=str(model_dir) if downloaded else None,
        ))
    return result


@router.post("/whisper/download")
async def download_whisper_model(req: DownloadRequest):
    """Download a Whisper model. Returns immediately; check progress via SSE."""
    if req.model_name not in WHISPER_MODELS:
        return {"error": f"Unknown model: {req.model_name}", "available": list(WHISPER_MODELS.keys())}

    model_dir = MODELS_DIR / "whisper" / req.model_name
    if model_dir.exists() and any(model_dir.iterdir()):
        return {"status": "already_downloaded", "path": str(model_dir)}

    # Use faster-whisper's download mechanism
    try:
        from faster_whisper import WhisperModel
        model_dir.mkdir(parents=True, exist_ok=True)

        # This downloads the model to the HuggingFace cache; we just need to trigger it
        _ = WhisperModel(
            req.model_name,
            device="cpu",
            compute_type="int8",
            download_root=str(MODELS_DIR / "whisper"),
        )
        return {"status": "completed", "path": str(model_dir)}
    except ImportError:
        return {"status": "error", "message": "faster-whisper not installed. Install with: uv sync --extra transcribe"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/whisper/check")
async def check_model_ready():
    """Quick check if any Whisper model is ready for use."""
    for name in WHISPER_MODELS:
        model_dir = MODELS_DIR / "whisper" / name
        if model_dir.exists() and any(model_dir.iterdir()):
            return {"ready": True, "model": name, "path": str(model_dir)}
    return {"ready": False, "model": None}
