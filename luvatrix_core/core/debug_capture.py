from __future__ import annotations

import hashlib
from dataclasses import dataclass


REQUIRED_SCREENSHOT_SIDECAR_KEYS: tuple[str, ...] = (
    "route",
    "revision",
    "captured_at_utc",
    "provenance_id",
)

REQUIRED_RECORDING_MANIFEST_KEYS: tuple[str, ...] = (
    "session_id",
    "route",
    "revision",
    "started_at_utc",
    "stopped_at_utc",
    "provenance_id",
    "frame_count",
    "platform",
)

REQUIRED_REPLAY_MANIFEST_KEYS: tuple[str, ...] = (
    "session_id",
    "seed",
    "platform",
    "ordering_digest",
    "event_count",
    "recorded_at_utc",
)

REQUIRED_PERF_HUD_KEYS: tuple[str, ...] = (
    "frame_index",
    "frame_time_ms",
    "fps",
    "present_mode",
    "ordering_digest",
)

REQUIRED_BUNDLE_MANIFEST_KEYS: tuple[str, ...] = (
    "bundle_id",
    "platform",
    "exported_at_utc",
    "provenance_id",
    "artifact_paths",
    "artifact_classes",
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


@dataclass(frozen=True)
class RecordingBudgetEnvelope:
    start_overhead_ms: float
    stop_overhead_ms: float
    steady_overhead_ms: float


@dataclass(frozen=True)
class RecordingBudgetResult:
    passed: bool
    exceeded_limits: tuple[str, ...]
    observed_start_overhead_ms: float
    observed_stop_overhead_ms: float
    observed_steady_overhead_ms: float


@dataclass(frozen=True)
class OverlayRect:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class OverlaySpec:
    overlay_id: str
    bounds: OverlayRect
    dirty_rects: tuple[OverlayRect, ...]
    coordinate_space: str
    opacity: float
    enabled: bool


@dataclass(frozen=True)
class OverlayToggleResult:
    overlay_id: str
    previous_enabled: bool
    next_enabled: bool
    content_digest_before: str
    content_digest_after: str
    destructive: bool


@dataclass(frozen=True)
class ReplayInputEvent:
    sequence: int
    timestamp_ms: int
    event_type: str
    payload_digest: str


@dataclass(frozen=True)
class ReplayContractResult:
    session_id: str
    seed: int
    platform: str
    event_count: int
    ordering_digest: str
    deterministic: bool
    expected_digest: str | None = None


@dataclass(frozen=True)
class FrameStepState:
    paused: bool
    frame_index: int
    last_ordering_digest: str


@dataclass(frozen=True)
class PerfHUDSnapshot:
    frame_index: int
    frame_time_ms: float
    fps: float
    present_mode: str
    ordering_digest: str


@dataclass(frozen=True)
class DebugBundleExport:
    bundle_id: str
    zip_path: str
    manifest: dict[str, object]


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
                "debug.capture.screenshot.clipboard",
                "debug.capture.screenshot.sidecar",
                "debug.capture.record",
                "debug.overlay.render",
                "debug.replay.record",
                "debug.replay.start",
                "debug.frame.step",
                "debug.perf.hud",
                "debug.bundle.export",
            ),
            unsupported_reason=None,
        ),
        DebugCapturePlatformSpec(
            platform="windows",
            supported=False,
            declared_capabilities=(
                "debug.capture.windows.stub",
                "debug.capture.screenshot.stub",
                "debug.capture.screenshot.clipboard.stub",
                "debug.capture.record.stub",
                "debug.overlay.stub",
                "debug.replay.stub",
                "debug.frame.step.stub",
                "debug.perf.hud.stub",
                "debug.bundle.stub",
            ),
            unsupported_reason="macOS-first phase: explicit stub only",
        ),
        DebugCapturePlatformSpec(
            platform="linux",
            supported=False,
            declared_capabilities=(
                "debug.capture.linux.stub",
                "debug.capture.screenshot.stub",
                "debug.capture.screenshot.clipboard.stub",
                "debug.capture.record.stub",
                "debug.overlay.stub",
                "debug.replay.stub",
                "debug.frame.step.stub",
                "debug.perf.hud.stub",
                "debug.bundle.stub",
            ),
            unsupported_reason="macOS-first phase: explicit stub only",
        ),
        DebugCapturePlatformSpec(
            platform="web",
            supported=False,
            declared_capabilities=(
                "debug.capture.web.stub",
                "debug.capture.screenshot.stub",
                "debug.capture.screenshot.clipboard.stub",
                "debug.capture.record.stub",
                "debug.overlay.stub",
                "debug.replay.stub",
                "debug.frame.step.stub",
                "debug.perf.hud.stub",
                "debug.bundle.stub",
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


def build_recording_manifest(
    *,
    session_id: str,
    route: str,
    revision: str,
    started_at_utc: str,
    stopped_at_utc: str,
    provenance_id: str,
    frame_count: int,
    platform: str = "macos",
) -> dict[str, str | int]:
    manifest: dict[str, str | int] = {
        "session_id": session_id.strip(),
        "route": route.strip(),
        "revision": revision.strip(),
        "started_at_utc": started_at_utc.strip(),
        "stopped_at_utc": stopped_at_utc.strip(),
        "provenance_id": provenance_id.strip(),
        "frame_count": int(frame_count),
        "platform": platform.strip(),
    }
    for key in REQUIRED_RECORDING_MANIFEST_KEYS:
        if key == "frame_count":
            if int(manifest[key]) < 0:
                raise ValueError("frame_count must be >= 0")
            continue
        if not str(manifest[key]).strip():
            raise ValueError(f"missing required recording manifest field: {key}")
    return manifest


def evaluate_recording_budget(
    *,
    envelope: RecordingBudgetEnvelope,
    observed_start_overhead_ms: float,
    observed_stop_overhead_ms: float,
    observed_steady_overhead_ms: float,
) -> RecordingBudgetResult:
    exceeded: list[str] = []
    if float(observed_start_overhead_ms) > float(envelope.start_overhead_ms):
        exceeded.append("start_overhead_ms")
    if float(observed_stop_overhead_ms) > float(envelope.stop_overhead_ms):
        exceeded.append("stop_overhead_ms")
    if float(observed_steady_overhead_ms) > float(envelope.steady_overhead_ms):
        exceeded.append("steady_overhead_ms")
    return RecordingBudgetResult(
        passed=not exceeded,
        exceeded_limits=tuple(exceeded),
        observed_start_overhead_ms=float(observed_start_overhead_ms),
        observed_stop_overhead_ms=float(observed_stop_overhead_ms),
        observed_steady_overhead_ms=float(observed_steady_overhead_ms),
    )


def build_overlay_spec(
    *,
    overlay_id: str,
    bounds: OverlayRect,
    dirty_rects: tuple[OverlayRect, ...],
    coordinate_space: str,
    opacity: float,
    enabled: bool,
) -> OverlaySpec:
    spec = OverlaySpec(
        overlay_id=overlay_id.strip(),
        bounds=bounds,
        dirty_rects=dirty_rects,
        coordinate_space=coordinate_space.strip(),
        opacity=float(opacity),
        enabled=bool(enabled),
    )
    validate_overlay_spec(spec)
    return spec


def validate_overlay_spec(spec: OverlaySpec) -> None:
    if not spec.overlay_id:
        raise ValueError("overlay_id must be non-empty")
    if spec.coordinate_space not in {"window_px", "content_px"}:
        raise ValueError("overlay coordinate_space must be one of: window_px, content_px")
    if not (0.0 <= spec.opacity <= 1.0):
        raise ValueError("overlay opacity must be in [0.0, 1.0]")
    _validate_overlay_rect(spec.bounds, field_name="bounds")
    for idx, rect in enumerate(spec.dirty_rects):
        _validate_overlay_rect(rect, field_name=f"dirty_rects[{idx}]")


def toggle_overlay_non_destructive(
    *,
    overlay_id: str,
    previous_enabled: bool,
    next_enabled: bool,
    content_digest: str,
) -> OverlayToggleResult:
    digest = content_digest.strip()
    if not digest:
        raise ValueError("content_digest must be non-empty")
    return OverlayToggleResult(
        overlay_id=overlay_id.strip(),
        previous_enabled=bool(previous_enabled),
        next_enabled=bool(next_enabled),
        content_digest_before=digest,
        content_digest_after=digest,
        destructive=False,
    )


def _validate_overlay_rect(rect: OverlayRect, *, field_name: str) -> None:
    if rect.width < 0 or rect.height < 0:
        raise ValueError(f"{field_name} width/height must be >= 0")


def build_replay_manifest(
    *,
    session_id: str,
    seed: int,
    platform: str,
    ordering_digest: str,
    event_count: int,
    recorded_at_utc: str,
) -> dict[str, str | int]:
    manifest: dict[str, str | int] = {
        "session_id": session_id.strip(),
        "seed": int(seed),
        "platform": platform.strip(),
        "ordering_digest": ordering_digest.strip(),
        "event_count": int(event_count),
        "recorded_at_utc": recorded_at_utc.strip(),
    }
    for key in REQUIRED_REPLAY_MANIFEST_KEYS:
        value = manifest[key]
        if key in {"seed", "event_count"}:
            if int(value) < 0:
                raise ValueError(f"{key} must be >= 0")
            continue
        if not str(value).strip():
            raise ValueError(f"missing required replay manifest field: {key}")
    return manifest


def compute_replay_ordering_digest(events: tuple[ReplayInputEvent, ...]) -> str:
    if not events:
        raise ValueError("events must be non-empty")
    canonical = "|".join(
        f"{event.sequence}:{event.timestamp_ms}:{event.event_type}:{event.payload_digest}" for event in events
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evaluate_replay_determinism(
    *,
    session_id: str,
    seed: int,
    platform: str,
    events: tuple[ReplayInputEvent, ...],
    expected_digest: str | None = None,
) -> ReplayContractResult:
    digest = compute_replay_ordering_digest(events)
    expected = expected_digest.strip() if expected_digest else None
    deterministic = expected is None or digest == expected
    return ReplayContractResult(
        session_id=session_id.strip(),
        seed=int(seed),
        platform=platform.strip(),
        event_count=len(events),
        ordering_digest=digest,
        deterministic=deterministic,
        expected_digest=expected,
    )


def frame_step_advance(state: FrameStepState, *, next_ordering_digest: str) -> FrameStepState:
    digest = next_ordering_digest.strip()
    if not digest:
        raise ValueError("next_ordering_digest must be non-empty")
    if not state.paused:
        raise ValueError("frame-step requires paused state")
    return FrameStepState(
        paused=True,
        frame_index=state.frame_index + 1,
        last_ordering_digest=digest,
    )


def build_perf_hud_snapshot(
    *,
    frame_index: int,
    frame_time_ms: float,
    present_mode: str,
    ordering_digest: str,
) -> dict[str, str | float | int]:
    if frame_index < 0:
        raise ValueError("frame_index must be >= 0")
    frame_time = float(frame_time_ms)
    if frame_time <= 0:
        raise ValueError("frame_time_ms must be > 0")
    digest = ordering_digest.strip()
    if not digest:
        raise ValueError("ordering_digest must be non-empty")
    mode = present_mode.strip()
    if not mode:
        raise ValueError("present_mode must be non-empty")
    snapshot = {
        "frame_index": int(frame_index),
        "frame_time_ms": frame_time,
        "fps": round(1000.0 / frame_time, 3),
        "present_mode": mode,
        "ordering_digest": digest,
    }
    for key in REQUIRED_PERF_HUD_KEYS:
        value = snapshot.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"missing required perf HUD field: {key}")
    return snapshot


def build_debug_bundle_manifest(
    *,
    bundle_id: str,
    platform: str,
    exported_at_utc: str,
    provenance_id: str,
    artifact_paths: tuple[str, ...],
    artifact_classes: tuple[str, ...],
) -> dict[str, object]:
    normalized_paths = tuple(path.strip() for path in artifact_paths if path.strip())
    normalized_classes = tuple(kind.strip() for kind in artifact_classes if kind.strip())
    manifest: dict[str, object] = {
        "bundle_id": bundle_id.strip(),
        "platform": platform.strip(),
        "exported_at_utc": exported_at_utc.strip(),
        "provenance_id": provenance_id.strip(),
        "artifact_paths": list(normalized_paths),
        "artifact_classes": list(normalized_classes),
    }
    for key in REQUIRED_BUNDLE_MANIFEST_KEYS:
        value = manifest.get(key)
        if value is None:
            raise ValueError(f"missing required bundle manifest field: {key}")
        if isinstance(value, str) and not value.strip():
            raise ValueError(f"missing required bundle manifest field: {key}")
        if isinstance(value, list) and not value:
            raise ValueError(f"missing required bundle manifest field: {key}")
    return manifest


def bundle_has_required_artifact_classes(
    manifest: dict[str, object],
    *,
    required_classes: tuple[str, ...] = ("captures", "replay", "perf", "provenance"),
) -> bool:
    classes = manifest.get("artifact_classes")
    if not isinstance(classes, list):
        return False
    declared = {str(item).strip() for item in classes if str(item).strip()}
    return all(required in declared for required in required_classes)


def build_debug_bundle_export(
    *,
    bundle_id: str,
    platform: str,
    exported_at_utc: str,
    provenance_id: str,
    artifact_paths: tuple[str, ...],
    artifact_classes: tuple[str, ...],
    output_dir: str = "artifacts/debug_bundles",
) -> DebugBundleExport:
    normalized_bundle_id = bundle_id.strip()
    if not normalized_bundle_id:
        raise ValueError("bundle_id must be non-empty")
    manifest = build_debug_bundle_manifest(
        bundle_id=normalized_bundle_id,
        platform=platform,
        exported_at_utc=exported_at_utc,
        provenance_id=provenance_id,
        artifact_paths=artifact_paths,
        artifact_classes=artifact_classes,
    )
    zip_path = f"{output_dir.rstrip('/')}/{normalized_bundle_id}.zip"
    return DebugBundleExport(
        bundle_id=normalized_bundle_id,
        zip_path=zip_path,
        manifest=manifest,
    )
