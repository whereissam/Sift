"""Telegram bot for Sift — supports all platforms via DownloaderFactory."""

import asyncio
import hashlib
import logging
import shutil
from pathlib import Path
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from ..config import get_settings
from ..core import (
    SiftError,
    AuthenticationError,
    ContentNotAvailableError,
    ContentNotFoundError,
    DownloaderFactory,
    Platform,
    UnsupportedPlatformError,
)

logger = logging.getLogger(__name__)

TELEGRAM_FILE_SIZE_LIMIT_MB = 50

VIDEO_PLATFORMS = {
    Platform.X_VIDEO,
    Platform.YOUTUBE_VIDEO,
    Platform.INSTAGRAM,
    Platform.XIAOHONGSHU,
}

PLATFORM_LABELS = {
    Platform.X_SPACES: "X Spaces",
    Platform.APPLE_PODCASTS: "Apple Podcasts",
    Platform.SPOTIFY: "Spotify",
    Platform.YOUTUBE: "YouTube Audio",
    Platform.XIAOYUZHOU: "Xiaoyuzhou",
    Platform.DISCORD: "Discord",
    Platform.X_VIDEO: "X Video",
    Platform.YOUTUBE_VIDEO: "YouTube Video",
    Platform.INSTAGRAM: "Instagram",
    Platform.XIAOHONGSHU: "Xiaohongshu",
}


def _short_hash(text: str) -> str:
    """Return short md5 hash for keying URLs in user_data."""
    return hashlib.md5(text.encode()).hexdigest()[:10]


