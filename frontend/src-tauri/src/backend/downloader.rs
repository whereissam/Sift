use std::path::{Path, PathBuf};
use std::process::Stdio;
use tokio::process::Command;

use super::platform;
use super::types::*;

/// Resolve the full path to yt-dlp binary.
/// macOS apps launched from Finder don't inherit shell PATH,
/// so we check common Homebrew/system locations as fallback.
fn find_ytdlp() -> String {
    if let Ok(path) = which::which("yt-dlp") {
        return path.to_string_lossy().to_string();
    }
    // Common fallback locations
    for candidate in &[
        "/opt/homebrew/bin/yt-dlp",
        "/usr/local/bin/yt-dlp",
        "/usr/bin/yt-dlp",
    ] {
        if std::path::Path::new(candidate).exists() {
            return candidate.to_string();
        }
    }
    "yt-dlp".to_string()
}

/// Build a PATH that includes common binary locations.
fn extended_path() -> String {
    let base = std::env::var("PATH").unwrap_or_default();
    format!("/opt/homebrew/bin:/usr/local/bin:{}", base)
}

/// Build yt-dlp command for audio downloads.
fn build_audio_cmd(
    url: &str,
    output_dir: &Path,
    format: OutputFormat,
    quality: QualityPreset,
    platform_type: Platform,
) -> Vec<String> {
    let output_template = output_dir
        .join("%(title)s [%(id)s].%(ext)s")
        .to_string_lossy()
        .to_string();

    let download_format = match format {
        OutputFormat::Mp3 => "mp3",
        _ => "m4a",
    };

    let mut cmd = vec![
        find_ytdlp(),
        "--no-progress".to_string(),
        "-x".to_string(),
        "--audio-format".to_string(),
        download_format.to_string(),
        "-o".to_string(),
        output_template,
        "--print-json".to_string(),
        // Parallel fragment downloads
        "--concurrent-fragments".to_string(),
        "16".to_string(),
        "--fragment-retries".to_string(),
        "5".to_string(),
        "--socket-timeout".to_string(),
        "30".to_string(),
    ];

    // Quality for mp3
    if format == OutputFormat::Mp3 {
        let bitrate = match quality {
            QualityPreset::Low => "64K",
            QualityPreset::Medium => "128K",
            QualityPreset::High => "192K",
            QualityPreset::Highest => "320K",
        };
        cmd.extend(["--audio-quality".to_string(), bitrate.to_string()]);
    }

    // YouTube-specific workaround
    if matches!(platform_type, Platform::Youtube | Platform::YoutubeVideo) {
        cmd.extend([
            "--extractor-args".to_string(),
            "youtube:player_client=web".to_string(),
        ]);
    }

    cmd.push(url.to_string());
    cmd
}

/// Build yt-dlp command for video downloads.
fn build_video_cmd(
    url: &str,
    output_dir: &Path,
    quality: QualityPreset,
    platform_type: Platform,
) -> Vec<String> {
    let output_template = output_dir
        .join("%(title)s [%(id)s].%(ext)s")
        .to_string_lossy()
        .to_string();

    let format_spec = match quality {
        QualityPreset::Low => "best[height<=360][ext=mp4]/best[height<=360]",
        QualityPreset::Medium => "best[height<=480][ext=mp4]/best[height<=480]",
        QualityPreset::High => "bestvideo[height<=720]+bestaudio/best[height<=720]",
        QualityPreset::Highest => "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
    };

    let mut cmd = vec![
        find_ytdlp(),
        "--no-progress".to_string(),
        "-f".to_string(),
        format_spec.to_string(),
        "-o".to_string(),
        output_template,
        "--print-json".to_string(),
        "--merge-output-format".to_string(),
        "mp4".to_string(),
        "--concurrent-fragments".to_string(),
        "16".to_string(),
        "--fragment-retries".to_string(),
        "5".to_string(),
    ];

    // YouTube-specific
    if matches!(platform_type, Platform::YoutubeVideo) {
        cmd.extend([
            "--extractor-args".to_string(),
            "youtube:player_client=web".to_string(),
            "--force-overwrites".to_string(),
        ]);
    }

    // Instagram-specific
    if matches!(platform_type, Platform::Instagram) {
        cmd.extend([
            "--recode-video".to_string(),
            "mp4".to_string(),
            "--add-header".to_string(),
            "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36".to_string(),
        ]);
    }

    // Xiaohongshu-specific
    if matches!(platform_type, Platform::Xiaohongshu) {
        cmd.extend([
            "--recode-video".to_string(),
            "mp4".to_string(),
            "--add-header".to_string(),
            "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36".to_string(),
            "--add-header".to_string(),
            "Referer:https://www.xiaohongshu.com/".to_string(),
        ]);
    }

    cmd.push(url.to_string());
    cmd
}

