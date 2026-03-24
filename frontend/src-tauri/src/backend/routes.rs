use axum::{
    extract::{Path as AxumPath, Query, State},
    http::StatusCode,
    response::IntoResponse,
    routing::{delete, get, post},
    Json, Router,
};
use serde::Deserialize;
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::RwLock;

use super::db::JobStore;
use super::downloader;
use super::platform;
use super::types::*;

/// Shared application state.
pub struct AppState {
    pub jobs: RwLock<HashMap<String, DownloadJob>>,
    pub db: JobStore,
    pub download_dir: PathBuf,
}

pub fn create_router(state: Arc<AppState>) -> Router {
    Router::new()
        // Health & metadata
        .route("/api/health", get(health))
        .route("/api/readyz", get(readyz))
        .route("/api/platforms", get(platforms))
        // Download operations
        .route("/api/download", post(start_download))
        .route("/api/download/{job_id}", get(get_job))
        .route("/api/download/{job_id}", delete(delete_job))
        .route("/api/download/{job_id}/file", get(serve_file))
        // Job management
        .route("/api/jobs", get(list_jobs))
        .route("/api/queue", get(queue_status))
        // Quick add (browser extension)
        .route("/api/add", get(quick_add))
        .with_state(state)
}

// ─── Health ─────────────────────────────────────────────────────

async fn health() -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "status": "healthy",
        "platforms": {
            "x_spaces": platform::is_ytdlp_available(),
            "youtube": platform::is_ytdlp_available(),
            "youtube_video": platform::is_ytdlp_available(),
            "x_video": platform::is_ytdlp_available(),
            "instagram": platform::is_ytdlp_available(),
            "xiaohongshu": platform::is_ytdlp_available(),
            "apple_podcasts": true,
            "spotify": true,
            "xiaoyuzhou": true,
            "discord": true,
        },
        "ffmpeg_available": platform::is_ffmpeg_available(),
        "whisper_available": false,
        "diarization_available": false,
        "summarization_available": false,
        "enhancement_available": platform::is_ffmpeg_available(),
        "version": "0.2.0",
        "runtime": "rust",
    }))
}

async fn readyz(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    if state.download_dir.exists() {
        (StatusCode::OK, Json(serde_json::json!({"status": "ready"})))
    } else {
        (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(serde_json::json!({"status": "not_ready", "reason": "download directory not found"})),
        )
    }
}

async fn platforms() -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "audio": [
            {"name": "x_spaces", "available": platform::is_ytdlp_available()},
            {"name": "apple_podcasts", "available": true},
            {"name": "spotify", "available": true},
            {"name": "youtube", "available": platform::is_ytdlp_available()},
            {"name": "xiaoyuzhou", "available": true},
            {"name": "discord", "available": true},
        ],
        "video": [
            {"name": "x_video", "available": platform::is_ytdlp_available()},
            {"name": "youtube_video", "available": platform::is_ytdlp_available()},
            {"name": "instagram", "available": platform::is_ytdlp_available()},
            {"name": "xiaohongshu", "available": platform::is_ytdlp_available()},
        ]
    }))
}

// ─── Download ───────────────────────────────────────────────────

async fn start_download(
    State(state): State<Arc<AppState>>,
    Json(req): Json<DownloadRequest>,
) -> impl IntoResponse {
    // Validate URL
    if !req.url.starts_with("http://") && !req.url.starts_with("https://") {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": "URL must start with http:// or https://"})),
        );
    }

    // Detect platform
    let detected = if req.platform == Platform::Auto {
        match platform::detect_platform(&req.url) {
            Some(p) => p,
            None => {
                return (
                    StatusCode::BAD_REQUEST,
                    Json(serde_json::json!({"error": "Unsupported URL — could not detect platform"})),
                );
            }
        }
    } else {
        req.platform
    };

    // Create job
    let job_id = uuid::Uuid::new_v4().to_string();
    let mut job = DownloadJob::new(job_id.clone(), Some(detected));

    // Store in-memory
    {
        let mut jobs = state.jobs.write().await;
        jobs.insert(job_id.clone(), job.clone());
    }

    // Spawn background download task
    let state_clone = Arc::clone(&state);
    let url = req.url.clone();
    let format = req.format;
    let quality = req.quality;
    let download_dir = state.download_dir.clone();

    tokio::spawn(async move {
        // Mark as processing
        {
            let mut jobs = state_clone.jobs.write().await;
            if let Some(j) = jobs.get_mut(&job_id) {
                j.status = JobStatus::Processing;
                j.progress = 0.1;
            }
        }

        // Execute download
        let result = downloader::execute_download(
            &url,
            &download_dir,
            format,
            quality,
            detected,
        )
        .await;

        // Update job with result
        {
            let mut jobs = state_clone.jobs.write().await;
            if let Some(j) = jobs.get_mut(&job_id) {
                if result.success {
                    j.status = JobStatus::Completed;
                    j.progress = 1.0;
                    j.file_path = result.file_path;
                    j.content_info = result.metadata;
                    j.file_size_mb = result
                        .file_size_bytes
                        .map(|b| b as f64 / 1024.0 / 1024.0);
                    j.download_url = Some(format!("/api/download/{}/file", j.job_id));
                    j.completed_at = Some(chrono::Utc::now());
                } else {
                    j.status = JobStatus::Failed;
                    j.error = result.error;
                }

                // Persist to SQLite
                let _ = state_clone.db.save_job(j, &url);
            }
        }
    });

    // Return job immediately
    job.status = JobStatus::Pending;
    (StatusCode::OK, Json(serde_json::to_value(&job).unwrap()))
}

