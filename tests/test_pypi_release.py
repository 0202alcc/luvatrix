from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "release" / "pypi_release.py"


def _load_release_module():
    spec = importlib.util.spec_from_file_location("pypi_release", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _distribution_names(version: str = "1.2.3") -> set[str]:
    return {
        f"luvatrix-{version}.tar.gz",
        f"luvatrix-{version}-py3-none-any.whl",
        f"luvatrix-{version}-cp314-cp314-android_26_arm64_v8a.whl",
        f"luvatrix-{version}-cp314-cp314-android_26_x86_64.whl",
    }


def test_distribution_validation_requires_the_complete_release_set() -> None:
    release = _load_release_module()
    names = _distribution_names()

    assert release.validate_distribution_names("luvatrix", "1.2.3", names) == names

    names.remove("luvatrix-1.2.3-cp314-cp314-android_26_x86_64.whl")
    with pytest.raises(ValueError, match="x86_64"):
        release.validate_distribution_names("luvatrix", "1.2.3", names)


def test_distribution_validation_rejects_unexpected_build_artifacts() -> None:
    release = _load_release_module()
    names = _distribution_names() | {"luvatrix-1.2.3-py2-none-any.whl"}

    with pytest.raises(ValueError, match="exactly four"):
        release.validate_distribution_names("luvatrix", "1.2.3", names)


def test_prepare_upload_recovers_only_missing_pypi_files() -> None:
    release = _load_release_module()
    names = _distribution_names()
    existing = {
        "luvatrix-1.2.3.tar.gz",
        "luvatrix-1.2.3-py3-none-any.whl",
    }

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        dist = root / "dist"
        upload = root / "upload"
        dist.mkdir()
        for name in names:
            (dist / name).write_bytes(name.encode())
        (dist / "build-notes.txt").write_text("not a distribution", encoding="utf-8")

        missing = release.prepare_upload(dist, upload, existing)

        assert {path.name for path in missing} == names - existing
        assert {path.name for path in upload.iterdir()} == names - existing


def test_prepare_upload_is_a_clean_noop_for_complete_release() -> None:
    release = _load_release_module()
    names = _distribution_names()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        dist = root / "dist"
        upload = root / "upload"
        dist.mkdir()
        upload.mkdir()
        (upload / "stale.whl").write_bytes(b"stale")
        for name in names:
            (dist / name).write_bytes(name.encode())

        assert release.prepare_upload(dist, upload, names) == ()
        assert list(upload.iterdir()) == []


def test_verify_release_rejects_a_partial_pypi_release() -> None:
    release = _load_release_module()
    names = _distribution_names()
    names.remove("luvatrix-1.2.3-cp314-cp314-android_26_arm64_v8a.whl")

    with patch.object(release, "fetch_release_filenames", return_value=names):
        with pytest.raises(RuntimeError, match="arm64_v8a"):
            release.verify_release("luvatrix", "1.2.3", attempts=1)


def test_verify_release_retries_while_pypi_indexes_files() -> None:
    release = _load_release_module()
    complete = _distribution_names()
    partial = complete - {
        "luvatrix-1.2.3-cp314-cp314-android_26_arm64_v8a.whl"
    }

    with patch.object(
        release,
        "fetch_release_filenames",
        side_effect=(partial, complete),
    ), patch.object(release.time, "sleep") as sleep:
        assert release.verify_release(
            "luvatrix",
            "1.2.3",
            attempts=2,
            retry_delay=0.01,
        ) == complete

    sleep.assert_called_once_with(0.01)
