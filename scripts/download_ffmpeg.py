#!/usr/bin/env python3
"""
Download a static FFmpeg binary for bundling with the desktop app.

Usage:
    uv run python scripts/download_ffmpeg.py [--target-dir PATH] [--download]

Copies the system FFmpeg if one is on PATH (unless --download is given),
otherwise downloads a pre-built static FFmpeg binary and places it in the
Tauri binaries directory with the correct target-triple suffix.

Every download is checked against a SHA-256 pinned below before it is
unpacked, and a mismatch aborts. Neither upstream publishes a SHA-256:
evermeet.cx only offers GPG signatures and johnvansickle.com only MD5 files
(not collision-resistant), so the digests are pinned here. The pinned
johnvansickle digests were cross-checked against its published .md5 files.

To bump a build: update the URL/version, download the file, record
`shasum -a 256 <file>` here, and review the diff.
"""

import argparse
import hashlib
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "frontend" / "src-tauri" / "binaries"


@dataclass(frozen=True)
class Build:
    url: str
    sha256: str
    version: str


# evermeet.cx ships macOS builds (x86_64; they run on Apple Silicon via
# Rosetta). The versioned URL is immutable, unlike .../getrelease/ffmpeg/zip.
MACOS_BUILD = Build(
    url="https://evermeet.cx/ffmpeg/ffmpeg-9.0.2.zip",
    sha256="4acc0be580f9b2788029eb7bd4d645ff87968911b0a62aeeb3940d42d54558d5",
    version="9.0.2",
)

# johnvansickle.com only serves the current release under a moving
# "release" name (the versioned file moves to old-releases/ once superseded),
# so a new upstream release fails the pin until it is reviewed and bumped.
LINUX_BUILDS = {
    "amd64": Build(
        url="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
        sha256="abda8d77ce8309141f83ab8edf0596834087c52467f6badf376a6a2a4c87cf67",
        version="7.0.2",
    ),
    "arm64": Build(
        url="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz",
        sha256="f4149bb2b0784e30e99bdda85471c9b5930d3402014e934a5098b41d0f7201b1",
        version="7.0.2",
    ),
}


class ChecksumMismatch(RuntimeError):
    """A downloaded file's SHA-256 does not match the pinned value."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: Path, expected: str) -> None:
    """Raise ChecksumMismatch unless `path` hashes to `expected`."""
    expected = expected.strip().lower()
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError(f"Invalid pinned SHA-256: {expected!r}")
    actual = sha256_file(path)
    if actual != expected:
        raise ChecksumMismatch(
            f"SHA-256 mismatch for {path.name}: expected {expected}, got {actual}"
        )


def fetch_verified(build: Build, dest: Path) -> None:
    """Download `build` to `dest` and verify it, deleting it on mismatch."""
    subprocess.run(
        ["curl", "-fL", "--proto", "=https", "--proto-redir", "=https", "-o", str(dest), build.url],
        check=True,
    )
    try:
        verify_sha256(dest, build.sha256)
    except ChecksumMismatch:
        dest.unlink(missing_ok=True)
        raise
    print(f"Verified SHA-256 {build.sha256} ({build.url})")


def get_target_triple() -> str:
    machine = platform.machine().lower()
    system = platform.system().lower()
    arch_map = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}
    arch = arch_map.get(machine, machine)

    if system == "darwin":
        return f"{arch}-apple-darwin"
    elif system == "linux":
        return f"{arch}-unknown-linux-gnu"
    elif system == "windows":
        return f"{arch}-pc-windows-msvc"
    else:
        raise RuntimeError(f"Unsupported platform: {system} {machine}")


def download_ffmpeg(target_dir: Path, force_download: bool = False) -> None:
    target_triple = get_target_triple()
    system = platform.system().lower()
    machine = platform.machine().lower()

    target_dir.mkdir(parents=True, exist_ok=True)
    output_name = f"ffmpeg-{target_triple}"

    # Check if ffmpeg is already installed via Homebrew or system
    ffmpeg_path = None if force_download else shutil.which("ffmpeg")
    if ffmpeg_path:
        print(f"Found system FFmpeg at: {ffmpeg_path}")
        final_path = target_dir / output_name
        shutil.copy2(ffmpeg_path, str(final_path))
        final_path.chmod(0o755)
        print(f"Copied to: {final_path}")
        print(f"Size: {final_path.stat().st_size / 1024 / 1024:.1f} MB")
        return

    # If no system ffmpeg, download a static build
    print("Downloading static FFmpeg build...")

    if system == "darwin":
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "ffmpeg.zip"
            fetch_verified(MACOS_BUILD, zip_path)
            extract_dir = Path(tmpdir) / "extract"
            subprocess.run(["unzip", "-o", str(zip_path), "-d", str(extract_dir)], check=True)
            extracted = extract_dir / "ffmpeg"
            if not extracted.is_file():
                print("ERROR: ffmpeg not found in downloaded archive")
                sys.exit(1)
            final_path = target_dir / output_name
            shutil.copy2(str(extracted), str(final_path))
            final_path.chmod(0o755)

    elif system == "linux":
        arch_suffix = "amd64" if "x86_64" in machine or "amd64" in machine else "arm64"
        build = LINUX_BUILDS[arch_suffix]
        with tempfile.TemporaryDirectory() as tmpdir:
            tar_path = Path(tmpdir) / "ffmpeg.tar.xz"
            fetch_verified(build, tar_path)
            extract_dir = Path(tmpdir) / "extract"
            extract_dir.mkdir()
            subprocess.run(["tar", "xf", str(tar_path), "-C", str(extract_dir)], check=True)
            # Find the ffmpeg binary in the extracted directory
            for f in extract_dir.rglob("ffmpeg"):
                if f.is_file():
                    final_path = target_dir / output_name
                    shutil.copy2(str(f), str(final_path))
                    final_path.chmod(0o755)
                    break
            else:
                print("ERROR: ffmpeg not found in downloaded archive")
                sys.exit(1)

    elif system == "windows":
        url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        print(f"Please download FFmpeg manually from: {url}")
        print("and verify it against the .sha256 published next to it.")
        print(f"Place ffmpeg.exe as: {target_dir / output_name}.exe")
        sys.exit(1)

    print(f"FFmpeg downloaded to: {target_dir / output_name}")
    print(f"Size: {(target_dir / output_name).stat().st_size / 1024 / 1024:.1f} MB")


def main():
    parser = argparse.ArgumentParser(description="Download static FFmpeg for desktop bundling")
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the pinned static build even if a system FFmpeg is on PATH",
    )
    args = parser.parse_args()
    try:
        download_ffmpeg(args.target_dir, force_download=args.download)
    except ChecksumMismatch as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Refusing to install an unverified FFmpeg build.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
