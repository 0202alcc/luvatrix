from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from luvatrix_core.platform.android.camera_processing_contract import ProcessingResult, ProcessingTelemetry


def load_manifest(burst_dir: Path) -> dict[str, object]:
    path = burst_dir / "burst_manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_frame_metadata(burst_dir: Path, frame_record: dict[str, object]) -> dict[str, object]:
    metadata_path = _resolve_artifact_path(burst_dir, frame_record.get("metadata_path"))
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def process_burst(burst_dir: Path, out_dir: Path, *, mode: str = "sharpest") -> dict[str, object]:
    if mode != "sharpest":
        raise ValueError(f"unsupported processing mode: {mode}")
    burst_dir = Path(burst_dir)
    out_dir = Path(out_dir)
    manifest = load_manifest(burst_dir)
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("burst manifest has no frames")

    scores: list[dict[str, object]] = []
    best_index = -1
    best_score = -1.0
    for raw_record in frames:
        if not isinstance(raw_record, dict):
            continue
        index = _int_value(raw_record.get("index"), default=len(scores))
        metadata = load_frame_metadata(burst_dir, raw_record)
        score = _score_yuv_luma_sharpness(burst_dir, raw_record, metadata)
        scores.append({"index": index, "sharpness": score})
        if score > best_score:
            best_score = score
            best_index = index

    if best_index < 0:
        raise ValueError("burst manifest has no processable YUV frames")

    out_dir.mkdir(parents=True, exist_ok=True)
    telemetry = ProcessingTelemetry(
        reference_frame=best_index,
        used_frames=len(scores),
        rejected_frames=max(0, len(frames) - len(scores)),
    )
    contract_result = ProcessingResult(
        burst_id=str(manifest.get("burst_id", "")),
        status="ok",
        output_path="",
        preview_path="",
        telemetry=telemetry,
    )
    result = contract_result.to_json()
    result.update(
        {
            "mode": mode,
            "reference_frame": best_index,
            "scores": scores,
        }
    )
    (out_dir / "processing_manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _score_yuv_luma_sharpness(
    burst_dir: Path,
    frame_record: dict[str, object],
    metadata: dict[str, object],
) -> float:
    if metadata.get("format") != "YUV_420_888":
        raise ValueError(f"unsupported frame format: {metadata.get('format')}")
    width = _int_value(metadata.get("width"))
    height = _int_value(metadata.get("height"))
    planes = metadata.get("planes")
    if width <= 1 or height <= 1 or not isinstance(planes, list) or not planes:
        return 0.0
    y_plane = planes[0] if isinstance(planes[0], dict) else {}
    row_stride = _int_value(y_plane.get("row_stride"), default=width)
    pixel_stride = _int_value(y_plane.get("pixel_stride"), default=1)
    byte_count = _int_value(y_plane.get("byte_count"), default=row_stride * height)
    frame_path = _resolve_artifact_path(burst_dir, frame_record.get("frame_path"))
    y_bytes = frame_path.read_bytes()[:byte_count]
    if not y_bytes:
        return 0.0

    step_x = max(1, width // 64)
    step_y = max(1, height // 64)
    total = 0
    count = 0
    for row in range(0, height, step_y):
        base = row * row_stride
        next_base = min(height - 1, row + step_y) * row_stride
        for col in range(0, width - step_x, step_x):
            idx = base + col * pixel_stride
            right_idx = base + (col + step_x) * pixel_stride
            down_idx = next_base + col * pixel_stride
            if idx >= len(y_bytes):
                continue
            center = y_bytes[idx]
            if right_idx < len(y_bytes):
                total += abs(center - y_bytes[right_idx])
                count += 1
            if down_idx < len(y_bytes):
                total += abs(center - y_bytes[down_idx])
                count += 1
    return float(total) / float(count) if count else 0.0


def _resolve_artifact_path(burst_dir: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("frame record is missing an artifact path")
    path = Path(value)
    if path.is_absolute():
        if path.exists():
            return path
        local = burst_dir / path.name
        if local.exists():
            return local
        return path
    return burst_dir / path


def _int_value(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process a Luvatrix computational camera burst.")
    parser.add_argument("burst_dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", default="sharpest")
    args = parser.parse_args(argv)
    result = process_burst(args.burst_dir, args.out, mode=args.mode)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
