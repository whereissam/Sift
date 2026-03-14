"""Pydantic schemas for API requests and responses."""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Platform(str, Enum):
    """Supported platforms."""

    # Audio
    X_SPACES = "x_spaces"
    APPLE_PODCASTS = "apple_podcasts"
    SPOTIFY = "spotify"
    YOUTUBE = "youtube"
    XIAOYUZHOU = "xiaoyuzhou"
    DISCORD = "discord"
    # Video
    X_VIDEO = "x_video"
    YOUTUBE_VIDEO = "youtube_video"
    INSTAGRAM = "instagram"
    XIAOHONGSHU = "xiaohongshu"
    AUTO = "auto"  # Auto-detect from URL


class OutputFormat(str, Enum):
    """Supported output formats."""

    M4A = "m4a"
    MP3 = "mp3"
    MP4 = "mp4"
    AAC = "aac"


class QualityPreset(str, Enum):
    """Quality presets for encoding."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    HIGHEST = "highest"


class JobStatus(str, Enum):
    """Download job statuses."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DownloadRequest(BaseModel):
    """Request to download audio."""

    url: str = Field(
        ...,
        max_length=2048,
        description="Audio content URL",
        examples=[
            "https://x.com/i/spaces/1vOxwdyYrlqKB",
            "https://podcasts.apple.com/us/podcast/show/id123456789",
            "https://open.spotify.com/episode/abc123",
        ],
    )
    platform: Platform = Field(
        default=Platform.AUTO,
        description="Platform (auto-detected if not specified)",
    )
    format: OutputFormat = Field(
        default=OutputFormat.M4A,
        description="Output audio format",
    )
    quality: QualityPreset = Field(
        default=QualityPreset.HIGH,
        description="Quality preset for encoding",
    )
    embed_metadata: bool = Field(
        default=True,
        description="Embed ID3/MP4 metadata tags (title, artist, artwork) into audio file",
    )
    output_dir: Optional[str] = Field(
        default=None,
        description="Custom output directory for the downloaded file. If not specified, uses default temp directory.",
    )
    keep_file: bool = Field(
        default=True,
        description="Keep the downloaded file after completion. Set to False for temp downloads.",
    )
    # Priority & Scheduling
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Priority level (1=low, 5=normal, 10=high)",
    )
    scheduled_at: Optional[datetime] = Field(
        default=None,
        description="Schedule download for a specific time (ISO format)",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        description="Webhook URL for job completion notification",
    )


class ContentInfo(BaseModel):
    """Information about downloaded content."""

    platform: Platform
    content_id: str
    title: str
    creator_name: Optional[str] = None
    creator_username: Optional[str] = None
    duration_seconds: Optional[int] = None
    # Podcast-specific
    show_name: Optional[str] = None
    episode_number: Optional[int] = None
    # Legacy X Spaces fields (for backward compatibility)
    host_username: Optional[str] = None
    host_display_name: Optional[str] = None


# Backward compatibility alias
SpaceInfo = ContentInfo


class DownloadJob(BaseModel):
    """Download job status response."""

    job_id: str
    status: JobStatus
    platform: Optional[Platform] = None
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    content_info: Optional[ContentInfo] = None
    # Legacy field for backward compatibility
    space_info: Optional[ContentInfo] = None
    download_url: Optional[str] = None
    file_path: Optional[str] = Field(
        default=None,
        description="Local file path where the download was saved",
    )
    file_size_mb: Optional[float] = None
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class MetadataResponse(BaseModel):
    """Response for content metadata lookup."""

    success: bool
    platform: Optional[Platform] = None
    content: Optional[ContentInfo] = None
    # Legacy field
    space: Optional[ContentInfo] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    platforms: dict[str, bool] = Field(
        default_factory=dict,
        description="Availability of each platform's dependencies",
    )
    ffmpeg_available: bool
    whisper_available: bool = False
    diarization_available: bool = False
    summarization_available: bool = False
    enhancement_available: bool = False
    version: str


# ============ Enhancement Schemas ============


class EnhancementPreset(str, Enum):
    """Audio enhancement presets."""

    NONE = "none"
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"


# ============ Transcription Schemas ============


