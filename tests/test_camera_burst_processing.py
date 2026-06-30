from __future__ import annotations

import json
from pathlib import Path

from tools.camera.process_burst import process_burst


def _write_frame(burst_dir: Path, index: int, y: bytes, *, width: int, height: int) -> dict[str, object]:
    frame = burst_dir / f"frame_{index:03d}.yuv"
    metadata = burst_dir / f"metadata_{index:03d}.json"
    frame.write_bytes(y)
    metadata.write_text(
        json.dumps(
            {
                "format": "YUV_420_888",
                "width": width,
                "height": height,
                "timestamp_ns": index + 1,
                "planes": [
                    {"name": "Y", "row_stride": width, "pixel_stride": 1, "byte_count": len(y)},
                    {"name": "U", "row_stride": width // 2, "pixel_stride": 2, "byte_count": 0},
                    {"name": "V", "row_stride": width // 2, "pixel_stride": 2, "byte_count": 0},
                ],
            }
        ),
        encoding="utf-8",
    )
    return {
        "index": index,
        "frame_path": str(frame),
        "metadata_path": str(metadata),
        "timestamp_ns": index + 1,
        "format": "YUV_420_888",
        "width": width,
        "height": height,
    }


def test_process_burst_selects_highest_contrast_yuv_frame(tmp_path: Path) -> None:
    burst_dir = tmp_path / "burst_1"
    burst_dir.mkdir()
    width = 4
    height = 4
    flat = bytes([80] * (width * height))
    high_contrast = bytes(
        [
            0,
            255,
            0,
            255,
            255,
            0,
            255,
            0,
            0,
            255,
            0,
            255,
            255,
            0,
            255,
            0,
        ]
    )
    frames = [
        _write_frame(burst_dir, 0, flat, width=width, height=height),
        _write_frame(burst_dir, 1, high_contrast, width=width, height=height),
    ]
    (burst_dir / "burst_manifest.json").write_text(
        json.dumps(
            {
                "burst_id": "burst_1",
                "format": "YUV_420_888",
                "frame_count": 2,
                "requested_frame_count": 2,
                "frames": frames,
            }
        ),
        encoding="utf-8",
    )

    result = process_burst(burst_dir, tmp_path / "out", mode="sharpest")

    assert result["reference_frame"] == 1
    output_manifest = tmp_path / "out" / "processing_manifest.json"
    assert output_manifest.exists()
    payload = json.loads(output_manifest.read_text(encoding="utf-8"))
    assert payload["burst_id"] == "burst_1"
    assert payload["mode"] == "sharpest"
    assert payload["reference_frame"] == 1
    assert payload["scores"][1]["sharpness"] > payload["scores"][0]["sharpness"]
