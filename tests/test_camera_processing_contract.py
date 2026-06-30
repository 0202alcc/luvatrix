from __future__ import annotations

import pytest

from luvatrix_core.platform.android.camera_processing_contract import (
    ProcessingRequest,
    ProcessingResult,
    ProcessingTelemetry,
)


def test_processing_request_json_roundtrip() -> None:
    request = ProcessingRequest(
        burst_id="burst_1",
        burst_manifest_path="/tmp/burst_1/burst_manifest.json",
        mode="sharpest",
        style="neutral",
        quality="standard",
    )

    payload = request.to_json()
    restored = ProcessingRequest.from_json(payload)

    assert restored == request


def test_processing_result_json_roundtrip() -> None:
    result = ProcessingResult(
        burst_id="burst_1",
        status="ok",
        output_path="/tmp/out/IMG_0001.jpg",
        preview_path="/tmp/out/IMG_0001_preview.jpg",
        telemetry=ProcessingTelemetry(reference_frame=3, used_frames=8, rejected_frames=2),
    )

    payload = result.to_json()
    restored = ProcessingResult.from_json(payload)

    assert restored == result


def test_processing_request_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unsupported processing mode: fancy"):
        ProcessingRequest.from_json(
            {
                "burst_id": "burst_1",
                "burst_manifest_path": "/tmp/burst_1/burst_manifest.json",
                "mode": "fancy",
                "style": "neutral",
                "quality": "standard",
            }
        )


def test_processing_request_requires_fields() -> None:
    with pytest.raises(ValueError, match="missing required processing request field: burst_manifest_path"):
        ProcessingRequest.from_json(
            {
                "burst_id": "burst_1",
                "mode": "sharpest",
                "style": "neutral",
                "quality": "standard",
            }
        )
