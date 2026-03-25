use regex::Regex;
use std::sync::LazyLock;

use super::types::Platform;

struct PlatformPattern {
    platform: Platform,
    patterns: Vec<Regex>,
}

static PLATFORM_PATTERNS: LazyLock<Vec<PlatformPattern>> = LazyLock::new(|| {
    vec![
        PlatformPattern {
            platform: Platform::XSpaces,
            patterns: vec![
                Regex::new(r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/i/spaces/([a-zA-Z0-9]+)").unwrap(),
                Regex::new(r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/spaces/([a-zA-Z0-9]+)").unwrap(),
            ],
        },
        PlatformPattern {
            platform: Platform::XVideo,
            patterns: vec![
                Regex::new(r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/\w+/status/(\d+)").unwrap(),
            ],
        },
        PlatformPattern {
            platform: Platform::YoutubeVideo,
            patterns: vec![
                // YouTube video URLs — detected as video first, audio uses Youtube variant
                Regex::new(r"(?:https?://)?(?:www\.)?(?:youtube\.com|youtu\.be)/").unwrap(),
            ],
        },
        PlatformPattern {
            platform: Platform::ApplePodcasts,
            patterns: vec![
                Regex::new(r"(?:https?://)?(?:www\.)?podcasts\.apple\.com/").unwrap(),
            ],
        },
        PlatformPattern {
            platform: Platform::Spotify,
            patterns: vec![
                Regex::new(r"(?:https?://)?(?:www\.)?open\.spotify\.com/").unwrap(),
            ],
        },
        PlatformPattern {
            platform: Platform::Xiaoyuzhou,
            patterns: vec![
                Regex::new(r"(?:https?://)?(?:www\.)?xiaoyuzhoufm\.com/episode/").unwrap(),
            ],
        },
        PlatformPattern {
            platform: Platform::Discord,
            patterns: vec![
                Regex::new(r"(?:https?://)?cdn\.discordapp\.com/attachments/").unwrap(),
            ],
        },
        PlatformPattern {
            platform: Platform::Instagram,
            patterns: vec![
                Regex::new(r"(?:https?://)?(?:www\.)?instagram\.com/(?:reel|p)/").unwrap(),
            ],
        },
        PlatformPattern {
            platform: Platform::Xiaohongshu,
            patterns: vec![
                Regex::new(r"(?:https?://)?(?:www\.)?xiaohongshu\.com/").unwrap(),
                Regex::new(r"(?:https?://)?xhslink\.com/").unwrap(),
            ],
        },
    ]
});

/// Detect platform from a URL. Returns None if no platform matches.
pub fn detect_platform(url: &str) -> Option<Platform> {
    for pp in PLATFORM_PATTERNS.iter() {
        for pattern in &pp.patterns {
            if pattern.is_match(url) {
                return Some(pp.platform);
            }
        }
    }
    None
}

/// Extract content ID from a URL for a given platform.
pub fn extract_content_id(url: &str, platform: Platform) -> Option<String> {
    match platform {
        Platform::XSpaces => {
            let re = Regex::new(r"(?:twitter\.com|x\.com)/(?:i/)?spaces/([a-zA-Z0-9]+)").unwrap();
            re.captures(url).map(|c| c[1].to_string())
        }
        Platform::XVideo => {
            let re = Regex::new(r"(?:twitter\.com|x\.com)/\w+/status/(\d+)").unwrap();
            re.captures(url).map(|c| c[1].to_string())
        }
        Platform::YoutubeVideo | Platform::Youtube => {
            let re = Regex::new(r"(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]+)").unwrap();
            re.captures(url).map(|c| c[1].to_string())
        }
        Platform::Instagram => {
            let re = Regex::new(r"instagram\.com/(?:reel|p)/([a-zA-Z0-9_-]+)").unwrap();
            re.captures(url).map(|c| c[1].to_string())
        }
        Platform::Xiaohongshu => {
            let re = Regex::new(r"xiaohongshu\.com/(?:explore|discovery/item)/([a-zA-Z0-9]+)").unwrap();
            re.captures(url).map(|c| c[1].to_string())
        }
        _ => {
            // For other platforms, use the full URL as the content ID
            Some(url.to_string())
        }
    }
}

/// Check if yt-dlp is available (PATH + common locations).
pub fn is_ytdlp_available() -> bool {
    which::which("yt-dlp").is_ok()
        || std::path::Path::new("/opt/homebrew/bin/yt-dlp").exists()
        || std::path::Path::new("/usr/local/bin/yt-dlp").exists()
}

/// Check if ffmpeg is available (PATH + common locations).
pub fn is_ffmpeg_available() -> bool {
    which::which("ffmpeg").is_ok()
        || std::path::Path::new("/opt/homebrew/bin/ffmpeg").exists()
        || std::path::Path::new("/usr/local/bin/ffmpeg").exists()
}
