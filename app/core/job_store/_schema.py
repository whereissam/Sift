"""Schema-init / migration mixin and shared connection context manager."""

import logging
import sqlite3
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class _SchemaMixin:
    """Owns connection management, table creation, and migrations.

    All other mixins assume ``self._get_conn()`` is available; that
    contract lives here.
    """

    db_path: object  # set by ``JobStore.__init__``

    @contextmanager
    def _get_conn(self):
        """Get database connection with context manager."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        """Initialize database schema."""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,

                    -- Source info
                    source_url TEXT,
                    platform TEXT,

                    -- File paths (two-phase tracking)
                    raw_file_path TEXT,
                    converted_file_path TEXT,

                    -- Settings
                    output_format TEXT,
                    quality TEXT,

                    -- Transcription specific
                    model_size TEXT,
                    language TEXT,
                    transcription_format TEXT,

                    -- Results
                    content_info TEXT,  -- JSON
                    transcription_result TEXT,  -- JSON
                    file_size_mb REAL,
                    error TEXT,

                    -- Progress tracking
                    progress REAL DEFAULT 0.0,
                    last_checkpoint TEXT,  -- JSON for transcription segments

                    -- Priority & Batching (v2)
                    priority INTEGER DEFAULT 5,
                    batch_id TEXT,

                    -- Scheduling (v2)
                    scheduled_at TEXT,

                    -- Webhooks (v2)
                    webhook_url TEXT,

                    -- Timestamps
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
            """)

            # Index for faster queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_job_type ON jobs(job_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_priority ON jobs(priority)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_batch_id ON jobs(batch_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_at ON jobs(scheduled_at)")

            # Batches table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id TEXT PRIMARY KEY,
                    name TEXT,
                    total_jobs INTEGER DEFAULT 0,
                    completed_jobs INTEGER DEFAULT 0,
                    failed_jobs INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    webhook_url TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Annotations table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS annotations (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    segment_start REAL,
                    segment_end REAL,
                    user_id TEXT NOT NULL,
                    user_name TEXT,
                    content TEXT NOT NULL,
                    parent_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_annotations_job ON annotations(job_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_annotations_parent ON annotations(parent_id)")

            # Cloud providers table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cloud_providers (
                    id TEXT PRIMARY KEY,
                    provider_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    credentials TEXT,
                    settings TEXT,
                    is_default INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Export jobs table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS export_jobs (
                    id TEXT PRIMARY KEY,
                    job_id TEXT,
                    file_path TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    destination_path TEXT,
                    status TEXT DEFAULT 'pending',
                    progress REAL DEFAULT 0.0,
                    bytes_uploaded INTEGER DEFAULT 0,
                    total_bytes INTEGER DEFAULT 0,
                    cloud_url TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY (provider_id) REFERENCES cloud_providers(id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_export_jobs_status ON export_jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_export_jobs_job ON export_jobs(job_id)")

            # AI settings table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_settings (
                    id INTEGER PRIMARY KEY,
                    provider TEXT NOT NULL DEFAULT 'ollama',
                    model TEXT NOT NULL DEFAULT 'llama3.2',
                    api_key TEXT,
                    base_url TEXT,
                    is_default INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Obsidian settings table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS obsidian_settings (
                    id INTEGER PRIMARY KEY,
                    vault_path TEXT NOT NULL,
                    subfolder TEXT DEFAULT 'Sift',
                    template TEXT,
                    default_tags TEXT DEFAULT 'sift,transcript',
                    is_default INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # P18: Knowledge layer (claims). Entities/topics/predictions land
            # in Phase B/C — but the join columns (entity_ids, topic_ids) are
            # already on Claim records as JSON arrays so the schema is forward-
            # compatible.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    speaker TEXT,
                    timestamp_start REAL NOT NULL,
                    timestamp_end REAL NOT NULL,
                    claim_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_excerpt TEXT NOT NULL,
                    entity_ids TEXT DEFAULT '[]',  -- JSON array
                    topic_ids TEXT DEFAULT '[]',   -- JSON array
                    source_url TEXT,
                    extraction_version INTEGER NOT NULL,
                    schema_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_episode ON claims(episode_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(claim_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_speaker ON claims(speaker)")

            # Generic embeddings table — keyed by (object_type, object_id, model)
            # so we can embed segments / claims / entities / episodes uniformly.
            # Phase A creates the table; population starts in Phase B (entity
            # canonicalization) and P10 (semantic search). Behind a thin
            # interface in embedding_store.py so the SQLite→Chroma swap is a
            # one-file change later.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    dim INTEGER NOT NULL,
                    vector_blob BLOB NOT NULL,
                    norm REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (object_type, object_id, model)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_type ON embeddings(object_type)")

            # P18 Phase B: Entities + mentions. Dual-ID (`entity_id` PK +
            # UNIQUE `slug`) lets us rename slugs on demand without breaking
            # references. Mentions carry an optional `claim_id` so entities
            # can exist without a specific claim reference.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    aliases TEXT DEFAULT '[]',  -- JSON array of surface forms
                    confidence REAL DEFAULT 1.0,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_slug ON entities(slug)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS entity_mentions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL,
                    episode_id TEXT NOT NULL,
                    claim_id TEXT,
                    chunk_id TEXT,
                    raw_text TEXT NOT NULL,
                    start_char INTEGER,
                    end_char INTEGER,
                    timestamp REAL,
                    speaker TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (entity_id) REFERENCES entities(entity_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mentions_entity ON entity_mentions(entity_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mentions_episode ON entity_mentions(episode_id)")

            # P18 Phase C.1: Topics + claim↔topic join. `claim_topics` is the
            # source of truth (powers reverse queries like "claims for this
            # topic"); the `claims.topic_ids` JSON array is a denormalized
            # cache kept in sync inside the same tx so per-claim render
            # doesn't need an extra query. No slug on topics — they're
            # fuzzier than entities and the kebab form reads worse.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS topics (
                    topic_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    aliases TEXT DEFAULT '[]',  -- JSON array of surface forms
                    confidence REAL DEFAULT 1.0,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_topics_name ON topics(name)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS claim_topics (
                    claim_id TEXT NOT NULL,
                    topic_id TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (claim_id, topic_id),
                    FOREIGN KEY (claim_id) REFERENCES claims(claim_id) ON DELETE CASCADE,
                    FOREIGN KEY (topic_id) REFERENCES topics(topic_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claim_topics_topic ON claim_topics(topic_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claim_topics_claim ON claim_topics(claim_id)")

            # P18 Phase C.2: Predictions. Dedicated table because the
            # lifecycle columns (target_horizon, conditions, falsifiable_by,
            # resolution, resolved_at, …) are the start of a workflow, not
            # a flag — keeping them off `claims` lets prediction-specific
            # expansion (resolution evidence, recalibration, dashboards)
            # land here without piling more nullable columns onto every
            # claim row. `claim_id` is FK-UNIQUE so re-extraction's
            # claim-cascade-delete reliably wipes the matching prediction
            # too.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    claim_id TEXT PRIMARY KEY,
                    target_horizon TEXT,
                    conditions TEXT,
                    falsifiable_by TEXT,
                    resolution TEXT NOT NULL DEFAULT 'pending',
                    resolution_note TEXT,
                    resolved_at TEXT,
                    resolved_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (claim_id) REFERENCES claims(claim_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_predictions_resolution ON predictions(resolution)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_predictions_created ON predictions(created_at)")

            # Quarantine for malformed extraction outputs — keep raw response
            # and error so we can debug prompt drift without crashing the
            # pipeline.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS extraction_failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    episode_id TEXT NOT NULL,
                    chunk_index INTEGER,
                    raw_output TEXT,
                    error TEXT NOT NULL,
                    extraction_version INTEGER,
                    model TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_failures_episode ON extraction_failures(episode_id)")

            # Run migrations for existing databases
            self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection):
        """Run database migrations for schema updates."""
        # Check existing columns in jobs table
        cursor = conn.execute("PRAGMA table_info(jobs)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        # Add missing columns (v2 schema)
        migrations = [
            ("priority", "INTEGER DEFAULT 5"),
            ("batch_id", "TEXT"),
            ("scheduled_at", "TEXT"),
            ("webhook_url", "TEXT"),
            # P18: knowledge layer status. Values: none|pending|running|ready|failed.
            # 'none' = never attempted; 'pending' = queued for backfill or on-demand.
            # ('extracting'/'complete' are legacy aliases for running/ready written
            # by the synchronous extract route — still accepted, never rejected.)
            ("knowledge_status", "TEXT DEFAULT 'none'"),
            # P18 Phase C.3: backfill control-plane columns. `knowledge_version`
            # bumps on every successful (re-)extraction so consumers can detect
            # staleness; `knowledge_locked_at` / `knowledge_worker_id` implement
            # a claim-lock so concurrent workers (or worker + on-demand route)
            # don't double-extract the same job.
            ("knowledge_version", "INTEGER DEFAULT 0"),
            ("knowledge_locked_at", "TEXT"),
            ("knowledge_worker_id", "TEXT"),
        ]

        for col_name, col_type in migrations:
            if col_name not in existing_columns:
                try:
                    conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}")
                    logger.info(f"Added column {col_name} to jobs table")
                except sqlite3.OperationalError:
                    pass  # Column might already exist

        # ai_settings.task_presets — JSON map of TaskType -> {provider,model,...}
        cursor = conn.execute("PRAGMA table_info(ai_settings)")
        ai_existing = {row[1] for row in cursor.fetchall()}
        if "task_presets" not in ai_existing:
            try:
                conn.execute("ALTER TABLE ai_settings ADD COLUMN task_presets TEXT")
                logger.info("Added column task_presets to ai_settings")
            except sqlite3.OperationalError:
                pass

        # Index for the Phase C.3 backfill pending-queue scan. Created here
        # (not in _init_db) because knowledge_status is added by migration
        # above, so the column may not exist on the jobs table until now.
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_status "
                "ON jobs(knowledge_status)"
            )
        except sqlite3.OperationalError:
            pass
