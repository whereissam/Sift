"""Checksum verification in scripts/download_ffmpeg.py fails closed."""

import hashlib
import importlib.util
import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "download_ffmpeg.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("download_ffmpeg", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_matching_digest_passes(mod, tmp_path):
    f = tmp_path / "ffmpeg.zip"
    f.write_bytes(b"ffmpeg build")
    mod.verify_sha256(f, hashlib.sha256(b"ffmpeg build").hexdigest())


def test_digest_comparison_is_case_insensitive(mod, tmp_path):
    f = tmp_path / "ffmpeg.zip"
    f.write_bytes(b"ffmpeg build")
    mod.verify_sha256(f, hashlib.sha256(b"ffmpeg build").hexdigest().upper())


def test_tampered_file_fails(mod, tmp_path):
    f = tmp_path / "ffmpeg.zip"
    expected = hashlib.sha256(b"ffmpeg build").hexdigest()
    f.write_bytes(b"ffmpeg build + backdoor")
    with pytest.raises(mod.ChecksumMismatch):
        mod.verify_sha256(f, expected)


@pytest.mark.parametrize("bad", ["", "abc", "z" * 64])
def test_malformed_pin_is_rejected(mod, tmp_path, bad):
    f = tmp_path / "ffmpeg.zip"
    f.write_bytes(b"x")
    with pytest.raises(ValueError):
        mod.verify_sha256(f, bad)


def test_fetch_verified_deletes_mismatched_download(mod, tmp_path, monkeypatch):
    dest = tmp_path / "ffmpeg.tar.xz"

    def fake_curl(cmd, check):
        dest.write_bytes(b"not the pinned build")

    monkeypatch.setattr(mod.subprocess, "run", fake_curl)
    build = mod.Build(url="https://example.invalid/ffmpeg", sha256="0" * 64, version="0")
    with pytest.raises(mod.ChecksumMismatch):
        mod.fetch_verified(build, dest)
    assert not dest.exists()


def test_every_pinned_build_has_a_wellformed_sha256(mod):
    builds = [mod.MACOS_BUILD, *mod.LINUX_BUILDS.values()]
    for build in builds:
        assert re.fullmatch(r"[0-9a-f]{64}", build.sha256), build
        assert build.url.startswith("https://"), build
