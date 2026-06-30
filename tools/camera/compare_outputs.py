from __future__ import annotations

import argparse
import colorsys
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image


def compare_processed_outputs(
    processed_dirs: list[Path],
    out_path: Path,
    *,
    labels: list[str] | None = None,
) -> dict[str, object]:
    if labels is not None and len(labels) != len(processed_dirs):
        raise ValueError("labels length must match processed directory count")
    cases = []
    for index, processed_dir in enumerate(processed_dirs):
        label = labels[index] if labels is not None else Path(processed_dir).name
        cases.append(_summarize_case(Path(processed_dir), label=label))
    report = {
        "schema": "luvatrix.camera_comparison.v1",
        "case_count": len(cases),
        "cases": cases,
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _summarize_case(processed_dir: Path, *, label: str) -> dict[str, object]:
    manifest_path = processed_dir / "processing_manifest.json"
    manifest = _read_json(manifest_path)
    output_path = _resolve_output_path(processed_dir, manifest)
    image_summary = _summarize_image(output_path)
    return {
        "label": label,
        "processed_dir": str(processed_dir),
        "manifest_path": str(manifest_path),
        "output_path": str(output_path),
        "decode_ok": image_summary["decode_ok"],
        "width": image_summary["width"],
        "height": image_summary["height"],
        "file_size_bytes": output_path.stat().st_size if output_path.exists() else 0,
        "status": _str_value(manifest.get("status")),
        "mode": _str_value(manifest.get("mode")),
        "reference_frame": _int_or_none(manifest.get("reference_frame")),
        "used_frames": _int_or_none(manifest.get("used_frames")),
        "rejected_frames": _int_or_none(manifest.get("rejected_frames")),
        "raw_quality_mode": _str_value(manifest.get("raw_quality_mode")),
        "raw_demosaic_mode": _str_value(manifest.get("raw_demosaic_mode")),
        "raw_merge_mode": _str_value(manifest.get("raw_merge_mode")),
        "style_profile": _str_value(manifest.get("style_profile")),
        "tone_map_exposure": _float_or_none(manifest.get("tone_map_exposure")),
        "tone_map_p50": _float_or_none(manifest.get("tone_map_p50")),
        "tone_map_p95": _float_or_none(manifest.get("tone_map_p95")),
        "tone_map_p99": _float_or_none(manifest.get("tone_map_p99")),
        "tone_map_highlight_rolloff": _float_or_none(manifest.get("tone_map_highlight_rolloff")),
        "raw_color_gains_usable": _bool_or_none(manifest.get("raw_color_gains_usable")),
        "raw_color_transform_usable": _bool_or_none(manifest.get("raw_color_transform_usable")),
        "raw_color_matrix_mode": _str_value(manifest.get("raw_color_matrix_mode")),
        "native_total_ms": _native_total_ms(manifest),
        "metrics": image_summary["metrics"],
    }


def _summarize_image(path: Path) -> dict[str, object]:
    if not path.exists():
        return {
            "decode_ok": False,
            "width": 0,
            "height": 0,
            "metrics": _empty_metrics(),
        }
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        raw = rgb.tobytes()
        pixels = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)]
    return {
        "decode_ok": True,
        "width": width,
        "height": height,
        "metrics": _compute_metrics(pixels, width=width, height=height),
    }


def _compute_metrics(pixels: list[tuple[int, int, int]], *, width: int, height: int) -> dict[str, float]:
    if not pixels or width <= 0 or height <= 0:
        return _empty_metrics()
    luma: list[float] = []
    saturation_total = 0.0
    for r, g, b in pixels:
        rf = r / 255.0
        gf = g / 255.0
        bf = b / 255.0
        luma.append((0.2126 * rf) + (0.7152 * gf) + (0.0722 * bf))
        saturation_total += colorsys.rgb_to_hsv(rf, gf, bf)[1]
    mean_luma = sum(luma) / len(luma)
    variance = sum((value - mean_luma) ** 2 for value in luma) / len(luma)
    sorted_luma = sorted(luma)
    clipped_shadow = sum(1 for value in luma if value <= 1.0 / 255.0) / len(luma)
    clipped_highlight = sum(1 for value in luma if value >= 254.0 / 255.0) / len(luma)
    return {
        "mean_luma": round(mean_luma, 6),
        "luma_stddev": round(math.sqrt(variance), 6),
        "p01_luma": round(_percentile(sorted_luma, 0.01), 6),
        "p50_luma": round(_percentile(sorted_luma, 0.50), 6),
        "p99_luma": round(_percentile(sorted_luma, 0.99), 6),
        "clipped_shadow_ratio": round(clipped_shadow, 6),
        "clipped_highlight_ratio": round(clipped_highlight, 6),
        "mean_saturation": round(saturation_total / len(pixels), 6),
        "sharpness_luma": round(_gradient_sharpness(luma, width=width, height=height), 6),
    }


def _gradient_sharpness(luma: list[float], *, width: int, height: int) -> float:
    if width <= 1 or height <= 1:
        return 0.0
    total = 0.0
    count = 0
    for y in range(height - 1):
        row = y * width
        next_row = (y + 1) * width
        for x in range(width - 1):
            center = luma[row + x]
            total += abs(center - luma[row + x + 1])
            total += abs(center - luma[next_row + x])
            count += 2
    return total / count if count else 0.0


def _empty_metrics() -> dict[str, float]:
    return {
        "mean_luma": 0.0,
        "luma_stddev": 0.0,
        "p01_luma": 0.0,
        "p50_luma": 0.0,
        "p99_luma": 0.0,
        "clipped_shadow_ratio": 0.0,
        "clipped_highlight_ratio": 0.0,
        "mean_saturation": 0.0,
        "sharpness_luma": 0.0,
    }


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, round((len(sorted_values) - 1) * fraction)))
    return sorted_values[index]


def _resolve_output_path(processed_dir: Path, manifest: dict[str, object]) -> Path:
    value = manifest.get("output_path")
    if isinstance(value, str) and value:
        path = Path(value)
        if path.is_absolute() and path.exists():
            return path
        if path.exists():
            return path
        local = processed_dir / path.name
        if local.exists():
            return local
    candidates = sorted(processed_dir.glob("IMG_*.jpg"))
    if not candidates:
        return processed_dir / "missing_output.jpg"
    return next((path for path in candidates if not path.name.endswith("_preview.jpg")), candidates[0])


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _native_total_ms(manifest: dict[str, object]) -> float | None:
    timing = manifest.get("native_timing_ms")
    if not isinstance(timing, dict):
        return None
    value = timing.get("total")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return round(float(value), 3)
    return None


def _str_value(value: object) -> str:
    return value if isinstance(value, str) else ""


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return round(float(value), 6)
    return None


def _bool_or_none(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare Luvatrix processed camera outputs.")
    parser.add_argument("processed_dirs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--label", action="append", dest="labels")
    args = parser.parse_args(argv)
    report = compare_processed_outputs(args.processed_dirs, args.out, labels=args.labels)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