/// Run yt-dlp and parse the result.
pub async fn execute_download(
    url: &str,
    output_dir: &Path,
    format: OutputFormat,
    quality: QualityPreset,
    detected_platform: Platform,
) -> DownloadResult {
    // Ensure output directory exists
    if let Err(e) = tokio::fs::create_dir_all(output_dir).await {
        return DownloadResult {
            success: false,
            file_path: None,
            metadata: None,
            error: Some(format!("Failed to create output directory: {}", e)),
            file_size_bytes: None,
        };
    }

    let is_video = matches!(
        detected_platform,
        Platform::XVideo | Platform::YoutubeVideo | Platform::Instagram | Platform::Xiaohongshu
    ) || matches!(format, OutputFormat::Mp4);

    let args = if is_video {
        build_video_cmd(url, output_dir, quality, detected_platform)
    } else {
        build_audio_cmd(url, output_dir, format, quality, detected_platform)
    };

    log::info!("yt-dlp resolved to: {}", args[0]);
    log::info!("PATH: {}", extended_path());
    log::info!("Running: {} ...", args[..3.min(args.len())].join(" "));

    // Run via /bin/sh to ensure shebangs and PATH resolve correctly.
    // Tauri's sandboxed environment may not handle Python script shebangs.
    let shell_cmd = args
        .iter()
        .map(|a| shell_escape::escape(std::borrow::Cow::Borrowed(a.as_str())).to_string())
        .collect::<Vec<_>>()
        .join(" ");

    let output = match Command::new("/bin/sh")
        .arg("-c")
        .arg(&shell_cmd)
        .env("PATH", extended_path())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(child) => match child.wait_with_output().await {
            Ok(output) => output,
            Err(e) => {
                return DownloadResult {
                    success: false,
                    file_path: None,
                    metadata: None,
                    error: Some(format!("yt-dlp process error: {}", e)),
                    file_size_bytes: None,
                };
            }
        },
        Err(e) => {
            return DownloadResult {
                success: false,
                file_path: None,
                metadata: None,
                error: Some(format!("Failed to spawn yt-dlp: {}. Is it installed?", e)),
                file_size_bytes: None,
            };
        }
    };

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return DownloadResult {
            success: false,
            file_path: None,
            metadata: None,
            error: Some(format!("yt-dlp failed: {}", &stderr[..stderr.len().min(500)])),
            file_size_bytes: None,
        };
    }

    // Parse JSON output from yt-dlp
    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut file_path: Option<PathBuf> = None;
    let mut metadata: Option<ContentInfo> = None;

    for line in stdout.lines() {
        if line.starts_with('{') {
            if let Ok(data) = serde_json::from_str::<serde_json::Value>(line) {
                // Extract file path
                let fp = data
                    .get("_filename")
                    .or_else(|| data.get("filename"))
                    .and_then(|v| v.as_str())
                    .map(PathBuf::from);

                if let Some(ref p) = fp {
                    if p.exists() {
                        file_path = fp;
                    }
                }

                let content_id = data.get("id").and_then(|v| v.as_str()).unwrap_or("unknown");
                let title = data
                    .get("title")
                    .and_then(|v| v.as_str())
                    .unwrap_or("Unknown");

                metadata = Some(ContentInfo {
                    platform: detected_platform,
                    content_id: content_id.to_string(),
                    title: title.to_string(),
                    creator_name: data.get("uploader").and_then(|v| v.as_str()).map(String::from),
                    creator_username: data
                        .get("uploader_id")
                        .and_then(|v| v.as_str())
                        .map(String::from),
                    duration_seconds: data.get("duration").and_then(|v| v.as_f64()),
                });
                break;
            }
        }
    }

    // If file not found from JSON, search the output directory
    if file_path.is_none() || !file_path.as_ref().map_or(false, |p| p.exists()) {
        let content_id = platform::extract_content_id(url, detected_platform).unwrap_or_default();
        let extensions = [".m4a", ".mp3", ".mp4", ".aac", ".webm"];
        if let Ok(entries) = std::fs::read_dir(output_dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                let name = path.file_name().unwrap_or_default().to_string_lossy();
                if !content_id.is_empty() && name.contains(&content_id) {
                    if extensions.iter().any(|ext| name.ends_with(ext)) {
                        file_path = Some(path);
                        break;
                    }
                }
            }
        }
    }

    match file_path {
        Some(ref fp) if fp.exists() => {
            let file_size = fp.metadata().map(|m| m.len()).ok();
            DownloadResult {
                success: true,
                file_path: Some(fp.to_string_lossy().to_string()),
                metadata,
                error: None,
                file_size_bytes: file_size,
            }
        }
        _ => DownloadResult {
            success: false,
            file_path: None,
            metadata,
            error: Some("Download completed but output file not found".to_string()),
            file_size_bytes: None,
        },
    }
}
