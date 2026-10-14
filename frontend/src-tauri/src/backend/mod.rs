pub mod db;
pub mod downloader;
pub mod platform;
pub mod routes;
pub mod spotify;
pub mod types;

use std::collections::HashMap;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::RwLock;
use axum::extract::Request;
use axum::http::{header, HeaderMap, HeaderValue, Method, StatusCode};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use tower_http::cors::CorsLayer;

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

    // CORS — restrict to the Tauri webview origin and the dev server only.
    // tauri://localhost on macOS/Linux, http(s)://tauri.localhost on Windows.
    let allowed_origins: Vec<HeaderValue> = [
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "http://localhost:5173",
    ]
    .iter()
    .filter_map(|o| o.parse().ok())
    .collect();

    let cors = CorsLayer::new()
        .allow_origin(allowed_origins)
        .allow_methods([Method::GET, Method::POST, Method::DELETE])
        .allow_headers([header::CONTENT_TYPE]);

    let app = create_router(state)
        .layer(cors)
        .layer(middleware::from_fn(local_only));

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

/// Browser origins of first-party clients: the webview, the dev server and
/// the browser extensions.
const TRUSTED_ORIGINS: [&str; 4] = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:5173",
];
const EXTENSION_SCHEMES: [&str; 3] =
    ["chrome-extension://", "moz-extension://", "safari-web-extension://"];

/// Hostname of a Host header value, without the port.
fn host_name(host: &str) -> &str {
    if let Some(rest) = host.strip_prefix('[') {
        return rest.split(']').next().unwrap_or("");
    }
    host.split(':').next().unwrap_or("")
}

fn is_loopback_host(host: &str) -> bool {
    matches!(
        host_name(host).to_ascii_lowercase().as_str(),
        "localhost" | "127.0.0.1" | "::1"
    )
}

/// True when a browser sent this request on behalf of another website.
///
/// CORS only stops such a page reading the response; a form POST, an
/// `<img>` GET or a navigation still reaches the handler. Clients that are
/// not browsers send neither header and are unaffected.
pub(crate) fn is_cross_site(headers: &HeaderMap) -> bool {
    let host = headers
        .get(header::HOST)
        .and_then(|h| h.to_str().ok())
        .unwrap_or("");
    if let Some(origin) = headers.get(header::ORIGIN) {
        let origin = origin.to_str().unwrap_or("null");
        let trusted = TRUSTED_ORIGINS.contains(&origin)
            || EXTENSION_SCHEMES.iter().any(|s| origin.starts_with(s))
            || origin
                .strip_prefix("http://")
                .is_some_and(|o| o.eq_ignore_ascii_case(host));
        return !trusted;
    }
    matches!(
        headers.get("sec-fetch-site").and_then(|v| v.to_str().ok()),
        Some("cross-site") | Some("same-site")
    )
}

/// Reject requests a website could make against this unauthenticated server.
///
/// - The Host must be a loopback name, so a DNS name rebound to 127.0.0.1
///   cannot reach it.
/// - State-changing requests must not come from another site.
async fn local_only(req: Request, next: Next) -> Response {
    let headers = req.headers();
    let host_ok = headers
        .get(header::HOST)
        .and_then(|h| h.to_str().ok())
        .is_some_and(is_loopback_host);
    if !host_ok {
        return (StatusCode::BAD_REQUEST, "Host not allowed").into_response();
    }
    let unsafe_method = !matches!(*req.method(), Method::GET | Method::HEAD | Method::OPTIONS);
    if unsafe_method && is_cross_site(headers) {
        return (StatusCode::FORBIDDEN, "Cross-origin request rejected").into_response();
    }
    next.run(req).await
}

#[cfg(test)]
mod tests {
    use super::*;

    fn headers(pairs: &[(&str, &str)]) -> HeaderMap {
        let mut h = HeaderMap::new();
        for (k, v) in pairs {
            h.insert(
                axum::http::HeaderName::from_bytes(k.as_bytes()).unwrap(),
                HeaderValue::from_str(v).unwrap(),
            );
        }
        h
    }

    #[test]
    fn loopback_hosts_only() {
        assert!(is_loopback_host("localhost:8000"));
        assert!(is_loopback_host("127.0.0.1:8000"));
        assert!(is_loopback_host("[::1]:8000"));
        assert!(!is_loopback_host("rebind.evil.example:8000"));
    }

    #[test]
    fn cross_site_detection() {
        let host = ("host", "localhost:8000");
        assert!(is_cross_site(&headers(&[host, ("origin", "https://evil.example")])));
        assert!(is_cross_site(&headers(&[host, ("origin", "null")])));
        assert!(is_cross_site(&headers(&[host, ("sec-fetch-site", "cross-site")])));
        assert!(!is_cross_site(&headers(&[host, ("origin", "tauri://localhost")])));
        assert!(!is_cross_site(&headers(&[host, ("origin", "chrome-extension://abc")])));
        assert!(!is_cross_site(&headers(&[host, ("origin", "http://localhost:8000")])));
        assert!(!is_cross_site(&headers(&[host])));
    }
}