class WhisperModelSize(str, Enum):
    """Available Whisper model sizes."""

    TINY = "tiny"
    BASE = "base"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE_V2 = "large-v2"
    LARGE_V3 = "large-v3"
    TURBO = "turbo"


class TranscriptionOutputFormat(str, Enum):
    """Output format for transcription."""

    TEXT = "text"
    SRT = "srt"
    VTT = "vtt"
    JSON = "json"
    DIALOGUE = "dialogue"  # Speaker-attributed dialogue format


class TranscribeRequest(BaseModel):
    """Request to transcribe audio."""

    url: Optional[str] = Field(
        default=None,
        description="URL to download and transcribe (X Spaces, YouTube, Podcast, etc.)",
    )
    job_id: Optional[str] = Field(
        default=None,
        description="Job ID of a completed download to transcribe",
    )
    language: Optional[str] = Field(
        default=None,
        description="Language code (e.g., 'en', 'zh', 'ja'). Auto-detect if not specified.",
    )
    model: WhisperModelSize = Field(
        default=WhisperModelSize.BASE,
        description="Whisper model size (larger = more accurate but slower)",
    )
    output_format: TranscriptionOutputFormat = Field(
        default=TranscriptionOutputFormat.TEXT,
        description="Output format for transcription",
    )
    translate: bool = Field(
        default=False,
        description="Translate to English (if source is non-English)",
    )
    diarize: bool = Field(
        default=False,
        description="Enable speaker diarization (identify different speakers)",
    )
    num_speakers: Optional[int] = Field(
        default=None,
        description="Exact number of speakers (if known, improves diarization accuracy)",
    )
    save_to: Optional[str] = Field(
        default=None,
        description="Path to save transcription output file. If not specified, results are only returned via API.",
    )
    keep_audio: bool = Field(
        default=False,
        description="Keep the downloaded audio file after transcription. Default is False (temp download).",
    )
    enhance: bool = Field(
        default=False,
        description="Apply audio enhancement (noise reduction, voice isolation) before transcription",
    )
    enhancement_preset: EnhancementPreset = Field(
        default=EnhancementPreset.MEDIUM,
        description="Audio enhancement preset: none, light, medium, or heavy",
    )
    keep_enhanced: bool = Field(
        default=False,
        description="Keep the enhanced audio file after transcription (only applies if enhance=True)",
    )


class TranscriptionSegment(BaseModel):
    """A segment of transcribed text with timestamps."""

    start: float = Field(description="Start time in seconds")
    end: float = Field(description="End time in seconds")
    text: str = Field(description="Transcribed text")
    speaker: Optional[str] = Field(
        default=None,
        description="Speaker label (e.g., 'SPEAKER_00') if diarization was enabled",
    )


class TranscriptionJob(BaseModel):
    """Transcription job status response."""

    job_id: str
    status: JobStatus
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    # Transcription results
    text: Optional[str] = None
    segments: Optional[list[TranscriptionSegment]] = None
    language: Optional[str] = None
    language_probability: Optional[float] = None
    duration_seconds: Optional[float] = None
    # Formatted output
    formatted_output: Optional[str] = None
    output_format: Optional[TranscriptionOutputFormat] = None
    # Metadata
    source_url: Optional[str] = None
    source_job_id: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    # Output file paths
    output_file: Optional[str] = Field(
        default=None,
        description="Path where transcription output was saved (if save_to was specified)",
    )
    audio_file: Optional[str] = Field(
        default=None,
        description="Path to audio file (if keep_audio was True)",
    )
    enhanced_file: Optional[str] = Field(
        default=None,
        description="Path to enhanced audio file (if enhance=True and keep_enhanced=True)",
    )


# ============ Transcript Fetch Schemas ============


class FetchTranscriptRequest(BaseModel):
    """Request to fetch an existing transcript from YouTube/Spotify."""

    url: str = Field(
        ...,
        description="YouTube or Spotify episode URL",
    )
    language: Optional[str] = Field(
        default=None,
        description="Preferred language code (e.g., 'en', 'zh'). Used for YouTube language selection.",
    )
    output_format: TranscriptionOutputFormat = Field(
        default=TranscriptionOutputFormat.TEXT,
        description="Output format for the fetched transcript",
    )


# ============ Summarization Schemas ============


