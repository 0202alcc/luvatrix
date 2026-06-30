from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from tools.camera.compare_outputs import compare_processed_outputs


def _write_processed_case(root: Path, name: str, *, color: tuple[int, int, int], mode: str) -> Path:
    case_dir = root / name
    case_dir.mkdir(parents=True)
    image_path = case_dir / f"IMG_{name}.jpg"
    Image.new("RGB", (8, 6), color).save(image_path, format="JPEG", quality=95)
    (case_dir / "processing_manifest.json").write_text(
        json.dumps(
            {
                "burst_id": name,
                "status": "ok",
                "mode": mode,
                "output_path": str(image_path),
                "reference_frame": 1,
                "used_frames": 3,
                "rejected_frames": 0,
                "raw_quality_mode": "fast_1600",
                "raw_demosaic_mode": "bilinear_fast",
                "raw_merge_mode": mode,
                "style_profile": "Neutral",
                "tone_map_exposure": 1.25,
                "tone_map_p50": 0.32,
                "tone_map_p95": 0.68,
                "tone_map_p99": 0.91,
                "tone_map_highlight_rolloff": 0.42,
                "raw_color_gains_usable": True,
                "raw_color_transform_usable": True,
                "raw_color_matrix_mode": "normalized_camera_transform",
                "native_timing_ms": {"total": 12.5},
            }
        ),
        encoding="utf-8",
    )
    return case_dir


def test_compare_processed_outputs_writes_metrics_report(tmp_path: Path) -> None:
    first = _write_processed_case(tmp_path, "raw_single", color=(80, 90, 100), mode="raw_single_frame")
    second = _write_processed_case(tmp_path, "raw_aligned", color=(120, 110, 100), mode="raw_average_global_aligned")

    report = compare_processed_outputs([first, second], tmp_path / "camera_comparison.json")

    assert report["case_count"] == 2
    assert report["cases"][0]["label"] == "raw_single"
    assert report["cases"][0]["decode_ok"] is True
    assert report["cases"][0]["width"] == 8
    assert report["cases"][0]["height"] == 6
    assert report["cases"][0]["mode"] == "raw_single_frame"
    assert report["cases"][0]["tone_map_exposure"] == 1.25
    assert report["cases"][0]["tone_map_p50"] == 0.32
    assert report["cases"][0]["tone_map_p95"] == 0.68
    assert report["cases"][0]["tone_map_p99"] == 0.91
    assert report["cases"][0]["tone_map_highlight_rolloff"] == 0.42
    assert report["cases"][0]["raw_color_gains_usable"] is True
    assert report["cases"][0]["raw_color_transform_usable"] is True
    assert report["cases"][0]["raw_color_matrix_mode"] == "normalized_camera_transform"
    assert report["cases"][1]["raw_merge_mode"] == "raw_average_global_aligned"
    assert "sharpness_luma" in report["cases"][0]["metrics"]
    assert "mean_saturation" in report["cases"][0]["metrics"]

    written = json.loads((tmp_path / "camera_comparison.json").read_text(encoding="utf-8"))
    assert written == report


def test_compare_processed_outputs_uses_explicit_labels(tmp_path: Path) -> None:
    first = _write_processed_case(tmp_path, "burst_a", color=(20, 30, 40), mode="raw_single_frame")

    report = compare_processed_outputs([first], tmp_path / "comparison.json", labels=["phone-fast"])

    assert report["cases"][0]["label"] == "phone-fast"
