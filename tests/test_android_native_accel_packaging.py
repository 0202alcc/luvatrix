from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from luvatrix_core.platform.android.runner import sync_android_accelerator_wheels


ROOT = Path(__file__).resolve().parents[1]


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_android_accelerator_downloads_verified_wheels_and_writes_requirement() -> None:
    version = "9.8.7"
    wheel_payloads = {
        "https://files.example/arm.whl": b"arm-wheel",
        "https://files.example/x86.whl": b"x86-wheel",
    }
    files = []
    for abi, url in (("arm64_v8a", "https://files.example/arm.whl"), ("x86_64", "https://files.example/x86.whl")):
        payload = wheel_payloads[url]
        files.append(
            {
                "filename": f"luvatrix-{version}-cp314-cp314-android_26_{abi}.whl",
                "url": url,
                "digests": {"sha256": hashlib.sha256(payload).hexdigest()},
            }
        )
    release = json.dumps({"urls": files}).encode()

    def open_url(url, timeout=20):
        _ = timeout
        if str(url).endswith(f"/{version}/json"):
            return _Response(release)
        return _Response(wheel_payloads[str(url)])

    with tempfile.TemporaryDirectory() as td, patch(
        "luvatrix_core.platform.android.runner.urllib.request.urlopen",
        side_effect=open_url,
    ):
        project = Path(td)
        synced = sync_android_accelerator_wheels(project, version=version)

        assert len(synced) == 2
        assert all(path.read_bytes() in wheel_payloads.values() for path in synced)
        assert (project / "app" / "luvatrix-android-accel.txt").read_text() == f"luvatrix=={version}\n"


def test_android_accelerator_rejects_incomplete_abi_set() -> None:
    release = json.dumps({"urls": []}).encode()
    with tempfile.TemporaryDirectory() as td, patch(
        "luvatrix_core.platform.android.runner.urllib.request.urlopen",
        return_value=_Response(release),
    ):
        project = Path(td)
        assert sync_android_accelerator_wheels(project, version="9.8.7") == ()
        assert not (project / "app" / "luvatrix-android-accel.txt").exists()


def test_android_accelerator_keeps_cached_release_when_pypi_is_unavailable() -> None:
    version = "9.8.7"
    with tempfile.TemporaryDirectory() as td:
        project = Path(td)
        app_dir = project / "app"
        wheel_dir = app_dir / "wheels"
        wheel_dir.mkdir(parents=True)
        cached = (
            wheel_dir / f"luvatrix-{version}-cp314-cp314-android_26_arm64_v8a.whl",
            wheel_dir / f"luvatrix-{version}-cp314-cp314-android_26_x86_64.whl",
        )
        for path in cached:
            path.write_bytes(b"cached-wheel")
        requirement = app_dir / "luvatrix-android-accel.txt"
        requirement.write_text(f"luvatrix=={version}\n", encoding="utf-8")

        with patch(
            "luvatrix_core.platform.android.runner.urllib.request.urlopen",
            side_effect=OSError("offline"),
        ):
            assert sync_android_accelerator_wheels(project, version=version) == tuple(
                path.resolve() for path in cached
            )

        assert requirement.read_text(encoding="utf-8") == f"luvatrix=={version}\n"


def test_android_accelerator_preserves_cache_when_refresh_fails_partway() -> None:
    version = "9.8.7"
    old_payload = b"cached-wheel"
    new_payload = b"new-wheel"
    files = [
        {
            "filename": f"luvatrix-{version}-cp314-cp314-android_26_{abi}.whl",
            "url": f"https://files.example/{abi}.whl",
            "digests": {"sha256": hashlib.sha256(new_payload).hexdigest()},
        }
        for abi in ("arm64_v8a", "x86_64")
    ]
    release = json.dumps({"urls": files}).encode()

    def open_url(url, timeout=20):
        _ = timeout
        if str(url).endswith(f"/{version}/json"):
            return _Response(release)
        if str(url).endswith("arm64_v8a.whl"):
            return _Response(new_payload)
        raise OSError("download interrupted")

    with tempfile.TemporaryDirectory() as td, patch(
        "luvatrix_core.platform.android.runner.urllib.request.urlopen",
        side_effect=open_url,
    ):
        project = Path(td)
        app_dir = project / "app"
        wheel_dir = app_dir / "wheels"
        wheel_dir.mkdir(parents=True)
        cached = tuple(
            wheel_dir / f"luvatrix-{version}-cp314-cp314-android_26_{abi}.whl"
            for abi in ("arm64_v8a", "x86_64")
        )
        for path in cached:
            path.write_bytes(old_payload)
        requirement = app_dir / "luvatrix-android-accel.txt"
        requirement.write_text(f"luvatrix=={version}\n", encoding="utf-8")

        assert sync_android_accelerator_wheels(project, version=version) == tuple(
            path.resolve() for path in cached
        )
        assert all(path.read_bytes() == old_payload for path in cached)


def test_release_workflow_builds_cp314_android_accelerator_wheels() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish-pypi.yml").read_text(encoding="utf-8")
    assert "cibuildwheel" in workflow
    assert "cp314-android_arm64_v8a" in workflow
    assert "cp314-android_x86_64" in workflow
    assert "LUVATRIX_BUILD_ACCEL" in workflow


def test_android_gradle_installs_synced_accelerator_without_dependencies() -> None:
    for root in (ROOT / "android", ROOT / "luvatrix_core" / "templates" / "native" / "android"):
        build = (root / "app" / "build.gradle.kts").read_text(encoding="utf-8")
        assert "luvatrix-android-accel.txt" in build
        assert "--find-links" in build
        assert "--no-deps" in build
