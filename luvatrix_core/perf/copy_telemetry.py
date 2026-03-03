from __future__ import annotations

from dataclasses import dataclass
import threading


@dataclass
class CopyTelemetry:
    copy_count: int = 0
    copy_bytes: int = 0
    upload_bytes: int = 0
    ui_pack_ns: int = 0
    matrix_stage_clone_ns: int = 0
    matrix_snapshot_clone_ns: int = 0
    upload_pack_ns: int = 0
    upload_map_ns: int = 0
    upload_memcpy_ns: int = 0
    queue_submit_ns: int = 0
    queue_present_ns: int = 0
    swapchain_recreate_count: int = 0
    staging_map_count: int = 0
    staging_realloc_count: int = 0
    upload_image_realloc_count: int = 0

    def add(self, **kwargs: int) -> None:
        for key, value in kwargs.items():
            if not hasattr(self, key):
                continue
            current = int(getattr(self, key, 0))
            setattr(self, key, current + max(0, int(value)))

    def as_dict(self) -> dict[str, int]:
        return {
            "copy_count": int(self.copy_count),
            "copy_bytes": int(self.copy_bytes),
            "upload_bytes": int(self.upload_bytes),
            "ui_pack_ns": int(self.ui_pack_ns),
            "matrix_stage_clone_ns": int(self.matrix_stage_clone_ns),
            "matrix_snapshot_clone_ns": int(self.matrix_snapshot_clone_ns),
            "upload_pack_ns": int(self.upload_pack_ns),
            "upload_map_ns": int(self.upload_map_ns),
            "upload_memcpy_ns": int(self.upload_memcpy_ns),
            "queue_submit_ns": int(self.queue_submit_ns),
            "queue_present_ns": int(self.queue_present_ns),
            "swapchain_recreate_count": int(self.swapchain_recreate_count),
            "staging_map_count": int(self.staging_map_count),
            "staging_realloc_count": int(self.staging_realloc_count),
            "upload_image_realloc_count": int(self.upload_image_realloc_count),
        }


_LOCAL = threading.local()


def begin_copy_telemetry_frame() -> None:
    _LOCAL.copy_telemetry = CopyTelemetry()


def add_copy_telemetry(**kwargs: int) -> None:
    telemetry = getattr(_LOCAL, "copy_telemetry", None)
    if telemetry is None:
        return
    telemetry.add(**kwargs)


def snapshot_copy_telemetry() -> dict[str, int]:
    telemetry = getattr(_LOCAL, "copy_telemetry", None)
    if telemetry is None:
        return CopyTelemetry().as_dict()
    return telemetry.as_dict()