class SummaryType(str, Enum):
    """Types of summaries that can be generated."""

    BULLET_POINTS = "bullet_points"
    CHAPTERS = "chapters"
    KEY_TOPICS = "key_topics"
    ACTION_ITEMS = "action_items"
    FULL = "full"


class LLMProvider(str, Enum):
    """Available LLM providers."""

    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GROQ = "groq"
    DEEPSEEK = "deepseek"
    CUSTOM = "custom"  # OpenAI-compatible endpoints


class SummarizeRequest(BaseModel):
    """Request to summarize text."""

    text: str = Field(
        ...,
        max_length=500_000,
        description="Text to summarize (typically a transcript)",
    )
    summary_type: SummaryType = Field(
        default=SummaryType.BULLET_POINTS,
        description="Type of summary to generate",
    )
    provider: Optional[LLMProvider] = Field(
        default=None,
        description="LLM provider to use. If not specified, uses configured default.",
    )
    model: Optional[str] = Field(
        default=None,
        description="Model to use. If not specified, uses configured default for the provider.",
    )


class SummarizeFromJobRequest(BaseModel):
    """Request to summarize a completed transcription job."""

    job_id: str = Field(
        ...,
        description="Job ID of a completed transcription to summarize",
    )
    summary_type: SummaryType = Field(
        default=SummaryType.BULLET_POINTS,
        description="Type of summary to generate",
    )


class SummaryResponse(BaseModel):
    """Response containing a generated summary."""

    summary_type: SummaryType
    content: str = Field(description="The generated summary")
    model: str = Field(description="Model used for generation")
    provider: str = Field(description="Provider used for generation")
    tokens_used: Optional[int] = Field(
        default=None,
        description="Number of tokens used for generation",
    )


# ============ Priority Queue Schemas ============


class PriorityUpdate(BaseModel):
    """Request to update job priority."""

    priority: int = Field(
        ...,
        ge=1,
        le=10,
        description="New priority level (1=low, 10=high)",
    )


class QueueStatus(BaseModel):
    """Current queue status."""

    pending: int = Field(description="Number of jobs waiting in queue")
    processing: int = Field(description="Number of jobs currently processing")
    max_concurrent: int = Field(description="Maximum concurrent jobs")
    processing_jobs: list[str] = Field(description="IDs of jobs being processed")
    jobs: list[dict] = Field(description="Jobs in queue with priority info")


# ============ Batch Schemas ============


class BatchDownloadRequest(BaseModel):
    """Request to create a batch download."""

    urls: list[str] = Field(
        ...,
        min_length=1,
        description="List of URLs to download",
    )
    name: Optional[str] = Field(
        default=None,
        description="Optional name for the batch",
    )
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Priority level for all jobs in batch",
    )
    format: OutputFormat = Field(
        default=OutputFormat.M4A,
        description="Output format for all downloads",
    )
    quality: QualityPreset = Field(
        default=QualityPreset.HIGH,
        description="Quality preset for all downloads",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        description="Webhook URL for batch completion notification",
    )


class BatchResponse(BaseModel):
    """Response for batch creation."""

    batch_id: str
    name: Optional[str]
    total_jobs: int
    job_ids: list[str]
    status: str
    created_at: datetime


class BatchStatus(BaseModel):
    """Batch status response."""

    batch_id: str
    name: Optional[str]
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    status: str
    webhook_url: Optional[str]
    created_at: datetime
    updated_at: datetime


# ============ Schedule Schemas ============


class ScheduleDownloadRequest(BaseModel):
    """Request to schedule a download."""

    url: str = Field(
        ...,
        description="URL to download",
    )
    scheduled_at: datetime = Field(
        ...,
        description="When to start the download (ISO format)",
    )
    platform: Platform = Field(
        default=Platform.AUTO,
        description="Platform (auto-detected if not specified)",
    )
    format: OutputFormat = Field(
        default=OutputFormat.M4A,
        description="Output format",
    )
    quality: QualityPreset = Field(
        default=QualityPreset.HIGH,
        description="Quality preset",
    )
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Priority level when scheduled time arrives",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        description="Webhook URL for completion notification",
    )


class ScheduledJob(BaseModel):
    """Scheduled job response."""

    job_id: str
    url: str
    scheduled_at: datetime
    priority: int
    status: str
    created_at: datetime


# ============ Webhook Schemas ============


