from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SUPPORTED_PROCESSING_MODES = frozenset({"sharpest", "average_aligned", "raw_linear"})
SUPPORTED_QUALITY_LEVELS = frozenset({"draft", "standard", "best"})


@dataclass(frozen=True)
class ProcessingRequest:
    burst_id: str
    burst_manifest_path: str
    mode: str
    style: str
    quality: str

    def to_json(self) -> dict[str, object]:
        return {
            "burst_id": self.burst_id,
            "burst_manifest_path": self.burst_manifest_path,
            "mode": self.mode,
            "style": self.style,
            "quality": self.quality,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "ProcessingRequest":
        burst_id = _required_str(payload, "burst_id")
        burst_manifest_path = _required_str(payload, "burst_manifest_path")
        mode = _required_str(payload, "mode")
        style = _required_str(payload, "style")
        quality = _required_str(payload, "quality")
        if mode not in SUPPORTED_PROCESSING_MODES:
            raise ValueError(f"unsupported processing mode: {mode}")
        if quality not in SUPPORTED_QUALITY_LEVELS:
            raise ValueError(f"unsupported processing quality: {quality}")
        return cls(
            burst_id=burst_id,
            burst_manifest_path=burst_manifest_path,
            mode=mode,
            style=style,
            quality=quality,
        )


@dataclass(frozen=True)
class ProcessingTelemetry:
    reference_frame: int
    used_frames: int
    rejected_frames: int

    def to_json(self) -> dict[str, object]:
        return {
            "reference_frame": self.reference_frame,
            "used_frames": self.used_frames,
            "rejected_frames": self.rejected_frames,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "ProcessingTelemetry":
        return cls(
            reference_frame=_required_int(payload, "reference_frame"),
            used_frames=_required_int(payload, "used_frames"),
            rejected_frames=_required_int(payload, "rejected_frames"),
        )


@dataclass(frozen=True)
class ProcessingResult:
    burst_id: str
    status: str
    output_path: str
    preview_path: str
    telemetry: ProcessingTelemetry

    def to_json(self) -> dict[str, object]:
        return {
            "burst_id": self.burst_id,
            "status": self.status,
            "output_path": self.output_path,
            "preview_path": self.preview_path,
            "telemetry": self.telemetry.to_json(),
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "ProcessingResult":
        telemetry = payload.get("telemetry")
        if not isinstance(telemetry, dict):
            raise ValueError("missing required processing result field: telemetry")
        return cls(
            burst_id=_required_str(payload, "burst_id"),
            status=_required_str(payload, "status"),
            output_path=_required_str(payload, "output_path"),
            preview_path=_required_str(payload, "preview_path"),
            telemetry=ProcessingTelemetry.from_json(telemetry),
        )


def _required_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        prefix = "processing request" if key in {"burst_manifest_path", "mode", "style", "quality"} else "processing result"
        raise ValueError(f"missing required {prefix} field: {key}")
    return value


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"missing required processing telemetry field: {key}")
    return value
