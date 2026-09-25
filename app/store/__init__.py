"""Persistent job storage using SQLite.

Split into focused mixins to keep each domain (jobs, batches, annotations,
settings, knowledge) navigable, but the public API is unchanged: callers
keep doing ``from app.store import JobStore, JobStatus, JobType,
get_job_store``.

The singleton (``_job_store``) and accessor (``get_job_store``) are defined
here so tests can monkeypatch them at the package namespace.
"""

from typing import Optional

from sift_core.settings import set_cloud_credentials_provider
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


def _cloud_transcription_credentials() -> Optional[dict]:
    return get_job_store().get_ai_settings()


# The ingestion core never opens this database itself; it asks for cloud
# transcription credentials through this hook.
set_cloud_credentials_provider(_cloud_transcription_credentials)
