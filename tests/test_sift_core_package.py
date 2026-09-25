"""`sift_core` is its own package (packages/sift-core), installed into the
app's environment as a uv workspace member. These pin what the split promised:
the CLI ships with the core, and the old `app.ingest` import path keeps working
for one release, with a warning."""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
import warnings
from importlib.metadata import distribution

import pytest

import sift_core


def test_core_is_installed_as_its_own_distribution():
    dist = distribution("sift-core")
    requires = " ".join(dist.requires or [])
    # The lean dependency set is the point of the split.
    for heavy in ("fastapi", "litellm", "python-telegram-bot", "sentence-transformers"):
        assert heavy not in requires, f"sift-core must not depend on {heavy}"


def test_the_app_depends_on_the_core():
    requires = distribution("sift").requires or []
    assert any(r.split(";")[0].strip().startswith("sift-core") for r in requires)


def test_sift_cli_comes_from_the_core():
    scripts = {
        ep.name: ep.value
        for ep in distribution("sift-core").entry_points
        if ep.group == "console_scripts"
    }
    assert scripts["sift"] == "sift_core.cli:cli"
    assert scripts["xdownloader"] == "sift_core.cli:cli"


def test_sift_cli_runs():
    exe = shutil.which("sift", path=str(sys.prefix) + "/bin")
    assert exe, "the `sift` console script should be installed"
    out = subprocess.run([exe, "--help"], capture_output=True, text=True, check=True)
    for command in ("download", "convert", "to-video"):
        assert command in out.stdout


def test_old_import_path_still_works_and_warns():
    sys.modules.pop("app.ingest", None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        shim = importlib.import_module("app.ingest")
    assert any(
        issubclass(w.category, DeprecationWarning) and "sift_core" in str(w.message)
        for w in caught
    )
    assert shim.download_audio is sift_core.download_audio
    assert shim.IngestSettings is sift_core.IngestSettings
    assert set(shim.__all__) == set(sift_core.__all__)


def test_old_submodule_paths_are_gone():
    """Only the top-level names are shimmed; submodules must not load twice
    under two names (that would duplicate classes like Platform)."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.ingest.platforms")
