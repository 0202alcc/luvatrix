from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch

from luvatrix_core.perf.copy_telemetry import begin_copy_telemetry_frame, snapshot_copy_telemetry
from luvatrix_core.platform.macos.vulkan_backend import MoltenVKMacOSBackend


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if q <= 0:
        return float(min(values))
    if q >= 100:
        return float(max(values))
    ordered = sorted(float(v) for v in values)
    idx = (len(ordered) - 1) * (q / 100.0)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return float(ordered[lo])
    blend = idx - float(lo)
    return float(ordered[lo] * (1.0 - blend) + ordered[hi] * blend)


@dataclass
class _ModeConfig:
    name: str
    persistent_staging: bool
    transfer_growth: bool
    upload_reuse: bool
    fast_upload_path: bool
    swapchain_recreate_every: int


class _FakeFFI:
    @staticmethod
    def from_buffer(buf):
        return buf

    @staticmethod
    def memmove(dst, src, n):
        dst[:n] = src[:n]


class _FakeVk:
    VK_FORMAT_B8G8R8A8_UNORM = 44
    VK_FORMAT_B8G8R8A8_SRGB = 50

    def __init__(self) -> None:
        self.ffi = _FakeFFI()

    @staticmethod
    def vkMapMemory(device, memory, offset, size, flags):
        return bytearray(size)

    @staticmethod
    def vkUnmapMemory(device, memory):
        return None


class _BenchBackend(MoltenVKMacOSBackend):
    def _ensure_staging_buffer(self, required_size: int) -> None:
        if self._staging_size >= required_size and self._staging_memory is not None:
            return
        self._staging_size = self._next_transfer_allocation_size(required_size)
        self._staging_memory = "staging"
        self._staging_buffer = "staging-buffer"
        self._staging_mapped_ptr = None
        from luvatrix_core.perf.copy_telemetry import add_copy_telemetry

        add_copy_telemetry(staging_realloc_count=1)

    def _ensure_upload_image(self, width: int, height: int) -> None:
        cur_w, cur_h = self._upload_image_extent
        can_reuse = self._upload_image is not None and self._upload_image_reuse_enabled and cur_w >= width and cur_h >= height
        if can_reuse:
            return
        if self._upload_image is not None and cur_w == width and cur_h == height:
            return
        alloc_w = self._next_upload_extent(width) if self._transfer_growth_enabled else width
        alloc_h = self._next_upload_extent(height) if self._transfer_growth_enabled else height
        self._upload_image = "upload-image"
        self._upload_image_memory = "upload-memory"
        self._upload_image_extent = (alloc_w, alloc_h)
        self._upload_image_layout = 0
        self._upload_image_format = int(self._swapchain_image_format or 44)
        from luvatrix_core.perf.copy_telemetry import add_copy_telemetry

        add_copy_telemetry(upload_image_realloc_count=1)

    def _recreate_swapchain(self, width: int, height: int) -> None:
        self._swapchain_extent = (width, height)


class _NoopWindowSystem:
    pass


def _synthetic_transfer_present_cost_ns(telemetry: dict[str, int]) -> int:
    return (
        int(telemetry.get("upload_pack_ns", 0))
        + int(telemetry.get("upload_map_ns", 0))
        + int(telemetry.get("upload_memcpy_ns", 0))
        + int(telemetry.get("queue_submit_ns", 0))
        + int(telemetry.get("queue_present_ns", 0))
        + (int(telemetry.get("staging_realloc_count", 0)) * 250_000)
        + (int(telemetry.get("upload_image_realloc_count", 0)) * 250_000)
        + (int(telemetry.get("swapchain_recreate_count", 0)) * 1_500_000)
    )


def _run_mode(config: _ModeConfig, *, frames: int, width: int, height: int) -> dict[str, Any]:
    backend = _BenchBackend(window_system=_NoopWindowSystem())
    backend._vk = _FakeVk()
    backend._vulkan_available = True
    backend._logical_device = "device"
    backend._physical_device = "gpu"
    backend._swapchain_image_format = 44
    backend._swapchain_extent = (width, height)
    backend._persistent_staging_enabled = config.persistent_staging
    backend._transfer_growth_enabled = config.transfer_growth
    backend._upload_image_reuse_enabled = config.upload_reuse
    backend._fast_upload_path_enabled = config.fast_upload_path

    costs_ns: list[int] = []
    upload_bytes_trace: list[int] = []
    recreate_trace: list[int] = []
    for i in range(frames):
        begin_copy_telemetry_frame()
        w = width + (64 if (i % 3 == 0) else 0)
        h = height + (32 if (i % 4 == 0) else 0)
        rgba = torch.zeros((h, w, 4), dtype=torch.uint8)
        backend._upload_rgba_to_staging(rgba)
        from luvatrix_core.perf.copy_telemetry import add_copy_telemetry

        add_copy_telemetry(queue_submit_ns=80_000, queue_present_ns=120_000)
        if config.swapchain_recreate_every > 0 and (i % config.swapchain_recreate_every == 0):
            backend._record_swapchain_recreate()
        telemetry = snapshot_copy_telemetry()
        costs_ns.append(_synthetic_transfer_present_cost_ns(telemetry))
        upload_bytes_trace.append(int(telemetry.get("upload_bytes", 0)))
        recreate_trace.append(int(telemetry.get("swapchain_recreate_count", 0)))

    return {
        "mode": config.name,
        "frames": int(frames),
        "avg_transfer_present_ms": float(sum(costs_ns) / max(1, len(costs_ns))) / 1_000_000.0,
        "p95_transfer_present_ms": float(_percentile([float(v) for v in costs_ns], 95.0)) / 1_000_000.0,
        "p95_upload_bytes": int(round(_percentile([float(v) for v in upload_bytes_trace], 95.0))),
        "swapchain_recreate_events": int(sum(recreate_trace)),
    }


def run_compare(*, frames: int, width: int, height: int) -> dict[str, Any]:
    baseline = _run_mode(
        _ModeConfig(
            name="baseline_legacy_flags",
            persistent_staging=False,
            transfer_growth=False,
            upload_reuse=False,
            fast_upload_path=False,
            swapchain_recreate_every=1,
        ),
        frames=frames,
        width=width,
        height=height,
    )
    candidate = _run_mode(
        _ModeConfig(
            name="candidate_r023_flags",
            persistent_staging=True,
            transfer_growth=True,
            upload_reuse=True,
            fast_upload_path=True,
            swapchain_recreate_every=4,
        ),
        frames=frames,
        width=width,
        height=height,
    )
    return {
        "frames": int(frames),
        "width": int(width),
        "height": int(height),
        "baseline": baseline,
        "candidate": candidate,
        "delta_ms": {
            "avg_transfer_present_ms": float(candidate["avg_transfer_present_ms"] - baseline["avg_transfer_present_ms"]),
            "p95_transfer_present_ms": float(candidate["p95_transfer_present_ms"] - baseline["p95_transfer_present_ms"]),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="R-023 synthetic Vulkan transfer/present comparison")
    parser.add_argument("--frames", type=int, default=90)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    summary = run_compare(frames=max(1, int(args.frames)), width=max(1, int(args.width)), height=max(1, int(args.height)))
    payload = json.dumps(summary, indent=2, sort_keys=True)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
