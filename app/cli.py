"""CLI for X Spaces downloader and audio converter."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .core import SpaceDownloader, SpaceURLParser
from .core.converter import AudioConverter


async def download_command(args):
    """Handle download command."""
    # Validate URL
    if not SpaceURLParser.is_valid_space_url(args.url):
        print(f"Error: Invalid Twitter Space URL: {args.url}", file=sys.stderr)
        sys.exit(1)

    print(f"Downloading Space: {args.url}")

    downloader = SpaceDownloader()
    result = await downloader.download(
        url=args.url,
        output_path=args.output,
        format=args.format,
        quality=args.quality,
    )

    if result.success:
        print("\nDownload complete!")
        print(f"File: {result.file_path}")
        if result.file_size_mb:
            print(f"Size: {result.file_size_mb:.2f} MB")
        if result.duration_seconds:
            mins = int(result.duration_seconds // 60)
            secs = int(result.duration_seconds % 60)
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
        help="Download a Twitter Space",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  xdownloader download https://x.com/i/spaces/1vOxwdyYrlqKB
  xdownloader download -f mp3 https://x.com/i/spaces/1vOxwdyYrlqKB
  xdownloader download -o my_space.m4a https://x.com/i/spaces/1vOxwdyYrlqKB
        """,
    )
    download_parser.add_argument("url", help="Twitter Space URL to download")
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
    else:
        parser.print_help()
        sys.exit(0)


def cli():
    """Synchronous CLI wrapper."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
