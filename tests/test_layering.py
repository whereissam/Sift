"""The layer fence.

`app/ingest/` is the core: platform adapters, download, media conversion,
transcription. Everything else is built on top of it. That direction already
held when the layers were carved out of the old flat `app/ingest/`, but nothing
kept it true — this test does.

It exists because the failure mode is invisible: one convenient import from
ingest into knowledge costs nothing today and quietly makes the ingestion core
un-extractable, which is the thing that has to stay shippable on its own.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"

# Layers that sit above ingest and must never be imported from inside it.
ABOVE_INGEST = ("knowledge", "delivery", "pipeline", "api", "bot", "mcp_server")


def _imported_modules(path: Path) -> set[str]:
    """Absolute dotted module names this file imports, relatives resolved."""
    tree = ast.parse(path.read_text(), filename=str(path))
    package = path.relative_to(APP.parent).parent.parts
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


def _python_files(layer: str) -> list[Path]:
    return sorted(p for p in (APP / layer).rglob("*.py") if "__pycache__" not in p.parts)


@pytest.mark.parametrize(
    "path", _python_files("ingest"), ids=lambda p: str(p.relative_to(APP))
)
def test_ingest_never_imports_an_upper_layer(path: Path):
    """The ingestion core must stay runnable with nothing above it loaded."""
    for module in _imported_modules(path):
        for layer in ABOVE_INGEST:
            assert not module.startswith(f"app.{layer}"), (
                f"{path.relative_to(APP)} imports {module}. The ingestion core "
                f"cannot depend on app.{layer} — move the caller up a layer "
                f"instead (see docs/architecture.md)."
            )


@pytest.mark.parametrize(
    "path", _python_files("ingest"), ids=lambda p: str(p.relative_to(APP))
)
def test_ingest_imports_nothing_from_app_outside_itself(path: Path):
    """Stricter than the layer list: no `app.config`, `app.store`, or any
    future sibling either. The core gets configuration through
    `app.ingest.settings`, which the app feeds from above."""
    for module in _imported_modules(path):
        if module == "app" or module.startswith("app."):
            assert module == "app.ingest" or module.startswith("app.ingest."), (
                f"{path.relative_to(APP)} imports {module}. The ingestion core "
                f"may only import from app.ingest — take the value as a "
                f"parameter or through app.ingest.settings instead."
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
    for layer in ("ingest", "knowledge", "delivery", "pipeline", "store"):
        assert (APP / layer / "__init__.py").exists(), f"app/{layer} needs __init__.py"