class WebhookConfig(BaseModel):
    """Webhook configuration."""

    default_url: Optional[str] = Field(
        default=None,
        description="Default webhook URL for all jobs",
    )
    retry_attempts: int = Field(
        default=3,
        description="Number of retry attempts for failed webhooks",
    )
    retry_delay: int = Field(
        default=60,
        description="Delay between retries in seconds",
    )


class WebhookTestRequest(BaseModel):
    """Request to test a webhook."""

    url: str = Field(
        ...,
        max_length=2048,
        description="Webhook URL to test",
    )


class WebhookTestResponse(BaseModel):
    """Response from webhook test."""

    success: bool
    error: Optional[str] = None


# ============ Annotation Schemas ============


class CreateAnnotationRequest(BaseModel):
    """Request to create an annotation."""

    content: str = Field(
        ...,
        min_length=1,
        description="Annotation content",
    )
    user_id: str = Field(
        ...,
        description="ID of the user creating the annotation",
    )
    user_name: Optional[str] = Field(
        default=None,
        description="Display name of the user",
    )
    segment_start: Optional[float] = Field(
        default=None,
        ge=0,
        description="Start time of the transcript segment (seconds)",
    )
    segment_end: Optional[float] = Field(
        default=None,
        ge=0,
        description="End time of the transcript segment (seconds)",
    )
    parent_id: Optional[str] = Field(
        default=None,
        description="ID of parent annotation if this is a reply",
    )


class UpdateAnnotationRequest(BaseModel):
    """Request to update an annotation."""

    content: str = Field(
        ...,
        min_length=1,
        description="Updated annotation content",
    )


class AnnotationResponse(BaseModel):
    """Annotation response."""

    id: str
    job_id: str
    content: str
    user_id: str
    user_name: Optional[str] = None
    segment_start: Optional[float] = None
    segment_end: Optional[float] = None
    parent_id: Optional[str] = None
    replies: list["AnnotationResponse"] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# Fix forward reference for nested annotations
AnnotationResponse.model_rebuild()


# ============ AI Settings Schemas ============


class AIProvider(str, Enum):
    """Available AI providers for settings."""

    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GROQ = "groq"
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"
    CUSTOM = "custom"


class AISettingsRequest(BaseModel):
    """Request to save AI provider settings."""

    provider: AIProvider
    model: str = Field(
        ...,
        description="Model name/identifier",
    )
    api_key: Optional[str] = Field(
        default=None,
        description="API key for cloud providers",
    )
    base_url: Optional[str] = Field(
        default=None,
        description="Base URL for custom endpoints or Ollama",
    )


class AISettingsResponse(BaseModel):
    """Response containing current AI settings."""

    provider: AIProvider
    model: str
    base_url: Optional[str] = None
    has_api_key: bool = Field(
        description="Whether an API key is configured (key itself not exposed)"
    )


class AIProviderInfo(BaseModel):
    """Information about an AI provider."""

    name: str
    display_name: str
    models: list[str]
    requires_api_key: bool
    default_base_url: Optional[str] = None


class AIProvidersResponse(BaseModel):
    """Response containing all available AI providers."""

    providers: list[AIProviderInfo]


class AITestRequest(BaseModel):
    """Request to test AI provider connection."""

    provider: AIProvider
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class AITestResponse(BaseModel):
    """Response from AI provider connection test."""

    success: bool
    error: Optional[str] = None
    response_time_ms: Optional[float] = None
    response_preview: Optional[str] = Field(
        default=None,
        description="Preview of the model's response",
    )


# ============ Translation Schemas ============


class TranslatorType(str, Enum):
    """Available translator backends."""

    TRANSLATEGEMMA = "translategemma"  # Local Ollama TranslateGemma
    AI_PROVIDER = "ai_provider"  # Use configured AI provider (GPT-4, Claude, etc.)


class TranslateRequest(BaseModel):
    """Request to translate text."""

    text: str = Field(
        ...,
        min_length=1,
        max_length=500_000,
        description="Text to translate",
    )
    source_lang: str = Field(
        ...,
        description="Source language code (e.g., 'en', 'ja', 'zh-Hans') or name (e.g., 'English', 'Japanese')",
    )
    target_lang: str = Field(
        ...,
        description="Target language code or name",
    )
    translator: TranslatorType = Field(
        default=TranslatorType.TRANSLATEGEMMA,
        description="Which translator to use: 'translategemma' (local) or 'ai_provider' (configured AI)",
    )
    model: Optional[str] = Field(
        default=None,
        description="For TranslateGemma: '4b', '12b', '27b', or 'latest'. Ignored for ai_provider.",
    )