async fn get_job(
    State(state): State<Arc<AppState>>,
    AxumPath(job_id): AxumPath<String>,
) -> impl IntoResponse {
    let jobs = state.jobs.read().await;
    match jobs.get(&job_id) {
        Some(job) => (StatusCode::OK, Json(serde_json::to_value(job).unwrap())),
        None => (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"error": "Job not found"})),
        ),
    }
}

async fn delete_job(
    State(state): State<Arc<AppState>>,
    AxumPath(job_id): AxumPath<String>,
) -> impl IntoResponse {
    let mut jobs = state.jobs.write().await;
    if let Some(job) = jobs.remove(&job_id) {
        // Delete the file if it exists
        if let Some(ref path) = job.file_path {
            let _ = tokio::fs::remove_file(path).await;
        }
        let _ = state.db.delete_job(&job_id);
        (
            StatusCode::OK,
            Json(serde_json::json!({"status": "deleted", "job_id": job_id})),
        )
    } else {
        (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"error": "Job not found"})),
        )
    }
}

async fn serve_file(
    State(state): State<Arc<AppState>>,
    AxumPath(job_id): AxumPath<String>,
) -> impl IntoResponse {
    let jobs = state.jobs.read().await;
    let job = match jobs.get(&job_id) {
        Some(j) => j,
        None => {
            return Err((
                StatusCode::NOT_FOUND,
                Json(serde_json::json!({"error": "Job not found"})),
            ));
        }
    };

    if job.status != JobStatus::Completed {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": "Job not completed yet"})),
        ));
    }

    let file_path = match &job.file_path {
        Some(p) => PathBuf::from(p),
        None => {
            return Err((
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({"error": "File path missing"})),
            ));
        }
    };

    if !file_path.exists() {
        return Err((
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"error": "File not found on disk"})),
        ));
    }

    let mime = mime_guess::from_path(&file_path)
        .first_or_octet_stream()
        .to_string();

    let filename = file_path
        .file_name()
        .unwrap_or_default()
        .to_string_lossy()
        .to_string();

    let bytes = tokio::fs::read(&file_path).await.map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": format!("Failed to read file: {}", e)})),
        )
    })?;

    Ok((
        [
            ("content-type", mime),
            (
                "content-disposition",
                format!("attachment; filename=\"{}\"", filename),
            ),
        ],
        bytes,
    ))
}

// ─── Jobs ───────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct JobsQuery {
    status: Option<String>,
    limit: Option<usize>,
}

async fn list_jobs(
    State(state): State<Arc<AppState>>,
    Query(query): Query<JobsQuery>,
) -> Json<serde_json::Value> {
    let limit = query.limit.unwrap_or(50);

    // First return in-memory jobs, then fall back to DB
    let jobs = state.jobs.read().await;
    let mut result: Vec<serde_json::Value> = jobs
        .values()
        .filter(|j| {
            query
                .status
                .as_ref()
                .map_or(true, |s| j.status.to_string() == *s)
        })
        .take(limit)
        .map(|j| serde_json::to_value(j).unwrap())
        .collect();

    // If we have fewer than limit, supplement from DB
    if result.len() < limit {
        if let Ok(db_jobs) = state.db.get_jobs(query.status.as_deref(), limit - result.len()) {
            for dj in db_jobs {
                let db_id = dj.get("job_id").and_then(|v| v.as_str()).unwrap_or("");
                if !jobs.contains_key(db_id) {
                    result.push(dj);
                }
            }
        }
    }

    Json(serde_json::json!({
        "jobs": result,
        "total": result.len(),
    }))
}

async fn queue_status(State(state): State<Arc<AppState>>) -> Json<QueueStatus> {
    let jobs = state.jobs.read().await;
    let mut qs = QueueStatus {
        pending: 0,
        processing: 0,
        completed: 0,
        failed: 0,
        total: jobs.len(),
    };

    for job in jobs.values() {
        match job.status {
            JobStatus::Pending => qs.pending += 1,
            JobStatus::Processing => qs.processing += 1,
            JobStatus::Completed => qs.completed += 1,
            JobStatus::Failed => qs.failed += 1,
        }
    }

    Json(qs)
}

// ─── Quick Add (Browser Extension) ─────────────────────────────

#[derive(Debug, Deserialize)]
struct QuickAddQuery {
    url: String,
    action: Option<String>,
}

async fn quick_add(
    State(state): State<Arc<AppState>>,
    Query(query): Query<QuickAddQuery>,
) -> impl IntoResponse {
    let req = DownloadRequest {
        url: query.url,
        platform: Platform::Auto,
        format: OutputFormat::default(),
        quality: QualityPreset::default(),
        embed_metadata: true,
        output_dir: None,
        keep_file: true,
        priority: 5,
        webhook_url: None,
    };

    start_download(State(state), Json(req)).await
}
