mod backend;

use std::path::PathBuf;
use tauri::{Emitter, Manager};

/// Get the default download directory.
fn default_download_dir() -> PathBuf {
    dirs_next().unwrap_or_else(|| PathBuf::from("./output"))
}

fn dirs_next() -> Option<PathBuf> {
    // Use ~/Sift as the default download location
    dirs::home_dir().map(|h| h.join("Sift").join("output"))
}

#[tauri::command]
async fn check_backend_health() -> Result<bool, String> {
    let client = reqwest::Client::new();
    match client.get("http://localhost:8000/api/health").send().await {
        Ok(resp) => Ok(resp.status().is_success()),
        Err(_) => Ok(false),
    }
}

#[tauri::command]
async fn get_backend_url() -> Result<String, String> {
    Ok("http://localhost:8000".to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            check_backend_health,
            get_backend_url,
        ])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            let download_dir = default_download_dir();
            let app_handle = app.handle().clone();

            // Start the Rust backend server in a background task
            tauri::async_runtime::spawn(async move {
                if let Err(e) = backend::start_server(download_dir, 8000).await {
                    log::error!("Backend server failed: {}", e);
                    let _ = app_handle.emit("backend-terminated", e.to_string());
                }
            });

            // Notify frontend when backend is ready
            let app_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let client = reqwest::Client::new();
                for _ in 0..60 {
                    tokio::time::sleep(std::time::Duration::from_millis(100)).await;
                    if let Ok(resp) = client.get("http://localhost:8000/api/health").send().await {
                        if resp.status().is_success() {
                            let _ = app_handle.emit("backend-ready", true);
                            return;
                        }
                    }
                }
                let _ = app_handle.emit("backend-ready", false);
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Sift");
}
