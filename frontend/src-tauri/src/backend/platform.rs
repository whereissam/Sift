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

/// Hosts each platform serves from; subdomains match too.
fn platform_hosts(platform: Platform) -> &'static [&'static str] {
    match platform {
        Platform::XSpaces | Platform::XVideo => &["x.com", "twitter.com"],
        Platform::Youtube | Platform::YoutubeVideo => &["youtube.com", "youtu.be"],
        Platform::ApplePodcasts => &["podcasts.apple.com"],
        Platform::Spotify => &["open.spotify.com"],
        Platform::Xiaoyuzhou => &["xiaoyuzhoufm.com"],
        Platform::Discord => &["cdn.discordapp.com", "media.discordapp.net"],
        Platform::Instagram => &["instagram.com"],
        Platform::Xiaohongshu => &["xiaohongshu.com", "xhslink.com"],
        Platform::Auto => &[],
    }
}

/// The lowercased host of an http(s) URL, or None for anything else.
///
/// The patterns below match a platform domain anywhere in the string, so
/// on their own they accept e.g. `http://10.0.0.1/youtube.com/watch?v=…`
/// and yt-dlp then fetches the internal host.
fn http_host(url: &str) -> Option<String> {
    if url.starts_with('-')
        || url.contains('\\')
        || url.chars().any(|c| c.is_whitespace() || c.is_control())
    {
        return None;
    }
    let with_scheme;
    let url = if url.contains("://") {
        url
    } else {
        with_scheme = format!("https://{url}");
        &with_scheme
    };
    let parsed = reqwest::Url::parse(url).ok()?;
    if !matches!(parsed.scheme(), "http" | "https") {
        return None;
    }
    Some(parsed.host_str()?.trim_end_matches('.').to_ascii_lowercase())
}

/// True when `url` is an http(s) URL on one of `platform`'s hosts.
pub fn url_matches_platform(url: &str, platform: Platform) -> bool {
    let Some(host) = http_host(url) else {
        return false;
    };
    platform_hosts(platform)
        .iter()
        .any(|d| host == *d || host.ends_with(&format!(".{d}")))
}

/// Detect platform from a URL. Returns None if no platform matches.
pub fn detect_platform(url: &str) -> Option<Platform> {
    for pp in PLATFORM_PATTERNS.iter() {
        if !url_matches_platform(url, pp.platform) {
            continue;
        }
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn real_platform_urls_are_detected() {
        assert_eq!(
            detect_platform("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            Some(Platform::YoutubeVideo)
        );
        assert_eq!(
            detect_platform("https://x.com/i/spaces/1abcdefghij"),
            Some(Platform::XSpaces)
        );
        assert_eq!(
            detect_platform("https://cdn.discordapp.com/attachments/1/2/a.mp3"),
            Some(Platform::Discord)
        );
        assert_eq!(
            detect_platform("youtube.com/watch?v=dQw4w9WgXcQ"),
            Some(Platform::YoutubeVideo)
        );
    }

    #[test]
    fn foreign_hosts_and_option_shaped_input_are_rejected() {
        for url in [
            "http://127.0.0.1:18080/youtube.com/watch?v=aaaaaaaaaaa",
            "https://attacker.example/cdn.discordapp.com/attachments/1/2/a.mp3",
            "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com@evil.example/watch?v=dQw4w9WgXcQ",
            "https://evil.example\\@www.youtube.com/watch?v=dQw4w9WgXcQ",
            "--config-location=/tmp/x/xiaohongshu.com/",
            "file:///youtube.com/watch?v=dQw4w9WgXcQ",
        ] {
            assert_eq!(detect_platform(url), None, "{url}");
        }
    }

    #[test]
    fn explicit_platform_still_checks_the_host() {
        assert!(url_matches_platform("https://youtu.be/dQw4w9WgXcQ", Platform::Youtube));
        assert!(!url_matches_platform("http://10.0.0.1/x", Platform::Youtube));
    }
}
