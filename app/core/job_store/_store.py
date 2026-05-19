"""Composed ``JobStore`` class.

The singleton accessor (``get_job_store`` / ``_job_store``) lives in
``__init__.py`` so tests can monkeypatch it via the package namespace.
"""

from pathlib import Path
from typing import Optional

from ._annotations import _AnnotationsMixin
from ._batches import _BatchesMixin
from ._jobs import _JobsMixin
from ._knowledge import _KnowledgeMixin
from ._schema import _SchemaMixin
from ._settings import _SettingsMixin


class JobStore(
    _SchemaMixin,
    _JobsMixin,
    _BatchesMixin,
    _AnnotationsMixin,
    _SettingsMixin,
    _KnowledgeMixin,
):
    """SQLite-based persistent job storage.

    Implementation is split across mixins for navigability:
    schema / jobs / batches / annotations / settings / knowledge.
    """

    def __init__(self, db_path: Optional[Path] = None):
        if db_path:
            self.db_path = db_path
        else:
            from ...config import get_settings

            settings = get_settings()
            self.db_path = Path(settings.download_dir) / "jobs.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
