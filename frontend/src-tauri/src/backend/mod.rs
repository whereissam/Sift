pub mod db;
pub mod downloader;
pub mod platform;
pub mod routes;
pub mod types;

use std::collections::HashMap;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::RwLock;
use tower_http::cors::{Any, CorsLayer};

use db::JobStore;
use routes::{create_router, AppState};

/// Start the embedded axum HTTP server.
/// This replaces the Python FastAPI backend entirely.
pub async fn start_server(download_dir: PathBuf, port: u16) -> Result<(), String> {
    // Ensure download directory exists
    std::fs::create_dir_all(&download_dir)
        .map_err(|e| format!("Failed to create download dir: {}", e))?;

    // Initialize SQLite
    let db_path = download_dir.join("jobs.db");
    let db = JobStore::new(&db_path)?;

    // Shared state
    let state = Arc::new(AppState {
        jobs: RwLock::new(HashMap::new()),
        db,
        download_dir,
    });

    // CORS — allow the Tauri webview and dev server
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    let app = create_router(state).layer(cors);

    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    log::info!("Rust backend starting on http://{}", addr);

    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .map_err(|e| format!("Failed to bind to port {}: {}", port, e))?;

    axum::serve(listener, app)
        .await
        .map_err(|e| format!("Server error: {}", e))?;

    Ok(())
}
