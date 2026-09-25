"""The layer fence.

`sift_core` (packages/sift-core) is the core: platform adapters, download,
media conversion, transcription. Everything in `app/` is built on top of it.
That direction already held when the layers were carved out of the old flat
`app/core/`, but nothing kept it true — this test does.

It exists because the failure mode is invisible: one convenient import from
the core into knowledge costs nothing today and quietly makes it
un-shippable on its own, which is the whole point of the package.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
CORE_SRC = ROOT / "packages" / "sift-core" / "src"
CORE = CORE_SRC / "sift_core"


def _imported_modules(path: Path, src_root: Path = ROOT) -> set[str]:
    """Absolute dotted module names this file imports, relatives resolved."""
    tree = ast.parse(path.read_text(), filename=str(path))
    package = path.relative_to(src_root).parent.parts
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = list(package[: len(package) - (node.level - 1)])
                found.add(".".join(base + (node.module.split(".") if node.module else [])))
            elif node.module:
                found.add(node.module)
    return found


def _sources(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*.py") if "__pycache__" not in p.parts)


def _python_files(layer: str) -> list[Path]:
    return _sources(APP / layer)


@pytest.mark.parametrize("path", _sources(CORE), ids=lambda p: str(p.relative_to(CORE_SRC)))
def test_core_never_imports_the_app(path: Path):
    """The core must run with no `app` package installed at all. It gets
    configuration through `sift_core.settings`, which the app feeds from
    above (see docs/architecture.md)."""
    for module in _imported_modules(path, CORE_SRC):
        assert module != "app" and not module.startswith("app."), (
            f"{path.relative_to(CORE_SRC)} imports {module}. sift_core cannot "
            f"depend on the app — take the value as a parameter or through "
            f"sift_core.settings instead."
        )


def test_app_ingest_is_only_the_deprecation_shim():
    """New code must not grow back into app/ingest/."""
    shim = APP / "ingest"
    assert [p.name for p in _sources(shim)] == ["__init__.py"]


@pytest.mark.parametrize(
    "path",
    [p for p in _sources(APP) + _sources(ROOT / "tests") if p.parent != APP / "ingest"],
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_nothing_in_the_repo_uses_the_shim(path: Path):
    for module in _imported_modules(path):
        assert module != "app.ingest" and not module.startswith("app.ingest."), (
            f"{path.relative_to(ROOT)} imports {module}; import from sift_core."
        )


@pytest.mark.parametrize(
    "path", _python_files("knowledge"), ids=lambda p: str(p.relative_to(APP))
)
def test_knowledge_never_imports_the_api_or_pipeline(path: Path):
    """Knowledge is a library, not a caller: orchestration lives in pipeline."""
    for module in _imported_modules(path):
        for layer in ("api", "pipeline", "bot", "mcp_server"):
            assert not module.startswith(f"app.{layer}"), (
                f"{path.relative_to(APP)} imports {module}. Knowledge modules "
                f"are called by app.{layer}, never the other way round."
            )


def test_the_old_flat_core_package_is_gone():
    """A leftover app/core would let new code re-enter the flat layout.

    Checks for source, not for the directory: switching to a branch that
    predates the split and running the suite there leaves an `app/ingest/
    __pycache__` behind, and stale bytecode is not a layering violation.
    """
    core = APP / "core"
    stale = sorted(p.name for p in core.rglob("*.py")) if core.exists() else []
    assert not stale, f"app/ingest/ is back ({', '.join(stale)}) — put it in a layer"


def test_every_layer_is_a_real_package():
    assert (CORE / "__init__.py").exists(), "sift_core needs __init__.py"
    for layer in ("knowledge", "delivery", "pipeline", "store"):
        assert (APP / layer / "__init__.py").exists(), f"app/{layer} needs __init__.py"
