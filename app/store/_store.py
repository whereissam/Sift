"""Composed ``JobStore`` class.

The singleton accessor (``get_job_store`` / ``_job_store``) lives in
``__init__.py`` so tests can monkeypatch it via the package namespace.
"""

from pathlib import Path
from typing import Optional

from ._annotations import _AnnotationsMixin
from ._artifacts import _ArtifactsMixin
from ._assets import _AssetsMixin
from ._backfill import _BackfillMixin
from ._batches import _BatchesMixin
from ._chat import _ChatMixin
from ._contradictions import _ContradictionsMixin
from ._digest import _DigestMixin
from ._distillations import _DistillationsMixin
from ._extraction_schemas import _ExtractionSchemasMixin
from ._principals import _PrincipalsMixin
from ._idempotency import _IdempotencyMixin
from ._jobs import _JobsMixin
from ._knowledge import _KnowledgeMixin
from ._kols import _KolsMixin
from ._pipeline import _PipelineMixin
from ._schema import _SchemaMixin
from ._search import _SearchMixin
from ._settings import _SettingsMixin


class JobStore(
    _SchemaMixin,
    _JobsMixin,
    _AssetsMixin,
    _ArtifactsMixin,
    _IdempotencyMixin,
    _BatchesMixin,
    _AnnotationsMixin,
    _SettingsMixin,
    _KnowledgeMixin,
    _KolsMixin,
    _BackfillMixin,
    _DigestMixin,
    _SearchMixin,
    _ChatMixin,
    _PipelineMixin,
    _ContradictionsMixin,
    _ExtractionSchemasMixin,
    _DistillationsMixin,
    _PrincipalsMixin,
):
    """SQLite-based persistent job storage.

    Implementation is split across mixins for navigability:
    schema / jobs / batches / annotations / settings / knowledge / backfill.
    """

    def __init__(self, db_path: Optional[Path] = None):
        if db_path:
            self.db_path = db_path
        else:
            from ..config import get_settings

            settings = get_settings()
            self.db_path = Path(settings.download_dir) / "jobs.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._backup_before_migration()
        self._init_db()
        self._rotate_legacy_secrets()

    def _backup_before_migration(self) -> None:
        """File-copy backup of an existing database before a schema-changing
        migration first runs (detected by the assets table being absent).
        Runs before any connection is opened, so the copy is consistent."""
        import shutil
        import sqlite3
        from datetime import datetime

        if not self.db_path.exists():
            return
        try:
            conn = sqlite3.connect(str(self.db_path))
            try:
                migrated = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='assets'"
                ).fetchone()
            finally:
                conn.close()
            if migrated:
                return
            backup_dir = self.db_path.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(self.db_path, backup_dir / f"pre_migration_{stamp}.db")
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Pre-migration backup failed for %s", self.db_path, exc_info=True
            )
