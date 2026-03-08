from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any

from .planes_protocol import PlanesValidationError


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

    has_error = any(d.level == "error" for d in diagnostics)
    if strict and has_error:
        first = next(d for d in diagnostics if d.level == "error")
        raise PlanesValidationError(f"{first.code}: {first.message} ({first.path})")

    return ValidationResult(valid=not has_error, diagnostics=tuple(diagnostics))


def validate_split_schema_bundle(root: Path, *, strict: bool = True) -> ValidationResult:
    manifest, planes, routes, frames = load_split_bundle(root)
    return validate_split_schema_documents(manifest, planes, routes, frames, strict=strict)


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