def _format_duration(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


class SiftBot:
    """Telegram bot supporting all Sift platforms."""

    def __init__(self, token: str):
        self.token = token
        self.settings = get_settings()

    # ── Commands ──────────────────────────────────────────────

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        platforms = "\n".join(
            f"  - {PLATFORM_LABELS.get(p, p.value)}"
            for p in Platform
        )
        text = (
            "Welcome to Sift Bot!\n\n"
            "Send me a link and I'll download the audio (or video) for you.\n\n"
            f"Supported platforms:\n{platforms}\n\n"
            "Commands:\n"
            "/start - Show this message\n"
            "/help - Usage instructions\n"
            "/status - Check bot status\n"
            "/platforms - List platforms & availability\n"
            "/transcribe - Transcribe audio"
        )
        await update.message.reply_text(text)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = (
            "How to use this bot:\n\n"
            "1. Send a link from any supported platform\n"
            "2. Choose output format from the buttons\n"
            "3. Wait for the download to complete\n"
            "4. Receive the file\n\n"
            "Transcription:\n"
            "- /transcribe <url> — download and transcribe\n"
            "- Reply to an audio file with /transcribe\n\n"
            "Note: Telegram limits file uploads to 50 MB."
        )
        await update.message.reply_text(text)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ffmpeg_ok = shutil.which("ffmpeg") is not None
        auth_ok = self.settings.has_auth
        available = DownloaderFactory.get_available_platforms()

        lines = [
            "Bot Status:\n",
            f"FFmpeg: {'OK' if ffmpeg_ok else 'Not Found'}",
            f"Twitter Auth: {'Configured' if auth_ok else 'Not Configured'}",
            f"Available platforms: {len(available)}/{len(Platform)}",
        ]
        await update.message.reply_text("\n".join(lines))

    async def platforms_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        available = set(DownloaderFactory.get_available_platforms())
        lines = ["Platforms:\n"]
        for p in Platform:
            ok = "+" if p in available else "-"
            label = PLATFORM_LABELS.get(p, p.value)
            kind = "video" if p in VIDEO_PLATFORMS else "audio"
            lines.append(f"  [{ok}] {label} ({kind})")
        lines.append("\n+ = available, - = missing dependencies")
        await update.message.reply_text("\n".join(lines))

    async def transcribe_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # If replying to an audio file
        reply = update.message.reply_to_message
        if reply and (reply.audio or reply.voice or reply.document):
            await self._transcribe_from_message(update, reply)
            return

        # If URL argument provided
        if context.args:
            url = context.args[0]
            await self._transcribe_from_url(update, url)
            return

        await update.message.reply_text(
            "Usage:\n"
            "- /transcribe <url>\n"
            "- Reply to an audio file with /transcribe"
        )

    # ── URL handler ───────────────────────────────────────────

    async def handle_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = update.message.text.strip()

        # Extract first URL-like token
        url = None
        for token in text.split():
            if token.startswith("http://") or token.startswith("https://"):
                url = token
                break

        if not url or not DownloaderFactory.is_url_supported(url):
            logger.info(f"[bot] Unsupported URL from user {update.effective_user.id}: {text[:100]}")
            await update.message.reply_text(
                "URL not supported. Use /platforms to see supported platforms."
            )
            return

        platform = DownloaderFactory.detect_platform(url)
        label = PLATFORM_LABELS.get(platform, platform.value) if platform else "Unknown"
        logger.info(f"[bot] URL from user {update.effective_user.id}: {url} -> {label}")

        url_hash = _short_hash(url)
        context.user_data[f"url:{url_hash}"] = url

        is_video = platform in VIDEO_PLATFORMS
        # YouTube URLs: detected as audio first, but user may want video
        is_youtube = platform in (Platform.YOUTUBE, Platform.YOUTUBE_VIDEO)

        if is_youtube:
            buttons = [
                [
                    InlineKeyboardButton("MP3 (audio)", callback_data=f"dl:{url_hash}:mp3"),
                    InlineKeyboardButton("M4A (audio)", callback_data=f"dl:{url_hash}:m4a"),
                ],
                [
                    InlineKeyboardButton("MP4 (video)", callback_data=f"dl:{url_hash}:mp4"),
                    InlineKeyboardButton("Transcribe", callback_data=f"tr:{url_hash}"),
                ],
            ]
        elif is_video:
            buttons = [
                [
                    InlineKeyboardButton("MP4 (video)", callback_data=f"dl:{url_hash}:mp4"),
                    InlineKeyboardButton("MP3 (audio)", callback_data=f"dl:{url_hash}:mp3"),
                ],
                [
                    InlineKeyboardButton("Transcribe", callback_data=f"tr:{url_hash}"),
                ],
            ]
        else:
            buttons = [
                [
                    InlineKeyboardButton("M4A", callback_data=f"dl:{url_hash}:m4a"),
                    InlineKeyboardButton("MP3", callback_data=f"dl:{url_hash}:mp3"),
                ],
                [
                    InlineKeyboardButton("Transcribe", callback_data=f"tr:{url_hash}"),
                ],
            ]

        await update.message.reply_text(
            f"Detected: {label}\nChoose an option:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    # ── Callback handler ──────────────────────────────────────

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()

        data = query.data
        if not data:
            return

        # Transcribe callback
        if data.startswith("tr:"):
            url_hash = data[3:]
            url = context.user_data.get(f"url:{url_hash}")
            if not url:
                await query.edit_message_text("Session expired. Please send the URL again.")
                return
            await query.edit_message_text("Downloading audio for transcription...")
            try:
                await self._transcribe_from_url_callback(update, query, url)
            except Exception as e:
                logger.exception(f"Transcribe error for user {update.effective_user.id}")
                await query.edit_message_text("Transcription failed. Please try again later.")
            return

        # Download callback
        if not data.startswith("dl:"):
            return

        parts = data.split(":")
        if len(parts) != 3:
            return

        _, url_hash, fmt = parts
        url = context.user_data.get(f"url:{url_hash}")
        if not url:
            await query.edit_message_text("Session expired. Please send the URL again.")
            return

        platform = DownloaderFactory.detect_platform(url)
        label = PLATFORM_LABELS.get(platform, platform.value) if platform else "Unknown"
        await query.edit_message_text(f"[1/3] Fetching from {label}...")

        try:
            await self._download_and_send(update, context, url, fmt, platform)
        except UnsupportedPlatformError:
            await query.edit_message_text("Platform not supported.")
        except ContentNotFoundError:
            await query.edit_message_text("Content not found. Check the URL.")
        except ContentNotAvailableError:
            await query.edit_message_text(
                "Content not available for download. It may be live or restricted."
            )
        except AuthenticationError:
            await query.edit_message_text(
                "Authentication error. Please contact the bot admin."
            )
        except SiftError as e:
            logger.error(f"Download error for user {update.effective_user.id}: {e}")
            await query.edit_message_text(f"Download failed: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error for user {update.effective_user.id}")
            await query.edit_message_text("An unexpected error occurred. Please try again later.")

    # ── Internal helpers ──────────────────────────────────────

    async def _download_and_send(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        url: str,
        fmt: str,
        platform=None,
    ) -> None:
        query = update.callback_query
        if platform is None:
            platform = DownloaderFactory.detect_platform(url)
        label = PLATFORM_LABELS.get(platform, platform.value) if platform else "Unknown"

        # YouTube special case: if user picks MP4, use the video downloader
        if fmt == "mp4" and platform == Platform.YOUTUBE:
            downloader = DownloaderFactory.get_downloader_for_platform(Platform.YOUTUBE_VIDEO)
        elif fmt in ("m4a", "mp3") and platform == Platform.YOUTUBE_VIDEO:
            downloader = DownloaderFactory.get_downloader_for_platform(Platform.YOUTUBE)
        else:
            downloader = DownloaderFactory.get_downloader(url)

        logger.info(f"[bot] Starting download: {url} as {fmt} for user {update.effective_user.id} (platform={label})")
        result = await downloader.download(url, output_format=fmt)

        if not result.success:
            await query.edit_message_text(f"Download failed: {result.error}")
            return

        file_path = result.file_path
        file_size_mb = result.file_size_mb or 0
        title = result.metadata.title if result.metadata else "Download"
        performer = None
        if result.metadata:
            performer = result.metadata.creator_name or result.metadata.creator_username

        logger.info(f"[bot] Download complete: {title} ({file_size_mb:.1f} MB) path={file_path}")

        # Step 2: Check size
        if file_size_mb > TELEGRAM_FILE_SIZE_LIMIT_MB:
            await query.edit_message_text(
                f"File too large ({file_size_mb:.1f} MB). Telegram limit is {TELEGRAM_FILE_SIZE_LIMIT_MB} MB."
            )
            if file_path:
                file_path.unlink(missing_ok=True)
            return

        # Step 3: Upload
        duration_text = ""
        if result.metadata and result.metadata.duration_seconds:
            duration_text = f" | {_format_duration(result.metadata.duration_seconds)}"
        await query.edit_message_text(
            f"[2/3] Downloaded: {title}\n"
            f"      {file_size_mb:.1f} MB{duration_text}\n\n"
            f"[3/3] Uploading to Telegram..."
        )

        caption_lines = [f"Title: {title}"]
        if performer:
            caption_lines.append(f"By: {performer}")
        if result.metadata and result.metadata.duration_seconds:
            caption_lines.append(f"Duration: {_format_duration(result.metadata.duration_seconds)}")
        caption_lines.append(f"Size: {file_size_mb:.1f} MB")
        caption = "\n".join(caption_lines)

        duration = None
        if result.metadata and result.metadata.duration_seconds:
            duration = int(result.metadata.duration_seconds)

        max_retries = 3
        try:
            for attempt in range(1, max_retries + 1):
                try:
                    with open(file_path, "rb") as f:
                        if fmt == "mp4" and platform in VIDEO_PLATFORMS:
                            await query.message.reply_video(
                                video=f,
                                caption=caption,
                                duration=duration,
                                supports_streaming=True,
                                read_timeout=300,
                                write_timeout=300,
                            )
                        else:
                            await query.message.reply_audio(
                                audio=f,
                                title=title,
                                performer=performer,
                                duration=duration,
                                caption=caption,
                                read_timeout=300,
                                write_timeout=300,
                            )
                    await query.delete_message()
                    logger.info(f"[bot] Upload complete: {title} ({file_size_mb:.1f} MB) -> user {update.effective_user.id}")
                    return
                except Exception as e:
                    logger.warning(f"[bot] Upload attempt {attempt}/{max_retries} failed: {e}")
                    if attempt == max_retries:
                        await query.edit_message_text(
                            f"Upload failed after {max_retries} attempts. File was {file_size_mb:.1f} MB — "
                            "Telegram may be having issues with large files."
                        )
                    else:
                        await asyncio.sleep(3 * attempt)
                        await query.edit_message_text(
                            f"[3/3] Upload failed, retrying ({attempt + 1}/{max_retries})..."
                        )
        finally:
            if file_path:
                file_path.unlink(missing_ok=True)

    async def _transcribe_from_url_callback(self, update: Update, query, url: str) -> None:
        """Transcribe from URL triggered via inline keyboard callback."""
        await query.edit_message_text("[1/2] Downloading audio...")
        result = await DownloaderFactory.get_downloader(url).download(url, output_format="m4a")
        if not result.success:
            await query.edit_message_text(f"Download failed: {result.error}")
            return

        await query.edit_message_text("[2/2] Transcribing (this may take a while)...")
        await self._do_transcribe(update, query, result.file_path)

    async def _transcribe_from_url(self, update: Update, url: str) -> None:
        if not DownloaderFactory.is_url_supported(url):
            await update.message.reply_text("URL not supported for transcription.")
            return

        status_msg = await update.message.reply_text("Downloading audio for transcription...")

        try:
            result = await DownloaderFactory.get_downloader(url).download(url, output_format="m4a")
            if not result.success:
                await status_msg.edit_text(f"Download failed: {result.error}")
                return

            await status_msg.edit_text("Transcribing...")
            await self._do_transcribe(update, status_msg, result.file_path)
        except Exception as e:
            logger.exception(f"Transcribe error for user {update.effective_user.id}")
            await status_msg.edit_text(f"Transcription failed: {e}")

    async def _transcribe_from_message(self, update: Update, reply_msg) -> None:
        status_msg = await update.message.reply_text("Downloading file...")

        try:
            file_obj = reply_msg.audio or reply_msg.voice or reply_msg.document
            tg_file = await file_obj.get_file()

            download_dir = self.settings.get_download_path()
            ext = Path(tg_file.file_path).suffix if tg_file.file_path else ".ogg"
            local_path = download_dir / f"tg_{file_obj.file_id}{ext}"
            await tg_file.download_to_drive(local_path)

            await status_msg.edit_text("Transcribing...")
            await self._do_transcribe(update, status_msg, local_path)
        except Exception as e:
            logger.exception(f"Transcribe error for user {update.effective_user.id}")
            await status_msg.edit_text(f"Transcription failed: {e}")

    @staticmethod
    async def _edit_status(msg, text: str) -> None:
        """Edit a status message — works with both Message and CallbackQuery."""
        if hasattr(msg, "edit_message_text"):
            await msg.edit_message_text(text)
        else:
            await msg.edit_text(text)

    @staticmethod
    async def _delete_status(msg) -> None:
        if hasattr(msg, "delete_message"):
            await msg.delete_message()
        else:
            await msg.delete()

    async def _do_transcribe(
        self,
        update: Update,
        status_msg,
        audio_path: Path,
    ) -> None:
        try:
            from ..core.transcriber import AudioTranscriber

            transcriber = AudioTranscriber(
                remote_service_url=self.settings.whisper_service_url,
            )
            result = await transcriber.transcribe(audio_path)

            if not result.success:
                logger.error(f"Transcription failed: {result.error}")
                await self._edit_status(status_msg, "Transcription failed. Please try again later.")
                return

            text = result.text or ""
            if len(text) <= 4096:
                await self._edit_status(status_msg, text or "(empty transcription)")
            else:
                txt_path = audio_path.with_suffix(".txt")
                txt_path.write_text(text, encoding="utf-8")
                await self._edit_status(status_msg, "Transcription too long, sending as file...")
                with open(txt_path, "rb") as f:
                    await update.effective_message.reply_document(
                        document=f,
                        filename="transcription.txt",
                    )
                await self._delete_status(status_msg)
                txt_path.unlink(missing_ok=True)
        finally:
            if audio_path and audio_path.exists():
                audio_path.unlink(missing_ok=True)

    # ── Application builder ───────────────────────────────────

    def build_application(self) -> Application:
        application = (
            Application.builder()
            .token(self.token)
            .read_timeout(300)
            .write_timeout(300)
            .connect_timeout(30)
            .build()
        )

        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("status", self.status_command))
        application.add_handler(CommandHandler("platforms", self.platforms_command))
        application.add_handler(CommandHandler("transcribe", self.transcribe_command))
        application.add_handler(CallbackQueryHandler(self.handle_callback))
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_url)
        )

        return application

    def run_polling(self) -> None:
        application = self.build_application()
        logger.info("Starting Sift Telegram bot (polling)...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

    async def setup_webhook(self, webhook_url: str, secret: Optional[str] = None) -> Application:
        application = self.build_application()
        await application.initialize()
        await application.bot.set_webhook(
            url=webhook_url,
            secret_token=secret,
        )
        await application.start()
        logger.info(f"Telegram webhook set to {webhook_url}")
        return application


def run_bot():
    """Entry point for running the bot in polling mode."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    settings = get_settings()

    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

    bot = SiftBot(settings.telegram_bot_token)
    bot.run_polling()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    run_bot()