class TranslateFromJobRequest(BaseModel):
    """Request to translate a completed transcription."""

    job_id: str = Field(
        ...,
        description="Job ID of a completed transcription to translate",
    )
    target_lang: str = Field(
        ...,
        description="Target language code or name",
    )
    source_lang: Optional[str] = Field(
        default=None,
        description="Source language (auto-detected from transcription if not specified)",
    )
    model: Optional[str] = Field(
        default=None,
        description="TranslateGemma model size",
    )


class TranslateResponse(BaseModel):
    """Response containing translated text."""

    source_text: str = Field(description="Original text")
    translated_text: str = Field(description="Translated text")
    source_lang: str = Field(description="Source language code")
    target_lang: str = Field(description="Target language code")
    source_lang_name: str = Field(description="Source language name")
    target_lang_name: str = Field(description="Target language name")
    model: str = Field(description="Model used for translation")
    tokens_used: Optional[int] = Field(
        default=None,
        description="Number of tokens used",
    )


class LanguageInfo(BaseModel):
    """Information about a supported language."""

    code: str = Field(description="Language code (e.g., 'en', 'zh-Hans')")
    name: str = Field(description="Language name (e.g., 'English', 'Chinese (Simplified)')")


class SupportedLanguagesResponse(BaseModel):
    """Response containing all supported languages."""

    languages: list[LanguageInfo]
    total: int


# ============ Social Media Clip Schemas ============


class SocialPlatform(str, Enum):
    """Supported social media platforms."""

    TIKTOK = "tiktok"  # 9:16, max 180s
    INSTAGRAM_REELS = "reels"  # 9:16, max 90s
    YOUTUBE_SHORTS = "shorts"  # 9:16, max 60s
    TWITTER_X = "twitter"  # 16:9, max 140s


class GenerateClipsRequest(BaseModel):
    """Request to generate viral clip suggestions."""

    max_clips: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of clips to generate",
    )
    target_duration: Optional[int] = Field(
        default=None,
        ge=10,
        le=180,
        description="Target clip duration in seconds (optional)",
    )
    platforms: list[SocialPlatform] = Field(
        default=[
            SocialPlatform.TIKTOK,
            SocialPlatform.INSTAGRAM_REELS,
            SocialPlatform.YOUTUBE_SHORTS,
            SocialPlatform.TWITTER_X,
        ],
        description="Target social media platforms",
    )
    min_viral_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum viral score threshold (0.0-1.0)",
    )


class ClipSuggestionResponse(BaseModel):
    """A suggested viral clip with metadata."""

    clip_id: str = Field(description="Unique clip identifier")
    start_time: float = Field(description="Start time in seconds")
    end_time: float = Field(description="End time in seconds")
    duration: float = Field(description="Clip duration in seconds")
    transcript_text: str = Field(description="Transcript text for this segment")
    hook: str = Field(description="Opening hook for engagement")
    caption: str = Field(description="Social media caption")
    hashtags: list[str] = Field(description="Relevant hashtags")
    viral_score: float = Field(description="Viral potential score (0.0-1.0)")
    engagement_factors: dict[str, float] = Field(
        description="Engagement factor breakdown (humor, emotion, controversy, value, relatability)"
    )
    compatible_platforms: list[SocialPlatform] = Field(
        description="Compatible platforms based on duration"
    )
    exported_files: Optional[dict[str, str]] = Field(
        default=None,
        description="Exported file paths by platform",
    )


class ClipsResponse(BaseModel):
    """Response containing generated clips."""

    success: bool
    job_id: str
    clips: list[ClipSuggestionResponse]
    model: Optional[str] = None
    provider: Optional[str] = None
    tokens_used: Optional[int] = None
    error: Optional[str] = None


