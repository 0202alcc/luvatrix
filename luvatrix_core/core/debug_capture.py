from __future__ import annotations

from dataclasses import dataclass


REQUIRED_SCREENSHOT_SIDECAR_KEYS: tuple[str, ...] = (
    "route",
    "revision",
    "captured_at_utc",
    "provenance_id",
)


@dataclass(frozen=True)
class DebugCapturePlatformSpec:
    platform: str
    supported: bool
    declared_capabilities: tuple[str, ...]
    unsupported_reason: str | None = None


@dataclass(frozen=True)
class ScreenshotArtifactBundle:
    capture_id: str
    png_path: str
    sidecar_path: str
    sidecar: dict[str, str]


def build_screenshot_sidecar(
    *,
    route: str,
    revision: str,
    captured_at_utc: str,
    provenance_id: str,
    platform: str = "macos",
) -> dict[str, str]:
    sidecar = {
        "route": route.strip(),
        "revision": revision.strip(),
        "captured_at_utc": captured_at_utc.strip(),
        "provenance_id": provenance_id.strip(),
        "platform": platform.strip(),
    }
    _validate_required_sidecar_fields(sidecar)
    return sidecar


def build_screenshot_artifact_bundle(
    *,
    capture_id: str,
    route: str,
    revision: str,
    captured_at_utc: str,
    provenance_id: str,
    platform: str = "macos",
    output_dir: str = "captures",
) -> ScreenshotArtifactBundle:
    normalized_capture_id = capture_id.strip()
    if not normalized_capture_id:
        raise ValueError("capture_id must be non-empty")
    sidecar = build_screenshot_sidecar(
        route=route,
        revision=revision,
        captured_at_utc=captured_at_utc,
        provenance_id=provenance_id,
        platform=platform,
    )
    base = f"{output_dir.rstrip('/')}/{normalized_capture_id}"
    return ScreenshotArtifactBundle(
        capture_id=normalized_capture_id,
        png_path=f"{base}.png",
        sidecar_path=f"{base}.json",
        sidecar=sidecar,
    )


def screenshot_artifacts_are_atomic(*, png_written: bool, sidecar_written: bool) -> bool:
    return bool(png_written == sidecar_written)


def default_debug_capture_platform_specs() -> tuple[DebugCapturePlatformSpec, ...]:
    return (
        DebugCapturePlatformSpec(
            platform="macos",
            supported=True,
            declared_capabilities=(
                "debug.capture.screenshot",
                "debug.capture.screenshot.sidecar",
            ),
            unsupported_reason=None,
        ),
        DebugCapturePlatformSpec(
            platform="windows",
            supported=False,
            declared_capabilities=(
                "debug.capture.windows.stub",
                "debug.capture.screenshot.stub",
            ),
            unsupported_reason="macOS-first phase: explicit stub only",
        ),
        DebugCapturePlatformSpec(
            platform="linux",
            supported=False,
            declared_capabilities=(
                "debug.capture.linux.stub",
                "debug.capture.screenshot.stub",
            ),
            unsupported_reason="macOS-first phase: explicit stub only",
        ),
    )


def debug_capture_platform_capability_matrix() -> dict[str, dict[str, object]]:
    matrix: dict[str, dict[str, object]] = {}
    for spec in default_debug_capture_platform_specs():
        matrix[spec.platform] = {
            "supported": spec.supported,
            "declared_capabilities": list(spec.declared_capabilities),
            "unsupported_reason": spec.unsupported_reason,
        }
    return matrix


def _validate_required_sidecar_fields(sidecar: dict[str, str]) -> None:
    for key in REQUIRED_SCREENSHOT_SIDECAR_KEYS:
        if not sidecar.get(key, "").strip():
            raise ValueError(f"missing required screenshot sidecar field: {key}")
