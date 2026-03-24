use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Supported platforms for audio/video download.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Platform {
    // Audio
    XSpaces,
    ApplePodcasts,
    Spotify,
    Youtube,
    Xiaoyuzhou,
    Discord,
    // Video
    XVideo,
    YoutubeVideo,
    Instagram,
    Xiaohongshu,
    // Auto-detect
    Auto,
}

impl std::fmt::Display for Platform {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            Self::XSpaces => "x_spaces",
            Self::ApplePodcasts => "apple_podcasts",
            Self::Spotify => "spotify",
            Self::Youtube => "youtube",
            Self::Xiaoyuzhou => "xiaoyuzhou",
            Self::Discord => "discord",
            Self::XVideo => "x_video",
            Self::YoutubeVideo => "youtube_video",
            Self::Instagram => "instagram",
            Self::Xiaohongshu => "xiaohongshu",
            Self::Auto => "auto",
        };
        write!(f, "{}", s)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OutputFormat {
    M4a,
    Mp3,
    Mp4,
    Aac,
}

impl Default for OutputFormat {
    fn default() -> Self {
        Self::M4a
    }
}

impl std::fmt::Display for OutputFormat {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            Self::M4a => "m4a",
            Self::Mp3 => "mp3",
            Self::Mp4 => "mp4",
            Self::Aac => "aac",
        };
        write!(f, "{}", s)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum QualityPreset {
    Low,
    Medium,
    High,
    Highest,
}

impl Default for QualityPreset {
    fn default() -> Self {
        Self::High
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum JobStatus {
    Pending,
    Processing,
    Completed,
    Failed,
}

impl std::fmt::Display for JobStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            Self::Pending => "pending",
            Self::Processing => "processing",
            Self::Completed => "completed",
            Self::Failed => "failed",
        };
        write!(f, "{}", s)
    }
}

/// Incoming download request from the frontend.
#[derive(Debug, Clone, Deserialize)]
pub struct DownloadRequest {
    pub url: String,
    #[serde(default = "default_platform")]
    pub platform: Platform,
    #[serde(default)]
    pub format: OutputFormat,
    #[serde(default)]
    pub quality: QualityPreset,
    #[serde(default = "default_true")]
    pub embed_metadata: bool,
    pub output_dir: Option<String>,
    #[serde(default = "default_true")]
    pub keep_file: bool,
    #[serde(default = "default_priority")]
    pub priority: i32,
    pub webhook_url: Option<String>,
}

fn default_platform() -> Platform {
    Platform::Auto
}

fn default_true() -> bool {
    true
}

fn default_priority() -> i32 {
    5
}

/// Metadata extracted from downloaded content.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContentInfo {
    pub platform: Platform,
    pub content_id: String,
    pub title: String,
    pub creator_name: Option<String>,
    pub creator_username: Option<String>,
    pub duration_seconds: Option<f64>,
}

/// A download job tracked by the system.
#[derive(Debug, Clone, Serialize)]
pub struct DownloadJob {
    pub job_id: String,
    pub status: JobStatus,
    pub platform: Option<Platform>,
    pub progress: f64,
    pub content_info: Option<ContentInfo>,
    pub download_url: Option<String>,
    pub file_path: Option<String>,
    pub file_size_mb: Option<f64>,
    pub error: Option<String>,
    pub created_at: DateTime<Utc>,
    pub completed_at: Option<DateTime<Utc>>,
}

impl DownloadJob {
    pub fn new(job_id: String, platform: Option<Platform>) -> Self {
        Self {
            job_id,
            status: JobStatus::Pending,
            platform,
            progress: 0.0,
            content_info: None,
            download_url: None,
            file_path: None,
            file_size_mb: None,
            error: None,
            created_at: Utc::now(),
            completed_at: None,
        }
    }
}

/// Result from a platform downloader subprocess.
#[derive(Debug)]
pub struct DownloadResult {
    pub success: bool,
    pub file_path: Option<String>,
    pub metadata: Option<ContentInfo>,
    pub error: Option<String>,
    pub file_size_bytes: Option<u64>,
}

/// Queue status response.
#[derive(Debug, Serialize)]
pub struct QueueStatus {
    pub pending: usize,
    pub processing: usize,
    pub completed: usize,
    pub failed: usize,
    pub total: usize,
}
