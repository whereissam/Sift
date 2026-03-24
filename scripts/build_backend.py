#!/usr/bin/env python3
"""
Build the AudioGrab backend into a standalone binary using Nuitka.

Usage:
    uv run python scripts/build_backend.py [--target-dir PATH]

The output binary is placed in frontend/src-tauri/binaries/ with the
correct target-triple suffix that Tauri expects for sidecars.
"""

import argparse
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_ENTRY = ROOT / "app" / "main.py"
DEFAULT_OUTPUT = ROOT / "frontend" / "src-tauri" / "binaries"


def get_target_triple() -> str:
    """Return the Rust-style target triple for the current platform."""
    machine = platform.machine().lower()
    system = platform.system().lower()

    arch_map = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }
    arch = arch_map.get(machine, machine)

    if system == "darwin":
        return f"{arch}-apple-darwin"
    elif system == "linux":
        return f"{arch}-unknown-linux-gnu"
    elif system == "windows":
        return f"{arch}-pc-windows-msvc"
    else:
        raise RuntimeError(f"Unsupported platform: {system} {machine}")


def build(target_dir: Path) -> None:
    target_triple = get_target_triple()
    output_name = f"audiograb-backend-{target_triple}"
    output_dir = target_dir / "nuitka_build"

    print(f"Building AudioGrab backend with Nuitka...")
    print(f"  Entry point: {APP_ENTRY}")
    print(f"  Target triple: {target_triple}")
    print(f"  Output: {target_dir / output_name}")

    cmd = [
        sys.executable, "-m", "nuitka",
        # Standalone mode — bundles Python interpreter + all deps
        "--standalone",
        # Single file output (optional, slightly slower startup but cleaner)
        "--onefile",
        # Output naming
        f"--output-filename={output_name}",
        f"--output-dir={output_dir}",
        # Include the entire app package
        "--include-package=app",
        # Include data files (templates, etc.)
        f"--include-data-dir={ROOT / 'app'}=app",
        # Key packages that need explicit inclusion (C extensions, lazy imports)
        "--include-package=uvicorn",
        "--include-package=uvicorn.lifespan",
        "--include-package=uvicorn.protocols",
        "--include-package=uvicorn.loops",
        "--include-package=fastapi",
        "--include-package=starlette",
        "--include-package=pydantic",
        "--include-package=pydantic_core",
        "--include-package=pydantic_settings",
        "--include-package=httpx",
        "--include-package=httpcore",
        "--include-package=anyio",
        "--include-package=slowapi",
        "--include-package=structlog",
        "--include-package=litellm",
        "--include-package=feedparser",
        "--include-package=mutagen",
        "--include-package=sentry_sdk",
        "--include-package=opencc",
        "--include-package=youtube_transcript_api",
        "--include-package=tenacity",
        "--include-package=cachetools",
        "--include-package=multipart",
        "--include-package=dotenv",
        # Native extension packages — use --include-module for C extensions
        # that crash Nuitka's optimizer (av, ctranslate2, onnxruntime).
        # --nofollow-import-to prevents Nuitka from compiling their internals;
        # they get included as-is (pre-compiled .so/.dylib wheels).
        "--nofollow-import-to=av",
        "--nofollow-import-to=ctranslate2",
        "--nofollow-import-to=onnxruntime",
        "--include-package=av",
        "--include-package=numpy",
        "--include-package=ctranslate2",
        "--include-package=onnxruntime",
        # Plugin controls
        "--enable-plugin=anti-bloat",
        "--nofollow-import-to=pytest",
        "--nofollow-import-to=setuptools",
        "--nofollow-import-to=pip",
        "--nofollow-import-to=wheel",
        # Suppress compilation prompts
        "--assume-yes-for-downloads",
        # Show progress
        "--show-progress",
        "--show-memory",
        # Entry point
        str(APP_ENTRY),
    ]

    print(f"\nRunning: {' '.join(cmd[:5])} ... (full command logged below)")
    print(f"Full command:\n  {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=str(ROOT))

    if result.returncode != 0:
        print(f"\nNuitka build failed with exit code {result.returncode}")
        sys.exit(1)

    # Move the built binary to the Tauri binaries directory
    # Nuitka puts the onefile binary in output_dir
    built_binary = output_dir / output_name
    if platform.system() == "Windows":
        built_binary = built_binary.with_suffix(".exe")

    if not built_binary.exists():
        # Try without the target triple in name (Nuitka might use a different name)
        for f in output_dir.iterdir():
            if f.is_file() and f.stat().st_size > 1_000_000:
                built_binary = f
                break

    if not built_binary.exists():
        print(f"ERROR: Built binary not found at {built_binary}")
        print(f"Contents of {output_dir}:")
        for f in output_dir.iterdir():
            print(f"  {f}")
        sys.exit(1)

    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = target_dir / output_name
    if platform.system() == "Windows":
        final_path = final_path.with_suffix(".exe")

    import shutil
    shutil.copy2(str(built_binary), str(final_path))
    final_path.chmod(0o755)

    print(f"\nBuild successful!")
    print(f"  Binary: {final_path}")
    print(f"  Size: {final_path.stat().st_size / 1024 / 1024:.1f} MB")


def main():
    parser = argparse.ArgumentParser(description="Build AudioGrab backend with Nuitka")
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output directory for the built binary",
    )
    args = parser.parse_args()
    build(args.target_dir)


if __name__ == "__main__":
    main()
