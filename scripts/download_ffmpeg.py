#!/usr/bin/env python3
"""
Download a static FFmpeg binary for bundling with the desktop app.

Usage:
    uv run python scripts/download_ffmpeg.py [--target-dir PATH]

Downloads a pre-built static FFmpeg binary and places it in the Tauri
binaries directory with the correct target-triple suffix.
"""

import argparse
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "frontend" / "src-tauri" / "binaries"


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


def download_ffmpeg(target_dir: Path) -> None:
    target_triple = get_target_triple()
    system = platform.system().lower()
    machine = platform.machine().lower()

    target_dir.mkdir(parents=True, exist_ok=True)
    output_name = f"ffmpeg-{target_triple}"

    # Check if ffmpeg is already installed via Homebrew or system
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        print(f"Found system FFmpeg at: {ffmpeg_path}")
        final_path = target_dir / output_name
        shutil.copy2(ffmpeg_path, str(final_path))
        final_path.chmod(0o755)
        print(f"Copied to: {final_path}")
        print(f"Size: {final_path.stat().st_size / 1024 / 1024:.1f} MB")
        return

    # If no system ffmpeg, download a static build
    print("No system FFmpeg found. Downloading static build...")

    if system == "darwin":
        # Use evermeet.cx static builds for macOS
        url = "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip"
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "ffmpeg.zip"
            subprocess.run(["curl", "-L", "-o", str(zip_path), url], check=True)
            subprocess.run(["unzip", "-o", str(zip_path), "-d", tmpdir], check=True)
            extracted = Path(tmpdir) / "ffmpeg"
            if not extracted.exists():
                print("ERROR: ffmpeg not found in downloaded archive")
                sys.exit(1)
            final_path = target_dir / output_name
            shutil.copy2(str(extracted), str(final_path))
            final_path.chmod(0o755)

    elif system == "linux":
        arch_suffix = "amd64" if "x86_64" in machine or "amd64" in machine else "arm64"
        url = f"https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-{arch_suffix}-static.tar.xz"
        with tempfile.TemporaryDirectory() as tmpdir:
            tar_path = Path(tmpdir) / "ffmpeg.tar.xz"
            subprocess.run(["curl", "-L", "-o", str(tar_path), url], check=True)
            subprocess.run(["tar", "xf", str(tar_path), "-C", tmpdir], check=True)
            # Find the ffmpeg binary in the extracted directory
            for f in Path(tmpdir).rglob("ffmpeg"):
                if f.is_file():
                    final_path = target_dir / output_name
                    shutil.copy2(str(f), str(final_path))
                    final_path.chmod(0o755)
                    break

    elif system == "windows":
        url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        print(f"Please download FFmpeg manually from: {url}")
        print(f"Place ffmpeg.exe as: {target_dir / output_name}.exe")
        sys.exit(1)

    print(f"FFmpeg downloaded to: {target_dir / output_name}")
    print(f"Size: {(target_dir / output_name).stat().st_size / 1024 / 1024:.1f} MB")


def main():
    parser = argparse.ArgumentParser(description="Download static FFmpeg for desktop bundling")
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    download_ffmpeg(args.target_dir)


if __name__ == "__main__":
    main()
