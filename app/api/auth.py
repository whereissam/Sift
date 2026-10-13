"""API authentication via X-API-Key header.

Two kinds of credentials (P22 Slice 4):

* **Principal keys** (``sk_sift_…``) — issued via ``POST /api/principals``,
  stored hashed. A principal key authenticates whenever it matches an active
  principal, gets its usage recorded per UTC day, and is refused with 429
  once its ``daily_request_quota`` is exhausted.
* **The legacy master key** (the ``API_KEY`` setting) — behaves exactly as
  before, and is additionally the only credential that may manage
  principals. When ``API_KEY`` is unset and no principal matches,
  authentication stays disabled (open access) for backward compatibility.
"""

import hmac

from fastapi import Header, HTTPException
from starlette.requests import HTTPConnection

from ..config import get_settings


def _key_matches(presented: str | None, expected: str) -> bool:
    """Constant-time key comparison that also accepts non-ASCII input.

    hmac.compare_digest raises TypeError for non-ASCII str, which surfaced
    as a 500; comparing the UTF-8 bytes refuses such a key with a 401.
    """
    if presented is None:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def _resolve_principal(x_api_key: str):
    """Active principal for a presented key, or None. Never raises — a
    storage hiccup must not lock out the legacy-key path."""
    if not x_api_key or not x_api_key.startswith("sk_sift_"):
        return None
    try:
        from ..store import get_job_store

        return get_job_store().get_principal_by_key(x_api_key)
    except Exception:
        return None


async def verify_api_key(
    # HTTPConnection (not Request) so the same dependency serves both HTTP
    # routes and the realtime WebSocket route.
    request: HTTPConnection,
    x_api_key: str | None = Header(None),
) -> None:
    """
    Verify API key if authentication is enabled.

    Principal keys are checked first; the legacy single API_KEY setting is
    the fallback. With no API_KEY configured, requests without a principal
    key remain open (original behavior).
    """
    settings = get_settings()

    principal = _resolve_principal(x_api_key) if x_api_key else None
    if principal is not None:
        from ..store import get_job_store

        store = get_job_store()
        count = store.record_usage(principal["principal_id"])
        quota = principal.get("daily_request_quota")
        if quota is not None and count > quota:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Daily request quota exhausted for principal "
                    f"'{principal['name']}' ({quota}/day)."
                ),
            )
        try:
            store.touch_principal(principal["principal_id"])
        except Exception:  # last_used_at is cosmetic — never block a request
            pass
        request.state.principal = principal
        return

    # Legacy path — unchanged semantics.
    if settings.api_key is None:
        return

    if x_api_key is None:
        raise HTTPException(
            status_code=401,
            detail="Missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not _key_matches(x_api_key, settings.api_key):
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    request.state.principal = None  # master key — no principal scoping


async def verify_master_key(x_api_key: str | None = Header(None)) -> None:
    """Guard for principal management: only the legacy master ``API_KEY``
    qualifies — a principal key must never mint or revoke other keys. When
    no master key is configured the instance is open, so management is too
    (consistent with every other route)."""
    settings = get_settings()
    if settings.api_key is None:
        return
    if not _key_matches(x_api_key, settings.api_key):
        raise HTTPException(
            status_code=403,
            detail="Principal management requires the master API key",
        )
