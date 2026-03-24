use rusqlite::{params, Connection};
use std::path::Path;
use std::sync::Mutex;

use super::types::*;

pub struct JobStore {
    conn: Mutex<Connection>,
}

impl JobStore {
    pub fn new(db_path: &Path) -> Result<Self, String> {
        let conn = Connection::open(db_path).map_err(|e| format!("Failed to open DB: {}", e))?;

        conn.execute_batch(
            "
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL DEFAULT 'DOWNLOAD',
                status TEXT NOT NULL DEFAULT 'pending',
                source_url TEXT,
                platform TEXT,
                raw_file_path TEXT,
                converted_file_path TEXT,
                output_format TEXT,
                quality TEXT,
                content_info TEXT,
                file_size_mb REAL,
                error TEXT,
                progress REAL DEFAULT 0.0,
                priority INTEGER DEFAULT 5,
                batch_id TEXT,
                webhook_url TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_jobs_priority ON jobs(priority);
            ",
        )
        .map_err(|e| format!("Failed to create tables: {}", e))?;

        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    pub fn save_job(&self, job: &DownloadJob, source_url: &str) -> Result<(), String> {
        let conn = self.conn.lock().unwrap();
        let content_info_json = job
            .content_info
            .as_ref()
            .map(|ci| serde_json::to_string(ci).unwrap_or_default());
        let now = chrono::Utc::now().to_rfc3339();

        conn.execute(
            "INSERT OR REPLACE INTO jobs
             (job_id, status, source_url, platform, converted_file_path,
              content_info, file_size_mb, error, progress, created_at, updated_at, completed_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)",
            params![
                job.job_id,
                job.status.to_string(),
                source_url,
                job.platform.map(|p| p.to_string()),
                job.file_path,
                content_info_json,
                job.file_size_mb,
                job.error,
                job.progress,
                job.created_at.to_rfc3339(),
                now,
                job.completed_at.map(|t| t.to_rfc3339()),
            ],
        )
        .map_err(|e| format!("Failed to save job: {}", e))?;

        Ok(())
    }

    pub fn get_jobs(
        &self,
        status_filter: Option<&str>,
        limit: usize,
    ) -> Result<Vec<serde_json::Value>, String> {
        let conn = self.conn.lock().unwrap();

        let query = match status_filter {
            Some(status) => format!(
                "SELECT job_id, status, source_url, platform, content_info,
                        file_size_mb, error, progress, created_at, completed_at
                 FROM jobs WHERE status = '{}' ORDER BY created_at DESC LIMIT {}",
                status, limit
            ),
            None => format!(
                "SELECT job_id, status, source_url, platform, content_info,
                        file_size_mb, error, progress, created_at, completed_at
                 FROM jobs ORDER BY created_at DESC LIMIT {}",
                limit
            ),
        };

        let mut stmt = conn.prepare(&query).map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([], |row| {
                Ok(serde_json::json!({
                    "job_id": row.get::<_, String>(0)?,
                    "status": row.get::<_, String>(1)?,
                    "source_url": row.get::<_, Option<String>>(2)?,
                    "platform": row.get::<_, Option<String>>(3)?,
                    "content_info": row.get::<_, Option<String>>(4)?
                        .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok()),
                    "file_size_mb": row.get::<_, Option<f64>>(5)?,
                    "error": row.get::<_, Option<String>>(6)?,
                    "progress": row.get::<_, f64>(7)?,
                    "created_at": row.get::<_, String>(8)?,
                    "completed_at": row.get::<_, Option<String>>(9)?,
                }))
            })
            .map_err(|e| e.to_string())?;

        let mut results = Vec::new();
        for row in rows {
            if let Ok(val) = row {
                results.push(val);
            }
        }
        Ok(results)
    }

    pub fn delete_job(&self, job_id: &str) -> Result<bool, String> {
        let conn = self.conn.lock().unwrap();
        let affected = conn
            .execute("DELETE FROM jobs WHERE job_id = ?1", params![job_id])
            .map_err(|e| e.to_string())?;
        Ok(affected > 0)
    }
}
