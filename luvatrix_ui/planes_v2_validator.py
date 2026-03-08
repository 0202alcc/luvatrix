from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any

from .planes_protocol import PlanesValidationError

REQUIRED_VISUAL_ARTIFACT_TYPES = (
    "screenshot",
    "recording",
    "replay_digest",
    "frame_step_snapshot",
    "debug_bundle",
)


@dataclass(frozen=True)
class ValidationDiagnostic:
    level: str
    code: str
    message: str
    path: str


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    diagnostics: tuple[ValidationDiagnostic, ...]


def load_split_bundle(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    manifest_path = root / "manifest.json"
    planes_dir = root / "planes"
    routes_dir = root / "routes"
    frames_dir = root / "frames"

    manifest = _load_json_object(manifest_path, "manifest.json")
    planes = _load_json_objects_from_dir(planes_dir, "planes")
    routes = _load_json_objects_from_dir(routes_dir, "routes")
    frames = _load_json_objects_from_dir(frames_dir, "frames")
    return manifest, planes, routes, frames


def validate_split_schema_documents(
    manifest: dict[str, Any],
    planes: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    *,
    strict: bool = True,
    permissive_compatibility_window: bool = False,
) -> ValidationResult:
    diagnostics: list[ValidationDiagnostic] = []

    _require_non_empty_str(manifest.get("planes_protocol_version"), "manifest.planes_protocol_version", diagnostics)
    _require_non_empty_str(manifest.get("camera_plane_id"), "manifest.camera_plane_id", diagnostics)

    plane_refs = manifest.get("planes")
    if not isinstance(plane_refs, list) or not plane_refs:
        diagnostics.append(
            ValidationDiagnostic(
                level="error",
                code="schema.manifest.planes",
                message="manifest.planes must be a non-empty list",
                path="manifest.planes",
            )
        )
    else:
        for idx, ref in enumerate(plane_refs):
            _require_non_empty_str(ref, f"manifest.planes[{idx}]", diagnostics)

    if not isinstance(planes, list) or not planes:
        diagnostics.append(
            ValidationDiagnostic(
                level="error",
                code="schema.planes",
                message="planes must be a non-empty list",
                path="planes",
            )
        )
    for idx, plane in enumerate(planes):
        if not isinstance(plane, dict):
            diagnostics.append(
                ValidationDiagnostic(
                    level="error",
                    code="schema.planes.object",
                    message="plane entry must be an object",
                    path=f"planes[{idx}]",
                )
            )
            continue
        _require_non_empty_str(plane.get("id"), f"planes[{idx}].id", diagnostics)
        _require_non_empty_str(plane.get("kind"), f"planes[{idx}].kind", diagnostics)
        if not isinstance(plane.get("k_hat_index"), int):
            diagnostics.append(
                ValidationDiagnostic(
                    level="error",
                    code="schema.planes.k_hat_index",
                    message="k_hat_index must be an integer",
                    path=f"planes[{idx}].k_hat_index",
                )
            )
        _require_non_empty_str(plane.get("default_frame"), f"planes[{idx}].default_frame", diagnostics)

    _validate_named_refs(routes, "routes", diagnostics)
    _validate_named_refs(frames, "frames", diagnostics)
    _validate_cross_file_invariants(manifest, planes, routes, frames, diagnostics)

    has_error = any(d.level == "error" for d in diagnostics)
    if strict and has_error:
        first = next(d for d in diagnostics if d.level == "error")
        raise PlanesValidationError(f"{first.code}: {first.message} ({first.path})")

    if not strict and permissive_compatibility_window and has_error:
        diagnostics = [
            ValidationDiagnostic(
                level="warning",
                code=f"permissive.{item.code}",
                message=item.message,
                path=item.path,
            )
            for item in diagnostics
        ]
        return ValidationResult(valid=True, diagnostics=tuple(sorted(diagnostics, key=lambda d: (d.path, d.code))))

    return ValidationResult(valid=not has_error, diagnostics=tuple(sorted(diagnostics, key=lambda d: (d.path, d.code))))


def validate_split_schema_bundle(root: Path, *, strict: bool = True) -> ValidationResult:
    manifest, planes, routes, frames = load_split_bundle(root)
    permissive_compatibility_window = bool(manifest.get("compatibility_window"))
    return validate_split_schema_documents(
        manifest,
        planes,
        routes,
        frames,
        strict=strict,
        permissive_compatibility_window=permissive_compatibility_window,
    )


def render_diagnostics(result: ValidationResult) -> tuple[str, ...]:
    return tuple(
        f"{row.level.upper()} {row.code} {row.path}: {row.message}"
        for row in sorted(result.diagnostics, key=lambda d: (d.path, d.code))
    )


def validate_visual_evidence_manifest(manifest: dict[str, Any], *, strict: bool = True) -> ValidationResult:
    diagnostics: list[ValidationDiagnostic] = []
    if not isinstance(manifest, dict):
        raise PlanesValidationError("visual evidence manifest must be an object")

    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        diagnostics.append(
            ValidationDiagnostic(
                level="error",
                code="evidence.entries.required",
                message="entries must be a non-empty list",
                path="entries",
            )
        )
    else:
        seen_types: set[str] = set()
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                diagnostics.append(
                    ValidationDiagnostic(
                        level="error",
                        code="evidence.entry.object",
                        message="entry must be an object",
                        path=f"entries[{idx}]",
                    )
                )
                continue
            _require_non_empty_str(entry.get("commit_sha"), f"entries[{idx}].commit_sha", diagnostics)
            _require_non_empty_str(entry.get("command"), f"entries[{idx}].command", diagnostics)
            _require_non_empty_str(entry.get("timestamp"), f"entries[{idx}].timestamp", diagnostics)
            _require_non_empty_str(entry.get("scenario"), f"entries[{idx}].scenario", diagnostics)
            if not isinstance(entry.get("seed"), int):
                diagnostics.append(
                    ValidationDiagnostic(
                        level="error",
                        code="evidence.entry.seed",
                        message="seed must be an integer",
                        path=f"entries[{idx}].seed",
                    )
                )
            _require_non_empty_str(entry.get("artifact_path"), f"entries[{idx}].artifact_path", diagnostics)
            _require_non_empty_str(entry.get("artifact_digest"), f"entries[{idx}].artifact_digest", diagnostics)
            _require_non_empty_str(entry.get("sidecar_path"), f"entries[{idx}].sidecar_path", diagnostics)
            _require_non_empty_str(entry.get("sidecar_digest"), f"entries[{idx}].sidecar_digest", diagnostics)
            artifact_type = entry.get("artifact_type")
            if not isinstance(artifact_type, str) or not artifact_type.strip():
                diagnostics.append(
                    ValidationDiagnostic(
                        level="error",
                        code="evidence.entry.artifact_type",
                        message="artifact_type must be a non-empty string",
                        path=f"entries[{idx}].artifact_type",
                    )
                )
            elif artifact_type not in REQUIRED_VISUAL_ARTIFACT_TYPES:
                diagnostics.append(
                    ValidationDiagnostic(
                        level="error",
                        code="evidence.entry.artifact_type",
                        message=f"artifact_type `{artifact_type}` is not supported",
                        path=f"entries[{idx}].artifact_type",
                    )
                )
            else:
                seen_types.add(artifact_type)

        for artifact_type in REQUIRED_VISUAL_ARTIFACT_TYPES:
            if artifact_type not in seen_types:
                diagnostics.append(
                    ValidationDiagnostic(
                        level="error",
                        code="evidence.matrix.required_artifact",
                        message=f"required artifact type `{artifact_type}` missing from entries",
                        path="entries",
                    )
                )

    has_error = any(d.level == "error" for d in diagnostics)
    if strict and has_error:
        first = next(d for d in diagnostics if d.level == "error")
        raise PlanesValidationError(f"{first.code}: {first.message} ({first.path})")
    return ValidationResult(valid=not has_error, diagnostics=tuple(sorted(diagnostics, key=lambda d: (d.path, d.code))))


def _validate_named_refs(items: list[dict[str, Any]], label: str, diagnostics: list[ValidationDiagnostic]) -> None:
    if not isinstance(items, list):
        diagnostics.append(
            ValidationDiagnostic(
                level="error",
                code=f"schema.{label}",
                message=f"{label} must be a list",
                path=label,
            )
        )
        return
    for idx, row in enumerate(items):
        if not isinstance(row, dict):
            diagnostics.append(
                ValidationDiagnostic(
                    level="error",
                    code=f"schema.{label}.object",
                    message=f"{label} entry must be an object",
                    path=f"{label}[{idx}]",
                )
            )
            continue
        _require_non_empty_str(row.get("id"), f"{label}[{idx}].id", diagnostics)


def _validate_cross_file_invariants(
    manifest: dict[str, Any],
    planes: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    diagnostics: list[ValidationDiagnostic],
) -> None:
    plane_by_id: dict[str, dict[str, Any]] = {}
    duplicate_plane_ids: set[str] = set()
    for idx, plane in enumerate(planes):
        if not isinstance(plane, dict):
            continue
        plane_id = plane.get("id")
        if not isinstance(plane_id, str) or not plane_id.strip():
            continue
        if plane_id in plane_by_id:
            duplicate_plane_ids.add(plane_id)
        else:
            plane_by_id[plane_id] = plane
    for plane_id in sorted(duplicate_plane_ids):
        diagnostics.append(
            ValidationDiagnostic(
                level="error",
                code="invariant.planes.duplicate_id",
                message=f"duplicate plane id `{plane_id}`",
                path="planes",
            )
        )

    camera_plane_id = manifest.get("camera_plane_id")
    if isinstance(camera_plane_id, str) and camera_plane_id.strip():
        camera_plane = plane_by_id.get(camera_plane_id)
        if camera_plane is None:
            diagnostics.append(
                ValidationDiagnostic(
                    level="error",
                    code="invariant.camera.exists",
                    message=f"camera plane `{camera_plane_id}` must exist in planes",
                    path="manifest.camera_plane_id",
                )
            )
        else:
            if camera_plane.get("kind") != "camera":
                diagnostics.append(
                    ValidationDiagnostic(
                        level="error",
                        code="invariant.camera.kind",
                        message="camera plane kind must be `camera`",
                        path="manifest.camera_plane_id",
                    )
                )
            if camera_plane.get("k_hat_index") != 0:
                diagnostics.append(
                    ValidationDiagnostic(
                        level="error",
                        code="invariant.camera.k_hat_index",
                        message="camera plane k_hat_index must be 0",
                        path="manifest.camera_plane_id",
                    )
                )

    frame_ids = {
        frame.get("id")
        for frame in frames
        if isinstance(frame, dict) and isinstance(frame.get("id"), str) and frame.get("id", "").strip()
    }
    for idx, plane in enumerate(planes):
        if not isinstance(plane, dict):
            continue
        if plane.get("kind") == "world" and isinstance(plane.get("k_hat_index"), int) and plane.get("k_hat_index") >= 0:
            diagnostics.append(
                ValidationDiagnostic(
                    level="error",
                    code="invariant.world.k_hat_index",
                    message="world planes must have k_hat_index < 0",
                    path=f"planes[{idx}].k_hat_index",
                )
            )
        default_frame = plane.get("default_frame")
        if isinstance(default_frame, str) and frame_ids and default_frame not in frame_ids:
            diagnostics.append(
                ValidationDiagnostic(
                    level="error",
                    code="invariant.plane.frame_ref",
                    message=f"default_frame `{default_frame}` must reference an existing frame id",
                    path=f"planes[{idx}].default_frame",
                )
            )

    _validate_attachment_cycles(planes, diagnostics)

    route_by_id: dict[str, dict[str, Any]] = {}
    for idx, route in enumerate(routes):
        if not isinstance(route, dict):
            continue
        route_id = route.get("id")
        if not isinstance(route_id, str) or not route_id.strip():
            continue
        if route_id in route_by_id:
            diagnostics.append(
                ValidationDiagnostic(
                    level="error",
                    code="invariant.routes.duplicate_id",
                    message=f"duplicate route id `{route_id}`",
                    path="routes",
                )
            )
            continue
        route_by_id[route_id] = route
        for active_idx, plane_id in enumerate(route.get("active_planes", []) if isinstance(route.get("active_planes"), list) else []):
            if not isinstance(plane_id, str) or plane_id not in plane_by_id:
                diagnostics.append(
                    ValidationDiagnostic(
                        level="error",
                        code="invariant.routes.active_plane_ref",
                        message=f"active plane `{plane_id}` must reference an existing plane id",
                        path=f"routes[{idx}].active_planes[{active_idx}]",
                    )
                )
        startup_frame_id = route.get("startup_frame_id")
        if isinstance(startup_frame_id, str) and startup_frame_id.strip() and frame_ids and startup_frame_id not in frame_ids:
            diagnostics.append(
                ValidationDiagnostic(
                    level="error",
                    code="invariant.routes.startup_frame_ref",
                    message=f"startup_frame_id `{startup_frame_id}` must reference an existing frame id",
                    path=f"routes[{idx}].startup_frame_id",
                )
            )

    startup_route_id = manifest.get("startup_route_id")
    if isinstance(startup_route_id, str) and startup_route_id.strip() and startup_route_id not in route_by_id:
        diagnostics.append(
            ValidationDiagnostic(
                level="error",
                code="invariant.manifest.startup_route_ref",
                message=f"startup_route_id `{startup_route_id}` must reference an existing route id",
                path="manifest.startup_route_id",
            )
        )


def _validate_attachment_cycles(planes: list[dict[str, Any]], diagnostics: list[ValidationDiagnostic]) -> None:
    graph: dict[str, str] = {}
    for plane in planes:
        if not isinstance(plane, dict):
            continue
        plane_id = plane.get("id")
        attach_to = plane.get("attach_to")
        if isinstance(plane_id, str) and plane_id.strip() and isinstance(attach_to, str) and attach_to.strip():
            graph[plane_id] = attach_to

    for start in sorted(graph):
        seen: dict[str, int] = {}
        node = start
        while node in graph:
            if node in seen:
                diagnostics.append(
                    ValidationDiagnostic(
                        level="error",
                        code="invariant.planes.attachment_cycle",
                        message=f"attachment cycle detected starting at `{start}`",
                        path=f"planes[{start}].attach_to",
                    )
                )
                break
            seen[node] = 1
            node = graph[node]


def _require_non_empty_str(value: Any, path: str, diagnostics: list[ValidationDiagnostic]) -> None:
    if not isinstance(value, str) or not value.strip():
        diagnostics.append(
            ValidationDiagnostic(
                level="error",
                code="schema.required_string",
                message="must be a non-empty string",
                path=path,
            )
        )


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise PlanesValidationError(f"missing required file: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PlanesValidationError(f"{label} must be a JSON object")
    return raw


def _load_json_objects_from_dir(path: Path, label: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for file_path in sorted(path.glob("*.json")):
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise PlanesValidationError(f"{label} file must be a JSON object: {file_path}")
        rows.append(raw)
    return rows
