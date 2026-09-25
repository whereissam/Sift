"""Regression test for SpeakerDiarizer.is_available().

find_spec("pyannote.audio") raises ModuleNotFoundError (rather than returning
None) when the parent `pyannote` package is not installed. That crashed the
/api/health endpoint with a 500. is_available() must swallow it and return a
plain bool.
"""

import importlib.util

from sift_core.transcribe.diarizer import SpeakerDiarizer


def test_is_available_returns_bool_without_raising():
    # Must never raise, regardless of whether pyannote is installed.
    result = SpeakerDiarizer.is_available()
    assert isinstance(result, bool)


def test_is_available_false_when_parent_package_missing(monkeypatch):
    """Simulate find_spec raising ModuleNotFoundError for the missing parent."""

    def boom(name, *args, **kwargs):
        raise ModuleNotFoundError("No module named 'pyannote'", name="pyannote")

    monkeypatch.setattr(importlib.util, "find_spec", boom)
    assert SpeakerDiarizer.is_available() is False
