"""Annotation CRUD with parent/reply threading."""

from datetime import datetime
from typing import Optional


class _AnnotationsMixin:
    """Methods that operate on the ``annotations`` table."""

    def create_annotation(
        self,
        annotation_id: str,
        job_id: str,
        user_id: str,
        content: str,
        segment_start: Optional[float] = None,
        segment_end: Optional[float] = None,
        parent_id: Optional[str] = None,
        user_name: Optional[str] = None,
    ) -> dict:
        """Create a new annotation."""
        now = datetime.utcnow().isoformat()

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO annotations (
                    id, job_id, user_id, content, segment_start, segment_end,
                    parent_id, user_name, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                annotation_id, job_id, user_id, content, segment_start, segment_end,
                parent_id, user_name, now, now
            ))

        return self.get_annotation(annotation_id)

    def get_annotation(self, annotation_id: str) -> Optional[dict]:
        """Get annotation by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM annotations WHERE id = ?", (annotation_id,)
            ).fetchone()

            if row:
                return dict(row)
        return None

    def get_annotations_for_job(
        self,
        job_id: str,
        segment_start: Optional[float] = None,
        segment_end: Optional[float] = None,
    ) -> list[dict]:
        """Get all annotations for a job, optionally filtered by time range."""
        with self._get_conn() as conn:
            if segment_start is not None and segment_end is not None:
                rows = conn.execute("""
                    SELECT * FROM annotations
                    WHERE job_id = ? AND parent_id IS NULL
                      AND ((segment_start IS NULL) OR
                           (segment_start <= ? AND segment_end >= ?))
                    ORDER BY segment_start ASC, created_at ASC
                """, (job_id, segment_end, segment_start)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM annotations
                    WHERE job_id = ? AND parent_id IS NULL
                    ORDER BY segment_start ASC, created_at ASC
                """, (job_id,)).fetchall()

            return [dict(row) for row in rows]

    def get_annotation_replies(self, parent_id: str) -> list[dict]:
        """Get replies to an annotation."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM annotations
                WHERE parent_id = ?
                ORDER BY created_at ASC
            """, (parent_id,)).fetchall()

            return [dict(row) for row in rows]

    def get_annotation_with_replies(self, annotation_id: str) -> Optional[dict]:
        """Get an annotation with all its replies."""
        annotation = self.get_annotation(annotation_id)
        if not annotation:
            return None

        annotation["replies"] = self.get_annotation_replies(annotation_id)
        return annotation

    def update_annotation(self, annotation_id: str, content: str) -> Optional[dict]:
        """Update an annotation's content."""
        now = datetime.utcnow().isoformat()

        with self._get_conn() as conn:
            cursor = conn.execute("""
                UPDATE annotations SET content = ?, updated_at = ?
                WHERE id = ?
            """, (content, now, annotation_id))

            if cursor.rowcount > 0:
                return self.get_annotation(annotation_id)
        return None

    def delete_annotation(self, annotation_id: str) -> bool:
        """Delete an annotation and its replies."""
        with self._get_conn() as conn:
            # Delete replies first
            conn.execute("DELETE FROM annotations WHERE parent_id = ?", (annotation_id,))
            # Delete the annotation
            cursor = conn.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
            return cursor.rowcount > 0