class ClipUpdateRequest(BaseModel):
    """Request to update clip boundaries or metadata."""

    start_time: Optional[float] = Field(
        default=None,
        ge=0,
        description="New start time in seconds",
    )
    end_time: Optional[float] = Field(
        default=None,
        ge=0,
        description="New end time in seconds",
    )
    hook: Optional[str] = Field(
        default=None,
        description="Updated opening hook",
    )
    caption: Optional[str] = Field(
        default=None,
        description="Updated social media caption",
    )
    hashtags: Optional[list[str]] = Field(
        default=None,
        description="Updated hashtags",
    )


class ClipExportRequest(BaseModel):
    """Request to export a clip for a platform."""

    platform: SocialPlatform = Field(
        description="Target social media platform",
    )
    quality: QualityPreset = Field(
        default=QualityPreset.HIGH,
        description="Audio quality preset",
    )
    format: OutputFormat = Field(
        default=OutputFormat.MP3,
        description="Output audio format",
    )


class ClipExportResponse(BaseModel):
    """Response from clip export."""

    success: bool
    clip_id: str
    platform: SocialPlatform
    file_path: Optional[str] = None
    file_size_mb: Optional[float] = None
    duration: Optional[float] = None
    format: Optional[str] = None
    error: Optional[str] = None


# ============ Sentiment Analysis Schemas ============


class AnalyzeSentimentRequest(BaseModel):
    """Request to analyze sentiment of a transcription."""

    window_size: int = Field(
        default=30,
        ge=10,
        le=120,
        description="Time window size in seconds for aggregation (default 30s)",
    )


class SentimentEmotions(BaseModel):
    """Emotion breakdown scores."""

    joy: float = Field(ge=0.0, le=1.0)
    anger: float = Field(ge=0.0, le=1.0)
    fear: float = Field(ge=0.0, le=1.0)
    surprise: float = Field(ge=0.0, le=1.0)
    sadness: float = Field(ge=0.0, le=1.0)


class SentimentSegmentResponse(BaseModel):
    """Sentiment analysis for a single segment."""

    segment_index: int
    start: float = Field(description="Start time in seconds")
    end: float = Field(description="End time in seconds")
    text: str
    polarity: float = Field(
        ge=-1.0,
        le=1.0,
        description="Sentiment polarity: -1.0 (negative) to 1.0 (positive)",
    )
    energy: str = Field(description="Energy level: aggressive, calm, or neutral")
    energy_score: float = Field(ge=0.0, le=1.0, description="Energy intensity 0-1")
    excitement: int = Field(ge=0, le=100, description="Excitement level 0-100")
    emotions: SentimentEmotions
    heat_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall emotional intensity 0-1",
    )
    is_heated: bool = Field(description="True if heat_score >= 0.6")
    speaker: Optional[str] = None


class TimeWindowResponse(BaseModel):
    """Aggregated sentiment for a time window."""

    window_index: int
    start: float
    end: float
    avg_polarity: float = Field(description="Average polarity in window")
    avg_heat_score: float = Field(description="Average heat score in window")
    dominant_emotion: str = Field(description="Most prominent emotion in window")
    segment_count: int = Field(description="Number of segments in window")


class PeakMomentResponse(BaseModel):
    """A peak emotional moment."""

    timestamp: float = Field(description="Timestamp in seconds")
    description: str = Field(description="Text snippet from the moment")
    heat_score: float = Field(description="Heat score of the moment")


class EmotionalArcResponse(BaseModel):
    """Overall emotional summary."""

    overall_sentiment: str = Field(
        description="Overall sentiment: positive, negative, neutral, or mixed"
    )
    avg_heat_score: float = Field(description="Average heat score across content")
    peak_moments: list[PeakMomentResponse] = Field(
        description="Top intense moments"
    )
    dominant_emotions: list[str] = Field(description="Top 3 dominant emotions")
    emotional_journey: str = Field(
        description="Narrative description of emotional progression"
    )
    total_heated_segments: int = Field(description="Number of heated segments")
    heated_percentage: float = Field(
        description="Percentage of segments that are heated"
    )


class SentimentResponse(BaseModel):
    """Complete sentiment analysis response."""

    success: bool
    job_id: str
    segments: list[SentimentSegmentResponse] = Field(default_factory=list)
    time_windows: list[TimeWindowResponse] = Field(default_factory=list)
    emotional_arc: Optional[EmotionalArcResponse] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    tokens_used: Optional[int] = None
    error: Optional[str] = None


