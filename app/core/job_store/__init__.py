"""Persistent job storage using SQLite.

Split into focused mixins to keep each domain (jobs, batches, annotations,
settings, knowledge) navigable, but the public API is unchanged: callers
keep doing ``from app.core.job_store import JobStore, JobStatus, JobType,
get_job_store``.

The singleton (``_job_store``) and accessor (``get_job_store``) are defined
here so tests can monkeypatch them at the package namespace.
"""

from typing import Optional

from ._enums import JobStatus, JobType
from ._store import JobStore

__all__ = ["JobStatus", "JobType", "JobStore", "get_job_store"]

_job_store: Optional[JobStore] = None


def get_job_store() -> JobStore:
    """Get or create the global job store instance."""
    global _job_store
    if _job_store is None:
        _job_store = JobStore()
    return _job_store
