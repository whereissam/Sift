"""CLI for the Sift downloader and audio converter."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from . import download_audio
from .media.converter import AudioConverter
from .fetch.downloader import DownloaderFactory
from .media.video import AudioToVideo


async def download_command(args):
    """Handle download command (any supported platform)."""
    platform = DownloaderFactory.detect_platform(args.url)
    if not platform:
        print(f"Error: Unsupported or invalid URL: {args.url}", file=sys.stderr)
        sys.exit(1)

    print(f"Downloading from {platform.value}: {args.url}")

    result = await download_audio(
        url=args.url,
        output_path=Path(args.output) if args.output else None,
        output_format=args.format,
        quality=args.quality,
    )

    if result.success:
        print("\nDownload complete!")
        print(f"File: {result.file_path}")
        if result.file_size_mb:
            print(f"Size: {result.file_size_mb:.2f} MB")
        duration = result.metadata.duration_seconds if result.metadata else None
        if duration:
            mins = int(duration // 60)
            secs = int(duration % 60)
            print(f"Duration: {mins}m {secs}s")
    else:
        print(f"\nDownload failed: {result.error}", file=sys.stderr)
        sys.exit(1)


async def convert_command(args):
    """Handle convert command."""
    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Converting: {input_path}")
    print(f"Format: {args.format}")
    print(f"Quality: {args.quality}")

    converter = AudioConverter()

    try:
        output_path = await converter.convert(
            input_path=input_path,
            output_path=args.output,
            output_format=args.format,
            quality=args.quality,
            keep_original=not args.delete_original,
        )

        output_size = output_path.stat().st_size / (1024 * 1024)
        print("\nConversion complete!")
        print(f"Output: {output_path}")
        print(f"Size: {output_size:.2f} MB")

    except Exception as e:
        print(f"\nConversion failed: {e}", file=sys.stderr)
        sys.exit(1)


async def to_video_command(args):
    """Create a YouTube-ready MP4 (still image + audio) from an audio file."""
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Creating video from: {input_path}")
    try:
        maker = AudioToVideo()
        output = await maker.create(
            input_path=input_path,
            output_path=args.output,
            resolution=args.resolution,
            fps=args.fps,
        )
    except Exception as e:
        print(f"\nVideo creation failed: {e}", file=sys.stderr)
        sys.exit(1)

    size_mb = output.stat().st_size / (1024 * 1024)
    print("\nVideo ready!")
    print(f"Output: {output}")
    print(f"Size: {size_mb:.2f} MB")


async def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="X Spaces Downloader - Download and convert Twitter/X Spaces audio",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Download command (also default if URL is provided directly)
    download_parser = subparsers.add_parser(
        "download",
        help="Download audio from any supported platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  xdownloader download https://x.com/i/spaces/1vOxwdyYrlqKB
  xdownloader download -f mp3 https://youtube.com/watch?v=dQw4w9WgXcQ
  xdownloader download -o episode.m4a https://xiaoyuzhoufm.com/episode/...
        """,
    )
    download_parser.add_argument("url", help="URL to download (X Spaces, YouTube, podcasts, …)")
    download_parser.add_argument("-o", "--output", help="Output file path")
    download_parser.add_argument(
        "-f", "--format",
        choices=["m4a", "mp3"],
        default="m4a",
        help="Output format (default: m4a)",
    )
    download_parser.add_argument(
        "-q", "--quality",
        choices=["low", "medium", "high", "highest"],
        default="high",
        help="Quality preset for MP3 (default: high)",
    )

    # Convert command
    convert_parser = subparsers.add_parser(
        "convert",
        help="Convert audio file to another format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  xdownloader convert -f mp3 space.m4a
  xdownloader convert -f mp4 -q highest space.m4a
  xdownloader convert -f wav -o output.wav space.m4a
  xdownloader convert -f mp3 --delete-original space.m4a

Supported formats: mp3, mp4, aac, wav, ogg, flac
        """,
    )
    convert_parser.add_argument("input", help="Input audio file")
    convert_parser.add_argument("-o", "--output", help="Output file path")
    convert_parser.add_argument(
        "-f", "--format",
        choices=["mp3", "mp4", "aac", "wav", "ogg", "flac"],
        default="mp3",
        help="Output format (default: mp3)",
    )
    convert_parser.add_argument(
        "-q", "--quality",
        choices=["low", "medium", "high", "highest"],
        default="high",
        help="Quality preset for lossy formats (default: high)",
    )
    convert_parser.add_argument(
        "--delete-original",
        action="store_true",
        help="Delete original file after conversion",
    )

    # to-video command
    to_video_parser = subparsers.add_parser(
        "to-video",
        help="Create a YouTube-ready MP4 (still image + audio) from an audio file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  xdownloader to-video podcast.m4a
  xdownloader to-video --resolution 1080p -o show.mp4 podcast.m4a
        """,
    )
    to_video_parser.add_argument("input", help="Input audio file")
    to_video_parser.add_argument("-o", "--output", help="Output MP4 path (default: <name>.youtube.mp4)")
    to_video_parser.add_argument(
        "--resolution",
        choices=["480p", "720p", "1080p"],
        default="720p",
        help="Video resolution (default: 720p)",
    )
    to_video_parser.add_argument(
        "--fps", type=int, default=2, help="Still-image frame rate (default: 2)"
    )

    # Parse args
    args, remaining = parser.parse_known_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    # Handle direct URL input (backward compatibility)
    if args.command is None and remaining:
        # Check if first remaining arg looks like a URL
        if remaining[0].startswith("http"):
            # Re-parse with download as default command
            sys.argv = [sys.argv[0], "download"] + remaining
            args = parser.parse_args()
            args.command = "download"

    # Execute command
    if args.command == "download":
        await download_command(args)
    elif args.command == "convert":
        await convert_command(args)
    elif args.command == "to-video":
        await to_video_command(args)
    else:
        parser.print_help()
        sys.exit(0)


def cli():
    """Synchronous CLI wrapper."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