class SentimentAvailabilityResponse(BaseModel):
    """Response for sentiment analysis availability check."""

    available: bool
    reason: Optional[str] = None
    has_transcript: bool
    has_segments: bool
    ai_available: bool


class HeatedMomentsResponse(BaseModel):
    """Response containing top heated moments."""

    job_id: str
    moments: list[SentimentSegmentResponse]
    total_heated: int


# ============ Obsidian Export Schemas ============


class ObsidianSettingsRequest(BaseModel):
    """Request to save Obsidian settings."""

    vault_path: str = Field(
        ...,
        description="Path to the Obsidian vault directory",
    )
    subfolder: Optional[str] = Field(
        default="AudioGrab",
        description="Subfolder within vault for exported notes",
    )
    template: Optional[str] = Field(
        default=None,
        description="Custom template for notes (not implemented yet)",
    )
    default_tags: Optional[list[str]] = Field(
        default=["audiograb", "transcript"],
        description="Default tags for exported notes",
    )


class ObsidianSettingsResponse(BaseModel):
    """Response containing Obsidian settings."""

    vault_path: str
    subfolder: str
    template: Optional[str] = None
    default_tags: list[str]
    is_configured: bool = Field(
        description="Whether Obsidian settings have been configured"
    )


class ObsidianExportRequest(BaseModel):
    """Request to export a transcription to Obsidian."""

    job_id: str = Field(
        ...,
        description="Job ID of a completed transcription to export",
    )
    title: Optional[str] = Field(
        default=None,
        description="Override auto-generated title",
    )
    tags: Optional[list[str]] = Field(
        default=None,
        description="Additional tags (merged with default tags)",
    )
    subfolder: Optional[str] = Field(
        default=None,
        description="Override default subfolder",
    )


class ObsidianExportResponse(BaseModel):
    """Response from Obsidian export."""

    success: bool
    file_path: Optional[str] = Field(
        default=None,
        description="Full path to the exported note",
    )
    note_name: Optional[str] = Field(
        default=None,
        description="Name of the exported note file",
    )
    error: Optional[str] = None


class ObsidianValidateResponse(BaseModel):
    """Response from vault validation."""

    valid: bool
    error: Optional[str] = None


# ============ Structured Data Extraction Schemas ============


class ExtractionPresetEnum(str, Enum):
    """Available extraction presets."""

    MEETING_NOTES = "meeting_notes"
    INTERVIEW = "interview"
    TUTORIAL = "tutorial"
    NEWS_ANALYSIS = "news_analysis"
    PRODUCT_REVIEW = "product_review"
    CUSTOM = "custom"


class ExtractRequest(BaseModel):
    """Request to extract structured data from a transcription."""

    preset: ExtractionPresetEnum = Field(
        ...,
        description="Extraction preset to use",
    )
    custom_schema: Optional[dict] = Field(
        default=None,
        description='Custom schema for "custom" preset. Example: {"fields": [{"name": "topics", "type": "list", "description": "Main topics"}]}',
    )


class ExtractedFieldResponse(BaseModel):
    """An individual extracted field."""

    key: str = Field(description="Field name")
    value: object = Field(description="Extracted value (string, list, or object)")
    field_type: str = Field(description="Type of value: string, list, object_list, object, number, boolean")


class ExtractionResponse(BaseModel):
    """Complete extraction response."""

    success: bool
    job_id: str
    preset: Optional[str] = None
    fields: list[ExtractedFieldResponse] = Field(default_factory=list)
    raw_output: Optional[str] = Field(
        default=None,
        description="Full JSON output as formatted string",
    )
    model: Optional[str] = None
    provider: Optional[str] = None
    tokens_used: Optional[int] = None
    error: Optional[str] = None


class ExtractionAvailabilityResponse(BaseModel):
    """Response for extraction availability check."""

    available: bool
    reason: Optional[str] = None
    has_transcript: bool
    ai_available: bool


class ExtractionPresetInfo(BaseModel):
    """Information about an extraction preset."""

    name: str = Field(description="Display name of the preset")
    value: str = Field(description="API value for the preset")
    description: str = Field(description="What this preset extracts")
    example_fields: list[str] = Field(description="Example field names")
