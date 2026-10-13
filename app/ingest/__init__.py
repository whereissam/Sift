"""Deprecated: the ingestion core moved to the `sift_core` package.

Kept for one release so `from app.ingest import download_audio` in existing
scripts keeps working. Only the top-level names are re-exported — import
submodules (`sift_core.platforms`, `sift_core.fetch.downloader`, ...) from
`sift_core` directly. Nothing inside this repo imports this module.
"""

import warnings

from sift_core import *  # noqa: F401,F403
from sift_core import __all__  # noqa: F401

warnings.warn(
    "app.ingest is deprecated; import from sift_core instead",
    DeprecationWarning,
    stacklevel=2,
)
