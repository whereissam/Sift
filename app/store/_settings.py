"""AI provider, Obsidian, and task-preset settings."""

import json
import logging
from datetime import datetime
from typing import Optional

from ._crypto import _decrypt_secret, _encrypt_secret, rotate_secret

logger = logging.getLogger(__name__)


class _SettingsMixin:
    """AI / Obsidian / task-preset rows.

    Secrets (provider API keys) are encrypted via ``_crypto`` on
    write and decrypted on read so the raw SQLite file never carries
    plaintext credentials.
    """

    def _rotate_legacy_secrets(self) -> None:
        """Re-encrypt stored secrets still under the old DOWNLOAD_DIR key.

        That key was a public constant on Docker installs, so values left
        under it are readable by anyone holding a copy of the database.
        """
        try:
            with self._get_conn() as conn:
                rotated = 0
                for row in conn.execute(
                    "SELECT id, api_key, task_presets FROM ai_settings"
                ).fetchall():
                    new_key = rotate_secret(row["api_key"])
                    presets = json.loads(row["task_presets"] or "{}")
                    presets_changed = False
                    if isinstance(presets, dict):
                        for preset in presets.values():
                            if isinstance(preset, dict):
                                new = rotate_secret(preset.get("api_key"))
                                if new:
                                    preset["api_key"] = new
                                    presets_changed = True
                    if new_key or presets_changed:
                        conn.execute(
                            "UPDATE ai_settings SET api_key = ?, task_presets = ? WHERE id = ?",
                            (
                                new_key or row["api_key"],
                                json.dumps(presets) if presets_changed else row["task_presets"],
                                row["id"],
                            ),
                        )
                        rotated += 1
                for row in conn.execute(
                    "SELECT id, credentials FROM cloud_providers"
                ).fetchall():
                    new = rotate_secret(row["credentials"])
                    if new:
                        conn.execute(
                            "UPDATE cloud_providers SET credentials = ? WHERE id = ?",
                            (new, row["id"]),
                        )
                        rotated += 1
            if rotated:
                logger.info("Re-encrypted %d stored secret row(s) under the current key", rotated)
        except Exception:
            logger.warning("Could not re-encrypt legacy secrets", exc_info=True)

    # ============ AI Settings Methods ============

    def get_ai_settings(self) -> Optional[dict]:
        """Get the current AI provider settings."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM ai_settings WHERE is_default = 1 ORDER BY id DESC LIMIT 1"
            ).fetchone()

            if row:
                result = dict(row)
                # Decrypt API key if present
                if result.get("api_key"):
                    result["api_key"] = _decrypt_secret(result["api_key"])
                return result
        return None

    def save_ai_settings(
        self,
        provider: str,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> dict:
        """Save AI provider settings.

        Args:
            provider: Provider name (ollama, openai, anthropic, groq, deepseek, custom)
            model: Model name/identifier
            api_key: API key for cloud providers
            base_url: Base URL for custom endpoints or Ollama

        Returns:
            The saved settings
        """
        now = datetime.utcnow().isoformat()

        # Encrypt API key before storing
        encrypted_key = _encrypt_secret(api_key) if api_key else None

        with self._get_conn() as conn:
            # Check if settings exist
            existing = conn.execute(
                "SELECT id FROM ai_settings WHERE is_default = 1"
            ).fetchone()

            if existing:
                # Update existing settings
                conn.execute("""
                    UPDATE ai_settings
                    SET provider = ?, model = ?, api_key = ?, base_url = ?, updated_at = ?
                    WHERE is_default = 1
                """, (provider, model, encrypted_key, base_url, now))
            else:
                # Insert new settings
                conn.execute("""
                    INSERT INTO ai_settings (provider, model, api_key, base_url, is_default, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?)
                """, (provider, model, encrypted_key, base_url, now, now))

        logger.info(f"Saved AI settings: provider={provider}, model={model}")
        return self.get_ai_settings()

    # ============ Obsidian Settings Methods ============

    def get_obsidian_settings(self) -> Optional[dict]:
        """Get the current Obsidian settings."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM obsidian_settings WHERE is_default = 1 ORDER BY id DESC LIMIT 1"
            ).fetchone()

            if row:
                result = dict(row)
                # Parse default_tags from comma-separated string to list
                if result.get("default_tags"):
                    result["default_tags"] = [
                        tag.strip() for tag in result["default_tags"].split(",")
                    ]
                else:
                    result["default_tags"] = []
                return result
        return None

    def save_obsidian_settings(
        self,
        vault_path: str,
        subfolder: Optional[str] = "Sift",
        template: Optional[str] = None,
        default_tags: Optional[list[str]] = None,
    ) -> dict:
        """Save Obsidian settings.

        Args:
            vault_path: Path to Obsidian vault
            subfolder: Subfolder within vault for notes
            template: Custom template for notes
            default_tags: Default tags for exported notes

        Returns:
            The saved settings
        """
        now = datetime.utcnow().isoformat()

        # Convert tags list to comma-separated string
        tags_str = ",".join(default_tags) if default_tags else "sift,transcript"

        with self._get_conn() as conn:
            # Check if settings exist
            existing = conn.execute(
                "SELECT id FROM obsidian_settings WHERE is_default = 1"
            ).fetchone()

            if existing:
                # Update existing settings
                conn.execute("""
                    UPDATE obsidian_settings
                    SET vault_path = ?, subfolder = ?, template = ?, default_tags = ?, updated_at = ?
                    WHERE is_default = 1
                """, (vault_path, subfolder, template, tags_str, now))
            else:
                # Insert new settings
                conn.execute("""
                    INSERT INTO obsidian_settings (vault_path, subfolder, template, default_tags, is_default, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?)
                """, (vault_path, subfolder, template, tags_str, now, now))

        logger.info(f"Saved Obsidian settings: vault_path={vault_path}, subfolder={subfolder}")
        return self.get_obsidian_settings()

    # ============ Task Presets ============

    def get_task_presets(self) -> dict[str, dict]:
        """Read `ai_settings.task_presets`, decrypting any nested api_keys.

        Mirrors the encryption boundary that `ai_settings.api_key` already
        enforces — secrets stored inside the JSON column round-trip through
        `_decrypt_secret` so an attacker dumping the raw column doesn't
        recover usable provider credentials.
        """
        settings = self.get_ai_settings()
        if not settings:
            return {}
        raw = settings.get("task_presets")
        if not raw:
            return {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("task_presets contained invalid JSON; ignoring")
                return {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, dict] = {}
        for task, preset in raw.items():
            if not isinstance(preset, dict):
                # Defensive: drop malformed entries instead of crashing every
                # call to get_provider_for_task() that touches them.
                logger.warning("task_presets[%s] is not a dict; skipping", task)
                continue
            preset = dict(preset)  # copy so we don't mutate the cached row
            api_key = preset.get("api_key")
            if api_key:
                preset["api_key"] = _decrypt_secret(api_key)
            out[task] = preset
        return out

    def set_task_presets(self, presets: dict[str, dict]) -> None:
        """Write `ai_settings.task_presets`, encrypting any nested api_keys.

        Caller must ensure an `ai_settings` row exists (typically by calling
        `save_ai_settings(...)` first); this method only updates the JSON
        column on the existing default row.
        """
        encrypted: dict[str, dict] = {}
        for task, preset in presets.items():
            if not isinstance(preset, dict):
                continue
            p = dict(preset)
            api_key = p.get("api_key")
            if api_key:
                p["api_key"] = _encrypt_secret(api_key)
            encrypted[task] = p

        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM ai_settings WHERE is_default = 1 LIMIT 1"
            ).fetchone()
            if not row:
                logger.warning(
                    "set_task_presets: no default ai_settings row; "
                    "call save_ai_settings(...) first"
                )
                return
            conn.execute(
                "UPDATE ai_settings SET task_presets = ?, updated_at = ? WHERE id = ?",
                (json.dumps(encrypted), now, row["id"]),
            )
