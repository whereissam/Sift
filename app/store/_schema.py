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

            # KOL scorecard (docs/kol-scorecard.md). A KOL is a `person`
            # entity plus its public handles; a handle belongs to exactly
            # one person, hence the (platform, handle) PK.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kol_handles (
                    entity_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    handle TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (platform, handle),
                    FOREIGN KEY (entity_id) REFERENCES entities(entity_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kol_handles_entity ON kol_handles(entity_id)")
            # Who is behind a speaker label in one episode. Keyed by the
            # label as it appears on `claims.speaker`, not by claim, so it
            # survives re-extraction (claims are replaced, labels are not).
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episode_speakers (
                    episode_id TEXT NOT NULL,
                    speaker TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    confirmed_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (episode_id, speaker),
                    FOREIGN KEY (entity_id) REFERENCES entities(entity_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episode_speakers_entity ON episode_speakers(entity_id)")

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

            # P20: subscription digest pipeline — configs + generated runs.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS digest_configs (
                    digest_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    subscription_ids TEXT NOT NULL,
                    window_days INTEGER NOT NULL DEFAULT 7,
                    schedule_hours INTEGER NOT NULL DEFAULT 24,
                    min_confidence REAL NOT NULL DEFAULT 0.6,
                    webhook_url TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_run_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS digest_runs (
                    run_id TEXT PRIMARY KEY,
                    digest_id TEXT NOT NULL,
                    window_start TEXT,
                    window_end TEXT,
                    status TEXT NOT NULL,
                    episode_count INTEGER NOT NULL DEFAULT 0,
                    claim_count INTEGER NOT NULL DEFAULT 0,
                    synthesis_json TEXT,
                    markdown TEXT,
                    model TEXT,
                    tokens_used INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (digest_id) REFERENCES digest_configs(digest_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_digest_runs_digest ON digest_runs(digest_id, created_at)")

            # Assets: durable content identity (migration Slice 1).
            # UNIQUE(source_fingerprint) is the dedup backbone — the same
            # canonical source always resolves to one asset.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS assets (
                    asset_id            TEXT PRIMARY KEY,
                    source_type         TEXT NOT NULL,
                    canonical_source    TEXT NOT NULL,
                    source_fingerprint  TEXT NOT NULL UNIQUE,
                    original_source     TEXT,
                    platform            TEXT,
                    created_at          TEXT NOT NULL,
                    updated_at          TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_assets_canonical "
                "ON assets(canonical_source)"
            )

            # Migration bookkeeping (e.g. one-time backfill completion markers).
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # Slice 2: versioned transcript artifacts. One row per transcript
            # *generation*; retranscription inserts a new artifact with
            # supersedes_artifact_id set instead of mutating history.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transcript_artifacts (
                    artifact_id             TEXT PRIMARY KEY,
                    asset_id                TEXT NOT NULL,
                    job_id                  TEXT,
                    schema_version          INTEGER NOT NULL DEFAULT 1,
                    pipeline_version        TEXT NOT NULL,
                    model_name              TEXT,
                    language                TEXT,
                    diarization_enabled     INTEGER NOT NULL DEFAULT 0,
                    status                  TEXT NOT NULL DEFAULT 'complete',
                    supersedes_artifact_id  TEXT,
                    created_at              TEXT NOT NULL,
                    FOREIGN KEY (asset_id) REFERENCES assets(asset_id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artifacts_asset "
                "ON transcript_artifacts(asset_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artifacts_job "
                "ON transcript_artifacts(job_id)"
            )

            # Addressable transcript segments. model_confidence_raw is
            # faster-whisper's avg_logprob verbatim (NOT calibrated);
            # confidence_normalized stays NULL until a documented transform
            # is chosen (see docs/knowledge-schema.md when that lands).
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transcript_segments (
                    segment_id              TEXT PRIMARY KEY,
                    transcript_artifact_id  TEXT NOT NULL,
                    ordinal                 INTEGER NOT NULL,
                    start_ms                INTEGER NOT NULL,
                    end_ms                  INTEGER NOT NULL,
                    speaker_id              TEXT,
                    text                    TEXT NOT NULL,
                    model_confidence_raw    REAL,
                    confidence_normalized   REAL,
                    source_segment_key      TEXT,
                    FOREIGN KEY (transcript_artifact_id)
                        REFERENCES transcript_artifacts(artifact_id)
                        ON DELETE CASCADE,
                    UNIQUE (transcript_artifact_id, ordinal)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_segments_artifact "
                "ON transcript_segments(transcript_artifact_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_segments_time "
                "ON transcript_segments(transcript_artifact_id, start_ms)"
            )

            # P10: semantic-search chunks. Windows of consecutive transcript
            # segments sized for the embedding model; the vector itself lives
            # in the generic `embeddings` table under object_type='segment'
            # keyed by chunk_id, so this table only carries the metadata a
            # search hit needs to render (timestamps, speaker, text).
            conn.execute("""
                CREATE TABLE IF NOT EXISTS search_chunks (
                    chunk_id        TEXT PRIMARY KEY,
                    job_id          TEXT NOT NULL,
                    ordinal         INTEGER NOT NULL,
                    start_s         REAL,
                    end_s           REAL,
                    speaker         TEXT,
                    text            TEXT NOT NULL,
                    embedding_model TEXT,
                    created_at      TEXT NOT NULL,
                    UNIQUE (job_id, ordinal)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_search_chunks_job "
                "ON search_chunks(job_id)"
            )

            # P13: contradiction pairs over P18 claims. The pair-hash PK makes
            # re-analysis an upsert; episode/speaker columns are denormalized
            # from the claims for cheap filtered reads.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS contradictions (
                    contradiction_id  TEXT PRIMARY KEY,
                    claim_id_a        TEXT NOT NULL,
                    claim_id_b        TEXT NOT NULL,
                    episode_id_a      TEXT,
                    episode_id_b      TEXT,
                    speaker           TEXT,
                    explanation       TEXT,
                    confidence        REAL,
                    detected_at       TEXT NOT NULL,
                    FOREIGN KEY (claim_id_a) REFERENCES claims(claim_id),
                    FOREIGN KEY (claim_id_b) REFERENCES claims(claim_id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_contradictions_speaker "
                "ON contradictions(speaker)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_contradictions_episode "
                "ON contradictions(episode_id_a, episode_id_b)"
            )

            # P22 Slice 4: API-key principals. Only the SHA-256 of a key is
            # stored — the plaintext is shown once at creation.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_principals (
                    principal_id        TEXT PRIMARY KEY,
                    name                TEXT NOT NULL UNIQUE,
                    key_hash            TEXT NOT NULL UNIQUE,
                    active              INTEGER NOT NULL DEFAULT 1,
                    daily_request_quota INTEGER,
                    created_at          TEXT NOT NULL,
                    last_used_at        TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_principals_hash "
                "ON api_principals(key_hash)"
            )

            # P22 Slice 4: per-principal, per-UTC-day usage counters.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage_ledger (
                    principal_id TEXT NOT NULL,
                    day          TEXT NOT NULL,
                    requests     INTEGER NOT NULL DEFAULT 0,
                    tokens       INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (principal_id, day)
                )
            """)

            # P14: on-demand distillation runs (explicit job sets; the
            # scheduled/subscription case lives in digest_runs).
            conn.execute("""
                CREATE TABLE IF NOT EXISTS distillations (
                    distill_id     TEXT PRIMARY KEY,
                    job_ids        TEXT NOT NULL,
                    mode           TEXT NOT NULL,
                    result         TEXT NOT NULL,
                    claim_count    INTEGER DEFAULT 0,
                    episode_count  INTEGER DEFAULT 0,
                    tokens_used    INTEGER DEFAULT 0,
                    model          TEXT,
                    created_at     TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_distillations_created "
                "ON distillations(created_at)"
            )

            # P17: named, reusable custom extraction schemas. `fields` is the
            # JSON list fed to the CUSTOM extraction prompt
            # ([{name, type, description}, ...]).
            conn.execute("""
                CREATE TABLE IF NOT EXISTS extraction_schemas (
                    schema_id   TEXT PRIMARY KEY,
                    name        TEXT NOT NULL UNIQUE,
                    description TEXT,
                    fields      TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                )
            """)

            # P11: Ask Audio Q&A history. job_id NULL = library-wide ask.
            # sources is the JSON list of RAGSource dicts the answer cited.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id      TEXT,
                    question    TEXT NOT NULL,
                    answer      TEXT NOT NULL,
                    sources     TEXT,
                    model       TEXT,
                    created_at  TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_history_job "
                "ON chat_history(job_id, created_at)"
            )

            # Slice 3: idempotency keys for /v1 submissions. Same key +
            # same request_hash replays the original job; same key +
            # different hash is a 409.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    principal_id     TEXT NOT NULL,
                    endpoint         TEXT NOT NULL,
                    idempotency_key  TEXT NOT NULL,
                    request_hash     TEXT NOT NULL,
                    job_id           TEXT NOT NULL,
                    created_at       TEXT NOT NULL,
                    PRIMARY KEY (principal_id, endpoint, idempotency_key)
                )
            """)

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
            # P12: agentic pipeline state — JSON {profile, stages: [{name,
            # status, ...}]} maintained by app/pipeline/agentic_pipeline.py.
            ("pipeline_state", "TEXT"),
            # P16: per-job webhook payload template override
            # (minimal | summary | full_intelligence).
            ("webhook_template", "TEXT"),
            # Slice 1: durable content identity. Nullable at the SQL level
            # (SQLite can't add NOT NULL without a rebuild); the service
            # layer sets it for every new job with a durable source.
            ("asset_id", "TEXT"),
            # Slice 3: outputs requested at submission (JSON array), so the
            # ingestion runner knows what to produce after a restart.
            ("requested_outputs", "TEXT"),
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

        # KOL scorecard: human review of a prediction's quote + speaker
        # before anything about it is published. Operator state, like
        # `resolution` — re-extraction must carry it over, never reset it.
        cursor = conn.execute("PRAGMA table_info(predictions)")
        prediction_columns = {row[1] for row in cursor.fetchall()}
        for col_name, col_type in [
            ("review_status", "TEXT NOT NULL DEFAULT 'unreviewed'"),
            ("review_note", "TEXT"),
            ("reviewed_at", "TEXT"),
            ("reviewed_by", "TEXT"),
        ]:
            if col_name not in prediction_columns:
                try:
                    conn.execute(f"ALTER TABLE predictions ADD COLUMN {col_name} {col_type}")
                    logger.info(f"Added column {col_name} to predictions table")
                except sqlite3.OperationalError:
                    pass
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_predictions_review "
                "ON predictions(review_status)"
            )
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

        # Slice 1: asset linkage index + one-time backfill of existing jobs.
        # Both run after the asset_id column migration above.
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_asset ON jobs(asset_id)"
            )
        except sqlite3.OperationalError:
            pass
        self._backfill_assets(conn)
