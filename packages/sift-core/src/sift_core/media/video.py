"""Audio-to-video (YouTube-ready MP4) creation using FFmpeg."""

import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from ..exceptions import FFmpegError

logger = logging.getLogger(__name__)

RESOLUTIONS: dict[str, tuple[int, int]] = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}

BACKGROUND_COLOR = "0x0f0f14"

# stderr fragments that indicate the AAC stream cannot be copied into MP4.
_COPY_MUX_ERROR_MARKERS = (
    "could not find tag",
    "not currently supported in container",
    "could not write header",
    "muxer does not support",
    "invalid data found",
)


def _default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}.youtube.mp4")


def _resolution_dims(resolution: str) -> tuple[int, int]:
    try:
        return RESOLUTIONS[resolution]
    except KeyError:
        raise FFmpegError(
            f"Unsupported resolution: {resolution}. "
            f"Choose from {', '.join(RESOLUTIONS)}"
        )


class AudioToVideo:
    """Create a YouTube-ready MP4 from an audio file using FFmpeg."""

    def __init__(self) -> None:
        self._ffmpeg = self._find("ffmpeg")
        self._ffprobe = self._find("ffprobe")

    @staticmethod
    def _find(name: str) -> str:
        path = shutil.which(name)
        if not path:
            raise FFmpegError(
                f"{name} not found in PATH. Please install it: brew install ffmpeg"
            )
        return path

    async def _run(self, cmd: list[str]) -> tuple[str, str, int]:
        """Run a subprocess, returning (stdout, stderr, returncode)."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        return (
            out.decode(errors="replace"),
            err.decode(errors="replace"),
            proc.returncode,
        )

    async def _probe_audio_codec(self, input_path: Path) -> str:
        cmd = [
            self._ffprobe, "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name",
            "-of", "json",
            str(input_path),
        ]
        stdout, stderr, rc = await self._run(cmd)
        if rc != 0:
            raise FFmpegError(f"ffprobe failed: {stderr[:300]}")
        streams = json.loads(stdout or "{}").get("streams", [])
        if not streams:
            raise FFmpegError(f"No audio stream found in {input_path}")
        return (streams[0].get("codec_name") or "").strip().lower()

    async def _find_attached_cover(self, input_path: Path) -> int | None:
        cmd = [
            self._ffprobe, "-v", "error",
            "-show_entries",
            "stream=index,codec_type:stream_disposition=attached_pic",
            "-of", "json",
            str(input_path),
        ]
        stdout, stderr, rc = await self._run(cmd)
        if rc != 0:
            return None
        for stream in json.loads(stdout or "{}").get("streams", []):
            disposition = stream.get("disposition", {})
            if (
                stream.get("codec_type") == "video"
                and disposition.get("attached_pic") == 1
            ):
                return int(stream["index"])
        return None

    async def _extract_cover(
        self, input_path: Path, stream_index: int, workdir: Path
    ) -> Path:
        cover = workdir / "cover.png"
        cmd = [
            self._ffmpeg, "-y",
            "-i", str(input_path),
            "-map", f"0:{stream_index}",
            "-frames:v", "1",
            str(cover),
        ]
        _, stderr, rc = await self._run(cmd)
        if rc != 0 or not cover.exists():
            raise FFmpegError(f"Failed to extract cover art: {stderr[:300]}")
        return cover

    def _build_command(
        self,
        *,
        image: Path | None,
        image_is_generated: bool,
        audio_path: Path,
        output_path: Path,
        width: int,
        height: int,
        fps: int,
        audio_copy: bool,
    ) -> list[str]:
        vf = (
            f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={BACKGROUND_COLOR},"
            f"format=yuv420p"
        )
        cmd = [self._ffmpeg, "-y"]
        # Input 0: the still image (looped) or a generated solid background.
        if image_is_generated:
            cmd += [
                "-f", "lavfi",
                "-i", f"color=c={BACKGROUND_COLOR}:s={width}x{height}:r={fps}",
            ]
        else:
            cmd += ["-loop", "1", "-framerate", str(fps), "-i", str(image)]
        # Input 1: the source audio.
        cmd += ["-i", str(audio_path)]
        cmd += [
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-preset", "veryfast",
            "-vf", vf,
            "-pix_fmt", "yuv420p",
            "-fps_mode", "cfr",
        ]
        if audio_copy:
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", "aac", "-b:a", "128k"]
        cmd += ["-shortest", "-movflags", "+faststart", str(output_path)]
        return cmd

    def _preflight(
        self, input_path: Path, output_path: Path, image: Path | None
    ) -> None:
        if not input_path.exists():
            raise FFmpegError(f"Input file not found: {input_path}")
        if output_path.exists():
            raise FFmpegError(
                f"Output already exists (refusing to overwrite): {output_path}"
            )
        if not os.access(output_path.parent, os.W_OK):
            raise FFmpegError(f"Destination not writable: {output_path.parent}")
        if image is not None and not image.exists():
            raise FFmpegError(f"Image file not found: {image}")

    @staticmethod
    def _is_copy_mux_failure(stderr: str) -> bool:
        low = stderr.lower()
        return any(marker in low for marker in _COPY_MUX_ERROR_MARKERS)

    async def create(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        image: str | Path | None = None,
        resolution: str = "720p",
        fps: int = 2,
    ) -> Path:
        input_path = Path(input_path)
        output_path = (
            Path(output_path) if output_path else _default_output_path(input_path)
        )
        image = Path(image) if image else None
        width, height = _resolution_dims(resolution)

        self._preflight(input_path, output_path, image)

        with tempfile.TemporaryDirectory(
            dir=str(output_path.parent), prefix=".to_video_"
        ) as tmp:
            workdir = Path(tmp)
            tmp_out = workdir / f"{output_path.stem}.tmp.mp4"

            # Resolve the still image: custom > embedded cover > generated bg.
            image_is_generated = False
            still = image
            if still is None:
                cover_idx = await self._find_attached_cover(input_path)
                if cover_idx is not None:
                    still = await self._extract_cover(input_path, cover_idx, workdir)
                else:
                    image_is_generated = True

            audio_copy = await self._probe_audio_codec(input_path) == "aac"
            logger.info(
                "Creating video: %s -> %s (audio=%s)",
                input_path.name, output_path.name, "copy" if audio_copy else "aac",
            )

            def build(copy: bool) -> list[str]:
                return self._build_command(
                    image=still, image_is_generated=image_is_generated,
                    audio_path=input_path, output_path=tmp_out,
                    width=width, height=height, fps=fps, audio_copy=copy,
                )

            _, stderr, rc = await self._run(build(audio_copy))
            if rc != 0:
                if audio_copy and self._is_copy_mux_failure(stderr):
                    logger.warning("Audio stream-copy failed; retrying with AAC encode")
                    if tmp_out.exists():
                        tmp_out.unlink()
                    _, stderr2, rc2 = await self._run(build(False))
                    if rc2 != 0:
                        raise FFmpegError(
                            "Video creation failed.\n"
                            f"Copy attempt: {stderr[:400]}\n"
                            f"AAC retry: {stderr2[:400]}"
                        )
                else:
                    raise FFmpegError(f"Video creation failed: {stderr[:500]}")

            if not tmp_out.exists():
                raise FFmpegError(f"Output not created: {tmp_out}")
            os.replace(str(tmp_out), str(output_path))

        size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info("Video complete: %s (%.2f MB)", output_path, size_mb)
        return output_path
