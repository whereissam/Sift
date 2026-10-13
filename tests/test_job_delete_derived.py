"""Deleting a job removes the rows derived from it, and only those.

Regression test for the security audit: delete_job removed only the jobs
row; search chunks, segment embeddings, claims (+ topics edges,
predictions, contradictions), mentions, annotations and chat history
survived with nothing pointing at them.
"""

import sqlite3

import pytest

from app.store import JobType
from app.store._store import JobStore


def _insert(conn, table, **values):
    """Insert a row, filling any other NOT NULL column with a dummy value."""
    for _, name, col_type, notnull, default, pk in conn.execute(f"PRAGMA table_info({table})"):
        if name in values or not notnull or default is not None:
            continue
        if pk and "INT" in (col_type or "").upper():
            continue
        values[name] = 0 if "INT" in (col_type or "").upper() or "REAL" in (col_type or "").upper() else f"{table}-{name}-{len(values)}"
    cols = ",".join(values)
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({','.join('?' * len(values))})", tuple(values.values()))


def _seed(conn, job):
    _insert(conn, "search_chunks", chunk_id=f"chunk-{job}", job_id=job)
    _insert(conn, "embeddings", object_type="segment", object_id=f"chunk-{job}", model="m")
    _insert(conn, "claims", claim_id=f"claim-{job}", episode_id=job)
    _insert(conn, "claim_topics", claim_id=f"claim-{job}", topic_id="topic-shared")
    _insert(conn, "predictions", claim_id=f"claim-{job}")
    _insert(conn, "entity_mentions", entity_id="ent-shared", episode_id=job, claim_id=f"claim-{job}")
    _insert(conn, "extraction_failures", episode_id=job)
    _insert(conn, "annotations", id=f"ann-{job}", job_id=job)
    _insert(conn, "chat_history", job_id=job)
    _insert(conn, "idempotency_keys", principal_id="default", endpoint="e", idempotency_key=f"k-{job}", job_id=job)


CHECKS = {
    "search_chunks": "job_id = ?",
    "claims": "episode_id = ?",
    "entity_mentions": "episode_id = ?",
    "extraction_failures": "episode_id = ?",
    "annotations": "job_id = ?",
    "chat_history": "job_id = ?",
    "idempotency_keys": "job_id = ?",
    "embeddings": "object_type = 'segment' AND object_id = 'chunk-' || ?",
    "claim_topics": "claim_id = 'claim-' || ?",
    "predictions": "claim_id = 'claim-' || ?",
}


def _count(conn, table, where, job):
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", (job,)).fetchone()[0]


@pytest.fixture
def store(tmp_path):
    store = JobStore(db_path=tmp_path / "jobs.db")
    for job in ("a", "b"):
        store.create_job(job, JobType.TRANSCRIBE, source_url=f"https://youtu.be/{job}")
    with sqlite3.connect(store.db_path) as conn:
        for job in ("a", "b"):
            _seed(conn, job)
        _insert(conn, "entities", entity_id="ent-shared")
        _insert(conn, "topics", topic_id="topic-shared")
        _insert(conn, "embeddings", object_type="entity", object_id="ent-shared", model="m")
        _insert(conn, "contradictions", claim_id_a="claim-a", claim_id_b="claim-b")
    return store


def test_delete_job_removes_only_its_derived_rows(store):
    assert store.delete_job("a")
    with sqlite3.connect(store.db_path) as conn:
        for table, where in CHECKS.items():
            assert _count(conn, table, where, "a") == 0, f"{table} kept rows of the deleted job"
            assert _count(conn, table, where, "b") == 1, f"{table} lost rows of another job"
        # A contradiction involving the deleted job's claim goes with it.
        assert conn.execute("SELECT COUNT(*) FROM contradictions").fetchone()[0] == 0
        # Shared, cross-job data stays.
        assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM embeddings WHERE object_type = 'entity'").fetchone()[0] == 1
    assert store.get_job("a") is None and store.get_job("b") is not None


def test_cleanup_old_jobs_removes_derived_rows(store):
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE jobs SET status = 'completed', updated_at = '2000-01-01' WHERE job_id = 'a'")
    assert store.cleanup_old_jobs(days=1) == 1
    with sqlite3.connect(store.db_path) as conn:
        assert all(_count(conn, t, w, "a") == 0 for t, w in CHECKS.items())
        assert all(_count(conn, t, w, "b") == 1 for t, w in CHECKS.items())
