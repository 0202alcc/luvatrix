from __future__ import annotations

import json
import math
import os
import time
from collections import deque
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable

from luvatrix_core.core.coordinates import CoordinateFrameRegistry
from luvatrix_ui.component_schema import CoordinatePoint
from luvatrix_ui.controls.svg_component import SVGComponent
from luvatrix_ui.planes_protocol import compile_planes_to_ui_ir, resolve_web_metadata
from luvatrix_ui.ui_ir import BoundingBoxSpec
from luvatrix_ui.text.component import TextComponent
from luvatrix_ui.text.renderer import FontSpec, TextAppearance, TextMeasureRequest, TextSizeSpec

from luvatrix_core.core.ui_frame_renderer import MatrixUIFrameRenderer


EventHandler = Callable[[dict[str, Any], dict[str, Any]], object | None]


@dataclass(frozen=True)
class ScrollIntent:
    delta_x: float
    delta_y: float
    source: str
    phase: str = "update"
    momentum_phase: str | None = None
    event_count: int = 1


@dataclass(frozen=True)
class PlanesV2RolloutFlags:
    schema_enabled: bool
    compiler_enabled: bool
    runtime_enabled: bool
    rollback_to_compat_adapter_default: bool


class PlaneApp:
    """Framework-managed Planes runtime lifecycle for App Protocol apps."""

    def __init__(
        self,
        plane_path: str | Path,
        *,
        handlers: dict[str, EventHandler] | None = None,
        strict: bool = True,
    ) -> None:
        self._plane_path = Path(plane_path).resolve()
        self._plane_dir = self._plane_path.parent
        self._handlers: dict[str, EventHandler] = dict(handlers or {})
        self._strict = strict
        self._renderer = MatrixUIFrameRenderer()
        self.state: dict[str, Any] = {}
        self._svg_markup_cache: dict[Path, str] = {}
        self._incremental_present_enabled_default = _env_flag(
            "LUVATRIX_INCREMENTAL_PRESENT_ENABLED",
            default=True,
        )
        self._scroll_bitmap_cache_enabled_default = _env_flag(
            "LUVATRIX_SCROLL_BITMAP_CACHE_ENABLED",
            default=False,
        )
        self._scroll_scheduler_enabled_default = _env_flag(
            "LUVATRIX_SCROLL_SCHEDULER_ENABLED",
            default=True,
        )
        self._intent_queue_enabled_default = _env_flag(
            "LUVATRIX_INTENT_QUEUE_ENABLED",
            default=True,
        )
        self._planes_v2_rollout_flags = resolve_planes_v2_rollout_flags()

        self._planes = json.loads(self._plane_path.read_text(encoding="utf-8"))
        self.metadata = resolve_web_metadata(self._planes["app"])
        self._ui_page = None
        self._bg_color = (0, 0, 0, 255)
        self.state.setdefault("active_theme", "default")
        self.state.setdefault("hover_component_id", None)
        self.state.setdefault("last_pointer_xy", None)
        self.state.setdefault("viewport_scroll", {})
        self.state.setdefault("plane_scroll", {"x": 0.0, "y": 0.0})
        self.state.setdefault("prefetch_margin_px", {"x": 96.0, "y": 96.0})
        self.state.setdefault("perf", {})
        self.state.setdefault("incremental_present_enabled", self._incremental_present_enabled_default)
        self.state.setdefault("scroll_bitmap_cache_enabled", self._scroll_bitmap_cache_enabled_default)
        self.state.setdefault("scroll_scheduler_enabled", self._scroll_scheduler_enabled_default)
        self.state.setdefault("intent_queue_enabled", self._intent_queue_enabled_default)
        self.state.setdefault("planes_v2_schema_enabled", self._planes_v2_rollout_flags.schema_enabled)
        self.state.setdefault("planes_v2_compiler_enabled", self._planes_v2_rollout_flags.compiler_enabled)
        self.state.setdefault("planes_v2_runtime_enabled", self._planes_v2_rollout_flags.runtime_enabled)
        self.state.setdefault(
            "planes_v2_rollback_to_compat_adapter_default",
            self._planes_v2_rollout_flags.rollback_to_compat_adapter_default,
        )
        self.state.setdefault("force_full_invalidation", False)
        self.state.setdefault("force_full_invalidation_reason", None)
        self.state.setdefault(
            "present_counters",
            {
                "presented_frames": 0,
                "incremental_frames": 0,
                "full_frames": 0,
                "idle_skipped_frames": 0,
            },
        )
        self._component_index: dict[str, Any] = {}
        self._plane_index: dict[str, Any] = {}
        self._coord_registry: CoordinateFrameRegistry | None = None
        self._frame_perf: dict[str, float] = {}
        self._frame_counts: dict[str, int] = {}
        self._retained_mount_cache: dict[str, tuple[tuple[Any, ...], Any]] = {}
        self._layout_position_cache: dict[str, tuple[tuple[Any, ...], tuple[float, float]]] = {}
        self._interaction_bounds_cache: dict[str, tuple[tuple[Any, ...], Any]] = {}
        self._layout_cache_signature: tuple[tuple[float, float], tuple[str, ...]] | None = None
        self._auto_component_size: dict[str, tuple[float, float]] = {}
        self._scrollbar_markups: dict[str, str] = {
            "page_track_h": self._build_scrollbar_markup(100, 10, "#1f344d"),
            "page_thumb_h": self._build_scrollbar_markup(100, 10, "#9bc9f8"),
            "page_track_v": self._build_scrollbar_markup(10, 100, "#1f344d"),
            "page_thumb_v": self._build_scrollbar_markup(10, 100, "#9bc9f8"),
            "viewport_track_h": self._build_scrollbar_markup(100, 10, "#1f344d"),
            "viewport_thumb_h": self._build_scrollbar_markup(100, 10, "#89b7e6"),
            "viewport_track_v": self._build_scrollbar_markup(10, 100, "#1f344d"),
            "viewport_thumb_v": self._build_scrollbar_markup(10, 100, "#89b7e6"),
        }
        self._hit_grid_cell_px = 96
        self._hit_spatial_index: dict[tuple[int, int], list[Any]] = {}
        self._hit_index_all: list[Any] = []
        self._hit_index_signature: tuple[tuple[float, float], tuple[tuple[str, float, float], ...], tuple[str, ...]] | None = None
        self._last_dirty_signature: tuple[str, str | None, tuple[tuple[str, float, float], ...]] | None = None
        self._last_plane_scroll: tuple[float, float] | None = None
        self._scroll_shift_residual: tuple[float, float] = (0.0, 0.0)
        self._frame_scroll_shift: tuple[int, int] | None = None
        self._event_pointer_dirty_rects: list[tuple[int, int, int, int]] = []
        self._intent_queue: deque[Any] = deque()
        self._event_batch_base = _env_int("LUVATRIX_EVENT_BATCH_BASE", default=128, min_value=1, max_value=4096)
        self._event_batch_max = _env_int("LUVATRIX_EVENT_BATCH_MAX", default=512, min_value=1, max_value=4096)
        self._intent_ingest_max = _env_int("LUVATRIX_INTENT_INGEST_MAX", default=1024, min_value=1, max_value=8192)
        self._intent_queue_max = _env_int("LUVATRIX_INTENT_QUEUE_MAX", default=4096, min_value=1, max_value=32768)
        if self._event_batch_max < self._event_batch_base:
            self._event_batch_max = self._event_batch_base

    def register_handler(self, target: str, handler: EventHandler) -> None:
        self._handlers[target] = handler

    def init(self, ctx) -> None:
        self._ensure_compiled(ctx)

    def loop(self, ctx, dt: float) -> None:
        frame_start_ns = time.perf_counter_ns()
        self._begin_perf_frame()
        self._frame_scroll_shift = None
        self._ensure_compiled(ctx)
        assert self._ui_page is not None
        pre_plane_scroll = self._plane_scroll_position()
        pre_signature = self._current_dirty_signature()
        input_start_ns = time.perf_counter_ns()
        self._dispatch_events(ctx, dt)
        self._add_perf_ns("input_ns", time.perf_counter_ns() - input_start_ns)
        self._bg_color = self._resolve_background()
        post_plane_scroll = self._plane_scroll_position()
        post_signature = self._current_dirty_signature()
        dirty_rects = self._compute_dirty_rects(
            pre_plane_scroll=pre_plane_scroll,
            post_plane_scroll=post_plane_scroll,
            pre_signature=pre_signature,
            post_signature=post_signature,
            events_processed=int(self._frame_counts.get("events_processed", 0)),
        )
        scroll_shift = self._compute_scroll_shift(
            pre_plane_scroll=pre_plane_scroll,
            post_plane_scroll=post_plane_scroll,
            pre_signature=pre_signature,
            post_signature=post_signature,
        )
        self._last_plane_scroll = post_plane_scroll
        self._last_dirty_signature = post_signature
        invalidation_escape_hatch_used, invalidation_escape_hatch_reason = self._consume_invalidation_escape_hatch()
        if invalidation_escape_hatch_used and self._ui_page is not None:
            self._reset_scroll_shift_residual()
            dirty_rects = [(0, 0, int(self._ui_page.matrix.width), int(self._ui_page.matrix.height))]
            scroll_shift = None
        elif dirty_rects and not self._incremental_present_enabled():
            self._reset_scroll_shift_residual()
            dirty_rects = [(0, 0, int(self._ui_page.matrix.width), int(self._ui_page.matrix.height))]
            scroll_shift = None
        dirty_count = int(len(dirty_rects))
        dirty_area = int(sum((w * h) for (_, _, w, h) in dirty_rects))
        full_area = (
            int(self._ui_page.matrix.width) * int(self._ui_page.matrix.height)
            if self._ui_page is not None
            else 0
        )
        dirty_area_ratio = (float(dirty_area) / float(full_area)) if full_area > 0 else 0.0
        event_budget = int(self._frame_counts.get("event_budget", 0))
        queue_pending_before = int(self._frame_counts.get("event_queue_pending_before", 0))
        queue_pending_after = int(self._frame_counts.get("event_queue_pending_after", 0))
        event_order_digest = str(self._frame_counts.get("event_order_digest", "0"))
        hdi_latency_p95_ms = self._ns_to_ms(float(self._frame_counts.get("hdi_queue_latency_ns_p95", 0)))
        hdi_latency_max_ms = self._ns_to_ms(float(self._frame_counts.get("hdi_queue_latency_ns_max", 0)))
        hdi_events_dropped = int(self._frame_counts.get("hdi_events_dropped", 0))
        hdi_events_coalesced = int(self._frame_counts.get("hdi_events_coalesced", 0))
        compose_mode = "partial_dirty" if not self._is_full_frame_dirty(dirty_rects) else "full_frame"
        estimated_copy = self._estimate_copy_telemetry(
            compose_mode=compose_mode,
            dirty_rects=dirty_rects,
        )
        if dirty_count == 0:
            counters = self._update_present_counters("idle_skip")
            self._add_perf_ns("frame_total_ns", time.perf_counter_ns() - frame_start_ns)
            self.state["perf"] = {
                "components_considered": 0,
                "components_culled": 0,
                "components_mounted": 0,
                "prefetch_margin_x_px": float(self._prefetch_margins()[0]),
                "prefetch_margin_y_px": float(self._prefetch_margins()[1]),
                "svg_cache_size": int(len(self._svg_markup_cache)),
                "events_polled": int(self._frame_counts.get("events_polled", 0)),
                "events_processed": int(self._frame_counts.get("events_processed", 0)),
                "event_budget": event_budget,
                "event_queue_pending_before": queue_pending_before,
                "event_queue_pending_after": queue_pending_after,
                "event_order_digest": event_order_digest,
                "scroll_events": int(self._frame_counts.get("scroll_events", 0)),
                "scroll_events_coalesced": int(self._frame_counts.get("scroll_events_coalesced", 0)),
                "scroll_scheduler_enabled": bool(self._scroll_scheduler_enabled()),
                "scroll_scheduler_applied": int(self._frame_counts.get("scroll_scheduler_applied", 0)),
                "scroll_scheduler_coalesced_events": int(self._frame_counts.get("scroll_scheduler_coalesced_events", 0)),
                "intent_queue_enabled": bool(self._intent_queue_enabled()),
                "intent_queue_depth_before": int(self._frame_counts.get("intent_queue_depth_before", 0)),
                "intent_queue_depth_after_enqueue": int(self._frame_counts.get("intent_queue_depth_after_enqueue", 0)),
                "intent_queue_depth_after_drain": int(self._frame_counts.get("intent_queue_depth_after_drain", 0)),
                "intent_queue_enqueued": int(self._frame_counts.get("intent_queue_enqueued", 0)),
                "intent_queue_drained": int(self._frame_counts.get("intent_queue_drained", 0)),
                "intent_queue_overflow_dropped": int(self._frame_counts.get("intent_queue_overflow_dropped", 0)),
                "hdi_events_dropped": hdi_events_dropped,
                "hdi_events_coalesced": hdi_events_coalesced,
                "hdi_queue_latency_p95_ms": hdi_latency_p95_ms,
                "hdi_queue_latency_max_ms": hdi_latency_max_ms,
                "hit_test_calls": int(self._frame_counts.get("hit_test_calls", 0)),
                "hit_test_candidates_checked": int(self._frame_counts.get("hit_test_candidates_checked", 0)),
                "hit_test_spatial_buckets": int(self._frame_counts.get("hit_test_spatial_buckets", 0)),
                "layout_cache_hits": int(self._frame_counts.get("layout_cache_hits", 0)),
                "layout_cache_misses": int(self._frame_counts.get("layout_cache_misses", 0)),
                "renderer_batch_groups": int(self._frame_counts.get("renderer_batch_groups", 0)),
                "renderer_batch_state_switches": int(self._frame_counts.get("renderer_batch_state_switches", 0)),
                "retained_components_reused": int(self._frame_counts.get("retained_components_reused", 0)),
                "retained_components_new": int(self._frame_counts.get("retained_components_new", 0)),
                "camera_overlay_scrollbar_primitives": int(self._frame_counts.get("camera_overlay_scrollbar_primitives", 0)),
                "dirty_rect_count": 0,
                "dirty_rect_area_px": 0,
                "dirty_rect_area_ratio": 0.0,
                "compose_mode": "idle_skip",
                "incremental_present_pct": float(counters.get("incremental_present_pct", 0.0)),
                "full_present_pct": float(counters.get("full_present_pct", 0.0)),
                "presented_frames": int(counters.get("presented_frames", 0)),
                "incremental_frames": int(counters.get("incremental_frames", 0)),
                "full_frames": int(counters.get("full_frames", 0)),
                "idle_skipped_frames": int(counters.get("idle_skipped_frames", 0)),
                "incremental_present_enabled": bool(self._incremental_present_enabled()),
                "scroll_bitmap_cache_enabled": bool(self._scroll_bitmap_cache_enabled()),
                "bitmap_cache_hits": 0,
                "bitmap_cache_misses": 0,
                "bitmap_cache_entry_count": 0,
                "invalidation_escape_hatch_used": bool(invalidation_escape_hatch_used),
                "invalidation_escape_hatch_reason": invalidation_escape_hatch_reason,
                "copy_count": 0,
                "copy_bytes": 0,
                "upload_bytes": 0,
                "swapchain_recreate_count": 0,
                "timing_ms": {
                    "input": self._ns_to_ms(self._frame_perf.get("input_ns", 0.0)),
                    "hit_test": self._ns_to_ms(self._frame_perf.get("hit_test_ns", 0.0)),
                    "scroll_update": self._ns_to_ms(self._frame_perf.get("scroll_update_ns", 0.0)),
                    "cull": 0.0,
                    "mount": 0.0,
                    "raster": 0.0,
                    "present": 0.0,
                    "frame_total": self._ns_to_ms(self._frame_perf.get("frame_total_ns", 0.0)),
                },
                "copy_timing_ms": {
                    "ui_pack": 0.0,
                    "matrix_stage_clone": 0.0,
                    "matrix_snapshot_clone": 0.0,
                    "upload_pack": 0.0,
                    "upload_map": 0.0,
                    "upload_memcpy": 0.0,
                    "queue_submit": 0.0,
                    "queue_present": 0.0,
                },
            }
            self._merge_renderer_bitmap_cache_stats()
            return
        if compose_mode == "full_frame":
            self._reset_scroll_shift_residual()

        raster_start_ns = time.perf_counter_ns()
        set_bitmap_cache_enabled = getattr(self._renderer, "set_bitmap_cache_enabled", None)
        if callable(set_bitmap_cache_enabled):
            set_bitmap_cache_enabled(bool(self._scroll_bitmap_cache_enabled()))
        ctx.begin_ui_frame(
            self._renderer,
            content_width_px=float(self._ui_page.matrix.width),
            content_height_px=float(self._ui_page.matrix.height),
            clear_color=self._bg_color,
            dirty_rects=dirty_rects,
            scroll_shift=scroll_shift,
        )
        self._add_perf_ns("raster_ns", time.perf_counter_ns() - raster_start_ns)
        ordered = self._ui_page.ordered_components_for_draw()
        viewport_content_refs = self._viewport_content_refs()
        prefetch_x, prefetch_y = self._prefetch_margins()
        considered = 0
        culled = 0
        mounted = 0
        mount_plan: list[tuple[str, Any, float, float, str]] = []
        for component in ordered:
            if not component.visible:
                continue
            if not self._component_is_active(component):
                continue
            considered += 1
            if component.component_id in viewport_content_refs:
                # Viewport content is rendered through the viewport camera pass.
                continue
            resolved_x, resolved_y = self._resolved_position(component)
            props = component.style if isinstance(component.style, dict) else {}
            layout_w, layout_h = self._component_layout_size(component, props=props)
            cull_start_ns = time.perf_counter_ns()
            if not self._is_component_in_camera_region(
                x=resolved_x,
                y=resolved_y,
                width=float(layout_w),
                height=float(layout_h),
                margin_x=prefetch_x,
                margin_y=prefetch_y,
            ):
                self._add_perf_ns("cull_ns", time.perf_counter_ns() - cull_start_ns)
                culled += 1
                continue
            self._add_perf_ns("cull_ns", time.perf_counter_ns() - cull_start_ns)
            if component.component_type == "viewport":
                mount_start_ns = time.perf_counter_ns()
                self._mount_viewport_cutout_mask(ctx, component)
                self._add_perf_ns("mount_ns", time.perf_counter_ns() - mount_start_ns)
                mounted += 1
                continue
            frame = component.resolved_frame(self._ui_page.default_frame)
            if component.component_type in {"text", "svg"}:
                mount_plan.append((str(component.component_type), component, resolved_x, resolved_y, frame))
                continue
            # viewport and other component types are validated at compile-time.
        mounted += self._mount_batched_drawables(ctx, mount_plan)
        mount_scrollbar_start_ns = time.perf_counter_ns()
        self._mount_plane_scrollbars(ctx)
        self._add_perf_ns("mount_ns", time.perf_counter_ns() - mount_scrollbar_start_ns)
        present_start_ns = time.perf_counter_ns()
        counters = self._update_present_counters(compose_mode)
        self.state["perf"] = {
            "components_considered": int(considered),
            "components_culled": int(culled),
            "components_mounted": int(mounted),
            "prefetch_margin_x_px": float(prefetch_x),
            "prefetch_margin_y_px": float(prefetch_y),
            "svg_cache_size": int(len(self._svg_markup_cache)),
            "events_polled": int(self._frame_counts.get("events_polled", 0)),
            "events_processed": int(self._frame_counts.get("events_processed", 0)),
            "event_budget": event_budget,
            "event_queue_pending_before": queue_pending_before,
            "event_queue_pending_after": queue_pending_after,
            "event_order_digest": event_order_digest,
            "scroll_events": int(self._frame_counts.get("scroll_events", 0)),
            "scroll_events_coalesced": int(self._frame_counts.get("scroll_events_coalesced", 0)),
            "scroll_scheduler_enabled": bool(self._scroll_scheduler_enabled()),
            "scroll_scheduler_applied": int(self._frame_counts.get("scroll_scheduler_applied", 0)),
            "scroll_scheduler_coalesced_events": int(self._frame_counts.get("scroll_scheduler_coalesced_events", 0)),
            "intent_queue_enabled": bool(self._intent_queue_enabled()),
            "intent_queue_depth_before": int(self._frame_counts.get("intent_queue_depth_before", 0)),
            "intent_queue_depth_after_enqueue": int(self._frame_counts.get("intent_queue_depth_after_enqueue", 0)),
            "intent_queue_depth_after_drain": int(self._frame_counts.get("intent_queue_depth_after_drain", 0)),
            "intent_queue_enqueued": int(self._frame_counts.get("intent_queue_enqueued", 0)),
            "intent_queue_drained": int(self._frame_counts.get("intent_queue_drained", 0)),
            "intent_queue_overflow_dropped": int(self._frame_counts.get("intent_queue_overflow_dropped", 0)),
            "hdi_events_dropped": hdi_events_dropped,
            "hdi_events_coalesced": hdi_events_coalesced,
            "hdi_queue_latency_p95_ms": hdi_latency_p95_ms,
            "hdi_queue_latency_max_ms": hdi_latency_max_ms,
            "hit_test_calls": int(self._frame_counts.get("hit_test_calls", 0)),
            "hit_test_candidates_checked": int(self._frame_counts.get("hit_test_candidates_checked", 0)),
            "hit_test_spatial_buckets": int(self._frame_counts.get("hit_test_spatial_buckets", 0)),
            "layout_cache_hits": int(self._frame_counts.get("layout_cache_hits", 0)),
            "layout_cache_misses": int(self._frame_counts.get("layout_cache_misses", 0)),
            "renderer_batch_groups": int(self._frame_counts.get("renderer_batch_groups", 0)),
            "renderer_batch_state_switches": int(self._frame_counts.get("renderer_batch_state_switches", 0)),
            "retained_components_reused": int(self._frame_counts.get("retained_components_reused", 0)),
            "retained_components_new": int(self._frame_counts.get("retained_components_new", 0)),
            "camera_overlay_scrollbar_primitives": int(self._frame_counts.get("camera_overlay_scrollbar_primitives", 0)),
            "dirty_rect_count": dirty_count,
            "dirty_rect_area_px": dirty_area,
            "dirty_rect_area_ratio": float(dirty_area_ratio),
            "compose_mode": compose_mode,
            "incremental_present_pct": float(counters.get("incremental_present_pct", 0.0)),
            "full_present_pct": float(counters.get("full_present_pct", 0.0)),
            "presented_frames": int(counters.get("presented_frames", 0)),
            "incremental_frames": int(counters.get("incremental_frames", 0)),
            "full_frames": int(counters.get("full_frames", 0)),
            "idle_skipped_frames": int(counters.get("idle_skipped_frames", 0)),
            "incremental_present_enabled": bool(self._incremental_present_enabled()),
            "scroll_bitmap_cache_enabled": bool(self._scroll_bitmap_cache_enabled()),
            "bitmap_cache_hits": 0,
            "bitmap_cache_misses": 0,
            "bitmap_cache_entry_count": 0,
            "invalidation_escape_hatch_used": bool(invalidation_escape_hatch_used),
            "invalidation_escape_hatch_reason": invalidation_escape_hatch_reason,
            "copy_count": int(estimated_copy.get("copy_count", 0)),
            "copy_bytes": int(estimated_copy.get("copy_bytes", 0)),
            "upload_bytes": int(estimated_copy.get("upload_bytes", 0)),
            "swapchain_recreate_count": int(estimated_copy.get("swapchain_recreate_count", 0)),
            "timing_ms": {
                "input": self._ns_to_ms(self._frame_perf.get("input_ns", 0.0)),
                "hit_test": self._ns_to_ms(self._frame_perf.get("hit_test_ns", 0.0)),
                "scroll_update": self._ns_to_ms(self._frame_perf.get("scroll_update_ns", 0.0)),
                "cull": self._ns_to_ms(self._frame_perf.get("cull_ns", 0.0)),
                "mount": self._ns_to_ms(self._frame_perf.get("mount_ns", 0.0)),
                "raster": self._ns_to_ms(self._frame_perf.get("raster_ns", 0.0)),
                "present": 0.0,
                "frame_total": 0.0,
            },
            "copy_timing_ms": {
                "ui_pack": self._ns_to_ms(float(estimated_copy.get("ui_pack_ns", 0))),
                "matrix_stage_clone": self._ns_to_ms(float(estimated_copy.get("matrix_stage_clone_ns", 0))),
                "matrix_snapshot_clone": self._ns_to_ms(float(estimated_copy.get("matrix_snapshot_clone_ns", 0))),
                "upload_pack": self._ns_to_ms(float(estimated_copy.get("upload_pack_ns", 0))),
                "upload_map": self._ns_to_ms(float(estimated_copy.get("upload_map_ns", 0))),
                "upload_memcpy": self._ns_to_ms(float(estimated_copy.get("upload_memcpy_ns", 0))),
                "queue_submit": self._ns_to_ms(float(estimated_copy.get("queue_submit_ns", 0))),
                "queue_present": self._ns_to_ms(float(estimated_copy.get("queue_present_ns", 0))),
            },
        }
        ctx.finalize_ui_frame()
        self._merge_ctx_copy_telemetry(ctx)
        self._merge_renderer_bitmap_cache_stats()
        self._add_perf_ns("present_ns", time.perf_counter_ns() - present_start_ns)
        self._add_perf_ns("frame_total_ns", time.perf_counter_ns() - frame_start_ns)
        perf = self.state.get("perf")
        if isinstance(perf, dict):
            timings = perf.get("timing_ms")
            if isinstance(timings, dict):
                timings["present"] = self._ns_to_ms(self._frame_perf.get("present_ns", 0.0))
                timings["frame_total"] = self._ns_to_ms(self._frame_perf.get("frame_total_ns", 0.0))

    def stop(self, ctx) -> None:
        _ = ctx

    def _ensure_compiled(self, ctx) -> None:
        if self._ui_page is not None:
            return
        self._ui_page = compile_planes_to_ui_ir(
            self._planes,
            matrix_width=int(ctx.matrix.width),
            matrix_height=int(ctx.matrix.height),
            strict=self._strict,
        )
        self._component_index = {component.component_id: component for component in self._ui_page.components}
        self._plane_index = {plane.plane_id: plane for plane in getattr(self._ui_page, "plane_manifest", ())}
        self._auto_component_size.clear()
        self._coord_registry = CoordinateFrameRegistry(
            width=int(self._ui_page.matrix.width),
            height=int(self._ui_page.matrix.height),
            default_frame="screen_tl",
        )
        self._initialize_viewport_scroll_state()
        self._initialize_plane_scroll_state()
        self._bg_color = _parse_hex_rgba(self._ui_page.background)

    def _dispatch_events(self, ctx, dt: float) -> None:
        if self._ui_page is None:
            return
        pending_before_hdi = self._ctx_pending_hdi_events(ctx)
        pending_before_intent = int(len(self._intent_queue))
        pending_before_total = int(pending_before_hdi + pending_before_intent)
        enqueued = 0
        if self._intent_queue_enabled():
            ingest_budget = max(int(self._event_batch_base), int(pending_before_hdi))
            ingest_budget = max(1, min(int(self._intent_ingest_max), ingest_budget))
            polled = ctx.poll_hdi_events(ingest_budget)
            self._frame_counts["events_polled"] = int(len(polled))
            for event in polled:
                if len(self._intent_queue) >= int(self._intent_queue_max):
                    self._intent_queue.popleft()
                    self._frame_counts["intent_queue_overflow_dropped"] = int(
                        self._frame_counts.get("intent_queue_overflow_dropped", 0)
                    ) + 1
                self._intent_queue.append(event)
                enqueued += 1
            pending_after_enqueue = int(len(self._intent_queue))
            budget = self._compute_event_budget(pending_after_enqueue)
            drain_count = min(int(budget), pending_after_enqueue)
            events = [self._intent_queue.popleft() for _ in range(drain_count)]
            pending_after_total = int(len(self._intent_queue) + self._ctx_pending_hdi_events(ctx))
            self._frame_counts["intent_queue_depth_before"] = int(pending_before_intent)
            self._frame_counts["intent_queue_depth_after_enqueue"] = int(pending_after_enqueue)
            self._frame_counts["intent_queue_depth_after_drain"] = int(len(self._intent_queue))
            self._frame_counts["intent_queue_enqueued"] = int(enqueued)
            self._frame_counts["intent_queue_drained"] = int(drain_count)
        else:
            budget = self._compute_event_budget(pending_before_hdi)
            events = ctx.poll_hdi_events(budget)
            pending_after_total = self._ctx_pending_hdi_events(ctx)
            self._frame_counts["events_polled"] = int(len(events))
            self._frame_counts["intent_queue_depth_before"] = int(0)
            self._frame_counts["intent_queue_depth_after_enqueue"] = int(0)
            self._frame_counts["intent_queue_depth_after_drain"] = int(0)
            self._frame_counts["intent_queue_enqueued"] = int(0)
            self._frame_counts["intent_queue_drained"] = int(0)
        self._frame_counts["event_budget"] = int(budget)
        self._frame_counts["event_queue_pending_before"] = int(pending_before_total)
        self._frame_counts["event_queue_pending_after"] = int(pending_after_total)
        processed_ids: list[int] = []
        if not events:
            self._merge_hdi_telemetry(ctx)
            return
        self._refresh_hit_test_index()
        scheduled_scroll_intent: ScrollIntent | None = None
        scroll_payload_for_hook: dict[str, Any] | None = None
        for event in events:
            processed_ids.append(int(event.event_id))
            self._frame_counts["events_processed"] = int(self._frame_counts.get("events_processed", 0)) + 1
            payload = event.payload if isinstance(event.payload, dict) else {}
            self._record_pointer_xy(payload)
            if event.event_type in {"scroll", "pan", "swipe"}:
                intent = _scroll_intent_from_event(event.event_type, payload, event.device)
                if intent is not None:
                    self._frame_counts["scroll_events"] = int(self._frame_counts.get("scroll_events", 0)) + 1
                    scheduled_scroll_intent = self._coalesce_scroll_intent(
                        current=scheduled_scroll_intent,
                        incoming=intent,
                    )
                    if scroll_payload_for_hook is None:
                        scroll_payload_for_hook = {}
                    if "x" in payload:
                        scroll_payload_for_hook["x"] = payload["x"]
                    if "y" in payload:
                        scroll_payload_for_hook["y"] = payload["y"]
                    if "phase" in payload:
                        scroll_payload_for_hook["phase"] = payload["phase"]
                    if "momentum_phase" in payload:
                        scroll_payload_for_hook["momentum_phase"] = payload["momentum_phase"]
                continue
            if event.event_type == "pointer_move":
                self._frame_counts["pointer_move_events"] = int(self._frame_counts.get("pointer_move_events", 0)) + 1
                self._dispatch_hover(payload, dt)
                if str(payload.get("phase", "")).lower() == "drag":
                    rect = self._event_pointer_dirty_rect(payload, margin_px=18)
                    if rect is not None:
                        self._event_pointer_dirty_rects.append(rect)
                continue
            self._frame_counts["non_scroll_non_pointer_events"] = int(
                self._frame_counts.get("non_scroll_non_pointer_events", 0)
            ) + 1
            hook = _hook_for_event(event.event_type, payload)
            target_component = self._pick_component_for_event(payload)
            rect = self._event_pointer_dirty_rect(payload, margin_px=18)
            if rect is not None:
                self._event_pointer_dirty_rects.append(rect)
            if hook is None:
                continue
            if target_component is None:
                continue
            self._invoke_bindings(target_component, hook, event.event_type, payload, dt)
        if scheduled_scroll_intent is not None:
            self._frame_counts["scroll_events_coalesced"] = int(self._frame_counts.get("scroll_events_coalesced", 0)) + 1
            self._frame_counts["scroll_scheduler_applied"] = int(1)
            self._frame_counts["scroll_scheduler_coalesced_events"] = int(scheduled_scroll_intent.event_count)
            coalesced_payload = dict(scroll_payload_for_hook or {})
            coalesced_payload["delta_x"] = float(-scheduled_scroll_intent.delta_x)
            coalesced_payload["delta_y"] = float(-scheduled_scroll_intent.delta_y)
            coalesced_payload["coalesced_count"] = int(scheduled_scroll_intent.event_count)
            if str(coalesced_payload.get("coalesce_mode", "")) != "latest" and scheduled_scroll_intent.source == "trackpad":
                coalesced_payload["coalesce_mode"] = "latest"
            if scheduled_scroll_intent.momentum_phase is not None:
                coalesced_payload["momentum_phase"] = scheduled_scroll_intent.momentum_phase
            self._dispatch_viewport_scroll(coalesced_payload, scheduled_scroll_intent)
            self._refresh_hit_test_index(force=True)
            hook = _hook_for_event("scroll", coalesced_payload)
            target_component = self._pick_component_for_event(coalesced_payload)
            if hook is not None and target_component is not None:
                self._invoke_bindings(target_component, hook, "scroll", coalesced_payload, dt)
        else:
            self._frame_counts["scroll_scheduler_applied"] = int(0)
            self._frame_counts["scroll_scheduler_coalesced_events"] = int(0)
        self._frame_counts["event_order_digest"] = _event_id_digest(processed_ids)
        self._merge_hdi_telemetry(ctx)

    def _coalesce_scroll_intent(self, *, current: ScrollIntent | None, incoming: ScrollIntent) -> ScrollIntent:
        if current is None:
            return incoming
        if not self._scroll_scheduler_enabled():
            return ScrollIntent(
                delta_x=float(current.delta_x + incoming.delta_x),
                delta_y=float(current.delta_y + incoming.delta_y),
                source=incoming.source,
                phase=incoming.phase,
                momentum_phase=incoming.momentum_phase or current.momentum_phase,
                event_count=int(current.event_count + incoming.event_count),
            )
        if incoming.source == "trackpad":
            # Trackpad path keeps latest event for lower latency while retaining count.
            return ScrollIntent(
                delta_x=float(incoming.delta_x),
                delta_y=float(incoming.delta_y),
                source=incoming.source,
                phase=incoming.phase,
                momentum_phase=incoming.momentum_phase or current.momentum_phase,
                event_count=int(current.event_count + incoming.event_count),
            )
        return ScrollIntent(
            delta_x=float(current.delta_x + incoming.delta_x),
            delta_y=float(current.delta_y + incoming.delta_y),
            source=incoming.source,
            phase=incoming.phase,
            momentum_phase=incoming.momentum_phase or current.momentum_phase,
            event_count=int(current.event_count + incoming.event_count),
        )

    def _compute_event_budget(self, pending_before: int) -> int:
        pending = max(0, int(pending_before))
        target = max(int(self._event_batch_base), pending)
        return max(1, min(int(self._event_batch_max), target))

    @staticmethod
    def _ctx_pending_hdi_events(ctx) -> int:
        getter = getattr(ctx, "pending_hdi_events", None)
        if callable(getter):
            try:
                return max(0, int(getter()))
            except Exception:  # noqa: BLE001
                return 0
        hdi = getattr(ctx, "hdi", None)
        pending = getattr(hdi, "pending_count", None)
        if callable(pending):
            try:
                return max(0, int(pending()))
            except Exception:  # noqa: BLE001
                return 0
        return 0

    def _merge_hdi_telemetry(self, ctx) -> None:
        consumer = getattr(ctx, "consume_hdi_telemetry", None)
        if consumer is None or not callable(consumer):
            return
        payload = consumer()
        if not isinstance(payload, dict):
            return
        self._frame_counts["hdi_events_dropped"] = int(payload.get("events_dropped", 0))
        self._frame_counts["hdi_events_coalesced"] = int(payload.get("events_coalesced", 0))
        self._frame_counts["hdi_queue_latency_ns_max"] = int(payload.get("queue_latency_ns_max", 0))
        self._frame_counts["hdi_queue_latency_ns_p95"] = int(payload.get("queue_latency_ns_p95", 0))

    def _dispatch_hover(self, payload: dict[str, Any], dt: float) -> None:
        if self._ui_page is None:
            return
        new_target = self._pick_component_for_event(payload)
        prev_id = self.state.get("hover_component_id")
        new_id = new_target.component_id if new_target is not None else None
        if prev_id == new_id:
            return
        prev_target = None
        if prev_id is not None:
            prev_target = next((c for c in self._ui_page.components if c.component_id == prev_id), None)
        if prev_target is not None:
            self._invoke_bindings(prev_target, "on_hover_end", "pointer_move", payload, dt)
        if new_target is not None:
            self._invoke_bindings(new_target, "on_hover_start", "pointer_move", payload, dt)
        self.state["hover_component_id"] = new_id

    def _pick_component_for_event(self, payload: dict[str, Any]):
        if self._ui_page is None:
            return None
        hit_start_ns = time.perf_counter_ns()
        self._frame_counts["hit_test_calls"] = int(self._frame_counts.get("hit_test_calls", 0)) + 1
        xy = self._extract_event_xy(payload)
        if xy is None:
            self._add_perf_ns("hit_test_ns", time.perf_counter_ns() - hit_start_ns)
            return None
        x, y = xy
        for component in self._hit_candidates_for_point(x, y):
            self._frame_counts["hit_test_candidates_checked"] = int(
                self._frame_counts.get("hit_test_candidates_checked", 0)
            ) + 1
            bounds = self._resolved_interaction_bounds(component)
            resolved_x, resolved_y = self._resolved_position(component)
            if resolved_x <= x <= resolved_x + bounds.width and resolved_y <= y <= resolved_y + bounds.height:
                self._add_perf_ns("hit_test_ns", time.perf_counter_ns() - hit_start_ns)
                return component
        self._add_perf_ns("hit_test_ns", time.perf_counter_ns() - hit_start_ns)
        return None

    def _viewport_stack_for_point(self, x: float, y: float) -> list[Any]:
        if self._ui_page is None:
            return []
        stack: list[Any] = []
        for component in self._hit_candidates_for_point(x, y):
            self._frame_counts["hit_test_candidates_checked"] = int(
                self._frame_counts.get("hit_test_candidates_checked", 0)
            ) + 1
            if component.component_type != "viewport":
                continue
            bounds = self._resolved_interaction_bounds(component)
            resolved_x, resolved_y = self._resolved_position(component)
            if resolved_x <= x <= resolved_x + bounds.width and resolved_y <= y <= resolved_y + bounds.height:
                stack.append(component)
        return stack

    def _dispatch_viewport_scroll(self, payload: dict[str, Any], intent: ScrollIntent) -> None:
        scroll_start_ns = time.perf_counter_ns()
        xy = self._extract_event_xy(payload)
        if xy is None:
            self._add_perf_ns("scroll_update_ns", time.perf_counter_ns() - scroll_start_ns)
            return
        px, py = xy
        stack = self._viewport_stack_for_point(px, py)
        rem_x = float(intent.delta_x)
        rem_y = float(intent.delta_y)
        for viewport in stack:
            consumed_x, consumed_y = self._apply_viewport_scroll_intent(
                viewport,
                ScrollIntent(
                    delta_x=rem_x,
                    delta_y=rem_y,
                    source=intent.source,
                    phase=intent.phase,
                    momentum_phase=intent.momentum_phase,
                    event_count=intent.event_count,
                ),
            )
            rem_x -= consumed_x
            rem_y -= consumed_y
            if abs(rem_x) <= 1e-9 and abs(rem_y) <= 1e-9:
                break
        if abs(rem_x) > 1e-9 or abs(rem_y) > 1e-9:
            self._apply_plane_scroll_intent(
                ScrollIntent(
                    delta_x=rem_x,
                    delta_y=rem_y,
                    source=intent.source,
                    phase=intent.phase,
                    momentum_phase=intent.momentum_phase,
                    event_count=intent.event_count,
                )
            )
        self._add_perf_ns("scroll_update_ns", time.perf_counter_ns() - scroll_start_ns)

    def _record_pointer_xy(self, payload: dict[str, Any]) -> None:
        xy = self._extract_xy_from_payload(payload)
        if xy is not None:
            self.state["last_pointer_xy"] = xy

    def _extract_event_xy(self, payload: dict[str, Any]) -> tuple[float, float] | None:
        direct = self._extract_xy_from_payload(payload)
        if direct is not None:
            return direct
        fallback = self.state.get("last_pointer_xy")
        if isinstance(fallback, tuple) and len(fallback) == 2:
            try:
                return (float(fallback[0]), float(fallback[1]))
            except (TypeError, ValueError):
                return None
        return None

    def _extract_xy_from_payload(self, payload: dict[str, Any]) -> tuple[float, float] | None:
        if "x" not in payload or "y" not in payload:
            return None
        try:
            return (float(payload["x"]), float(payload["y"]))
        except (TypeError, ValueError):
            return None

    def _event_pointer_dirty_rect(self, payload: dict[str, Any], *, margin_px: int) -> tuple[int, int, int, int] | None:
        xy = self._extract_event_xy(payload)
        if xy is None:
            return None
        x, y = xy
        margin = max(1, int(margin_px))
        left = int(math.floor(float(x))) - margin
        top = int(math.floor(float(y))) - margin
        size = int((margin * 2) + 1)
        return (left, top, size, size)

    def _resolve_handler(self, target: str) -> EventHandler | None:
        if target in self._handlers:
            return self._handlers[target]
        if "::" in target:
            _, fn_name = target.split("::", 1)
            for key, handler in self._handlers.items():
                if key.endswith(f"::{fn_name}"):
                    return handler
        return None

    def _invoke_bindings(
        self,
        component,
        hook: str,
        event_type: str,
        payload: dict[str, Any],
        dt: float,
    ) -> None:
        for binding in component.interactions:
            if binding.event != hook:
                continue
            handler = self._resolve_handler(binding.handler)
            if handler is None:
                if self._strict:
                    raise RuntimeError(f"missing handler for target: {binding.handler}")
                continue
            event_ctx = {
                "component_id": component.component_id,
                "event_type": event_type,
                "hook": hook,
                "payload": payload,
                "dt": float(dt),
            }
            handler(event_ctx, self.state)

    def _resolve_background(self) -> tuple[int, int, int, int]:
        if self._ui_page is None:
            return self._bg_color
        theme_name = str(self.state.get("active_theme", "default"))
        themes = self._planes.get("themes", {})
        if isinstance(themes, dict):
            entry = themes.get(theme_name)
            if isinstance(entry, dict):
                color = entry.get("background")
                if isinstance(color, str):
                    return _parse_hex_rgba(color)
        return _parse_hex_rgba(self._ui_page.background)

    def _resolve_text_color(self, component_id: str, props: dict[str, Any]) -> str:
        color_hex = str(props.get("color_hex", "#f5fbff"))
        theme_name = str(self.state.get("active_theme", "default"))
        theme_colors = props.get("theme_colors")
        if isinstance(theme_colors, dict):
            themed = theme_colors.get(theme_name)
            if isinstance(themed, str) and themed.strip():
                color_hex = themed
        hovered = self.state.get("hover_component_id")
        hover_hex = props.get("hover_color_hex")
        if hovered == component_id and isinstance(hover_hex, str) and hover_hex.strip():
            color_hex = hover_hex
        return color_hex

    @staticmethod
    def _resolve_text_color_for_state(
        *,
        component_id: str,
        props: dict[str, Any],
        theme_name: str,
        hovered_component_id: str | None,
    ) -> str:
        color_hex = str(props.get("color_hex", "#f5fbff"))
        theme_colors = props.get("theme_colors")
        if isinstance(theme_colors, dict):
            themed = theme_colors.get(theme_name)
            if isinstance(themed, str) and themed.strip():
                color_hex = themed
        hover_hex = props.get("hover_color_hex")
        if hovered_component_id == component_id and isinstance(hover_hex, str) and hover_hex.strip():
            color_hex = hover_hex
        return color_hex

    def _resolved_position(self, component) -> tuple[float, float]:
        self._ensure_layout_cache_state()
        key = self._resolved_position_cache_key(component)
        cached = self._layout_position_cache.get(component.component_id)
        if cached is not None and cached[0] == key:
            self._frame_counts["layout_cache_hits"] = int(self._frame_counts.get("layout_cache_hits", 0)) + 1
            return cached[1]
        x, y = self._resolved_position_base(component)
        if not (self._is_overlay_attached(component) or self._is_camera_fixed(component)):
            plane_x, plane_y = self._plane_scroll_position()
            x -= plane_x
            y -= plane_y
        resolved = (x, y)
        self._layout_position_cache[component.component_id] = (key, resolved)
        self._frame_counts["layout_cache_misses"] = int(self._frame_counts.get("layout_cache_misses", 0)) + 1
        return resolved

    def _resolved_position_cache_key(self, component) -> tuple[Any, ...]:
        props = component.style if isinstance(component.style, dict) else {}
        layout_w, layout_h = self._component_layout_size(component, props=props)
        plane_id = getattr(component, "plane_id", None)
        plane_x = 0.0
        plane_y = 0.0
        if isinstance(plane_id, str):
            plane = self._plane_index.get(plane_id)
            if plane is not None:
                plane_x = float(plane.resolved_position.x)
                plane_y = float(plane.resolved_position.y)
                plane_frame = str(plane.resolved_position.frame or plane.default_frame)
            else:
                plane_frame = ""
        else:
            plane_frame = ""
        component_frame = component.resolved_frame(self._ui_page.default_frame) if self._ui_page is not None else ""
        return (
            float(component.position.x),
            float(component.position.y),
            float(layout_w),
            float(layout_h),
            str(getattr(component, "attachment_kind", "plane")),
            str(plane_id or ""),
            plane_x,
            plane_y,
            plane_frame,
            component_frame,
            int(self._ui_page.matrix.width) if self._ui_page is not None else 0,
            int(self._ui_page.matrix.height) if self._ui_page is not None else 0,
            props.get("anchor_x"),
            props.get("anchor_y"),
            props.get("anchor_frame"),
            props.get("font_size_px"),
            bool(props.get("camera_fixed", False)),
            str(props.get("align", "")),
            str(props.get("v_align", "")),
            float(props.get("margin_bottom_px", 0.0)),
        )

    def _resolved_interaction_bounds(self, component):
        if self._ui_page is None:
            return component.resolved_interaction_bounds("screen_tl")
        self._ensure_layout_cache_state()
        props = component.style if isinstance(component.style, dict) else {}
        layout_w, layout_h = self._component_layout_size(component, props=props)
        key = (
            float(layout_w),
            float(layout_h),
            self._ui_page.default_frame,
            bool(props.get("auto_size_width", False)),
            bool(props.get("auto_size_height", False)),
        )
        cached = self._interaction_bounds_cache.get(component.component_id)
        if cached is not None and cached[0] == key:
            self._frame_counts["layout_cache_hits"] = int(self._frame_counts.get("layout_cache_hits", 0)) + 1
            return cached[1]
        bounds = component.resolved_interaction_bounds(self._ui_page.default_frame)
        if bool(props.get("auto_size_width", False)) or bool(props.get("auto_size_height", False)):
            bounds = BoundingBoxSpec(
                x=float(bounds.x),
                y=float(bounds.y),
                width=float(layout_w),
                height=float(layout_h),
                frame=bounds.frame,
            )
        self._interaction_bounds_cache[component.component_id] = (key, bounds)
        self._frame_counts["layout_cache_misses"] = int(self._frame_counts.get("layout_cache_misses", 0)) + 1
        return bounds

    def _layout_signature_current(self) -> tuple[tuple[float, float], tuple[str, ...]]:
        return (self._plane_scroll_position(), self._hit_index_active_planes())

    def _ensure_layout_cache_state(self) -> None:
        signature = self._layout_signature_current()
        if self._layout_cache_signature == signature:
            return
        self._layout_cache_signature = signature
        self._layout_position_cache.clear()
        self._interaction_bounds_cache.clear()

    def _prefetch_margins(self) -> tuple[float, float]:
        entry = self.state.get("prefetch_margin_px")
        if isinstance(entry, dict):
            try:
                mx = max(0.0, float(entry.get("x", 96.0)))
                my = max(0.0, float(entry.get("y", 96.0)))
                return (mx, my)
            except (TypeError, ValueError):
                return (96.0, 96.0)
        return (96.0, 96.0)

    def _is_component_in_camera_region(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        margin_x: float,
        margin_y: float,
    ) -> bool:
        if self._ui_page is None:
            return True
        view_w = float(self._ui_page.matrix.width)
        view_h = float(self._ui_page.matrix.height)
        left = -margin_x
        top = -margin_y
        right = view_w + margin_x
        bottom = view_h + margin_y
        comp_right = x + max(0.0, width)
        comp_bottom = y + max(0.0, height)
        if comp_right < left:
            return False
        if comp_bottom < top:
            return False
        if x > right:
            return False
        if y > bottom:
            return False
        return True

    def _load_svg_markup(self, svg_path: Path) -> str:
        cached = self._svg_markup_cache.get(svg_path)
        if cached is not None:
            return cached
        markup = svg_path.read_text(encoding="utf-8")
        self._svg_markup_cache[svg_path] = markup
        return markup

    def _draw_batch_key(self, kind: str, component) -> tuple[Any, ...]:
        if kind == "svg":
            asset_src = ""
            if component.asset is not None:
                asset_src = str(component.asset.source)
            return ("svg", asset_src, round(float(component.opacity), 4))
        props = component.style if isinstance(component.style, dict) else {}
        return (
            "text",
            round(float(component.opacity), 4),
            round(float(props.get("font_size_px", 14.0)), 4),
        )

    def _mount_batched_drawables(self, ctx, drawables: list[tuple[str, Any, float, float, str]]) -> int:
        if not drawables:
            self._frame_counts["renderer_batch_groups"] = 0
            self._frame_counts["renderer_batch_state_switches"] = 0
            return 0
        batches: list[list[tuple[str, Any, float, float, str]]] = []
        current: list[tuple[str, Any, float, float, str]] = []
        current_key: tuple[Any, ...] | None = None
        for entry in drawables:
            kind, component, _, _, _ = entry
            key = self._draw_batch_key(kind, component)
            if current_key is None or key == current_key:
                current.append(entry)
                current_key = key
                continue
            batches.append(current)
            current = [entry]
            current_key = key
        if current:
            batches.append(current)
        self._frame_counts["renderer_batch_groups"] = int(len(batches))
        self._frame_counts["renderer_batch_state_switches"] = int(max(0, len(batches) - 1))
        mounted = 0
        for batch in batches:
            for kind, component, resolved_x, resolved_y, frame in batch:
                if kind == "text":
                    props = component.style if isinstance(component.style, dict) else {}
                    text = str(props.get("text", component.component_id))
                    color_hex = self._resolve_text_color(component.component_id, props)
                    font_size_px = float(props.get("font_size_px", 14.0))
                    max_width_px = props.get("max_width_px")
                    if max_width_px is not None:
                        max_width_px = float(max_width_px)
                    if self._text_origin_uses_frame_reference(props):
                        resolved_x, resolved_y = self._resolve_text_draw_origin_frame_reference(
                            component=component,
                            x=float(resolved_x),
                            y=float(resolved_y),
                            props=props,
                        )
                    mount_start_ns = time.perf_counter_ns()
                    ctx.mount_component(
                        self._retained_text_component(
                            component_id=component.component_id,
                            text=text,
                            x=resolved_x,
                            y=resolved_y,
                            frame=frame,
                            font_size_px=font_size_px,
                            color_hex=color_hex,
                            opacity=float(component.opacity),
                            max_width_px=max_width_px,
                        )
                    )
                    self._add_perf_ns("mount_ns", time.perf_counter_ns() - mount_start_ns)
                    mounted += 1
                    continue
                if component.asset is None:
                    continue
                svg_path = (self._plane_dir / component.asset.source).resolve()
                svg_markup = self._load_svg_markup(svg_path)
                mount_start_ns = time.perf_counter_ns()
                ctx.mount_component(
                    self._retained_svg_component(
                        component_id=component.component_id,
                        svg_markup=svg_markup,
                        x=resolved_x,
                        y=resolved_y,
                        frame=frame,
                        width=float(component.width),
                        height=float(component.height),
                        opacity=float(component.opacity),
                    )
                )
                self._add_perf_ns("mount_ns", time.perf_counter_ns() - mount_start_ns)
                mounted += 1
        return mounted

    @staticmethod
    def _text_origin_uses_frame_reference(props: dict[str, Any]) -> bool:
        raw = str(props.get("text_origin_mode", "")).strip().lower()
        return raw in {"frame_reference", "component_frame_reference"}

    def _resolve_text_draw_origin_frame_reference(
        self,
        *,
        component,
        x: float,
        y: float,
        props: dict[str, Any],
    ) -> tuple[float, float]:
        if self._ui_page is None:
            return (x, y)
        viewport_w = float(self._ui_page.matrix.width)
        viewport_h = float(self._ui_page.matrix.height)
        layout_w, layout_h = self._component_layout_size(component, props=props)
        text_w, text_h = self._measure_text_layout_size(component, style=props)
        if abs(float(layout_w) - float(text_w)) <= 1e-6 and abs(float(layout_h) - float(text_h)) <= 1e-6:
            return (x, y)
        layout_ax, layout_ay = self._resolve_anchor_offset_for_size(
            component=component,
            local_w=float(layout_w),
            local_h=float(layout_h),
            viewport_w=viewport_w,
            viewport_h=viewport_h,
            props=props,
        )
        text_ax, text_ay = self._resolve_anchor_offset_for_size(
            component=component,
            local_w=float(text_w),
            local_h=float(text_h),
            viewport_w=viewport_w,
            viewport_h=viewport_h,
            props=props,
        )
        return (float(x + (layout_ax - text_ax)), float(y + (layout_ay - text_ay)))

    def _retained_text_component(
        self,
        *,
        component_id: str,
        text: str,
        x: float,
        y: float,
        frame: str,
        font_size_px: float,
        color_hex: str,
        opacity: float,
        max_width_px: float | None,
    ) -> TextComponent:
        key: tuple[Any, ...] = (
            "text",
            text,
            round(float(x), 4),
            round(float(y), 4),
            frame,
            round(float(font_size_px), 4),
            color_hex,
            round(float(opacity), 4),
            None if max_width_px is None else round(float(max_width_px), 4),
        )
        cached_entry = self._retained_mount_cache.get(component_id)
        if cached_entry is not None and cached_entry[0] == key and isinstance(cached_entry[1], TextComponent):
            self._frame_counts["retained_components_reused"] = int(self._frame_counts.get("retained_components_reused", 0)) + 1
            return cached_entry[1]
        component = TextComponent(
            component_id=component_id,
            text=text,
            position=CoordinatePoint(float(x), float(y), frame),
            size=TextSizeSpec(unit="px", value=float(font_size_px)),
            appearance=TextAppearance(color_hex=color_hex, opacity=float(opacity)),
            max_width_px=max_width_px,
        )
        self._retained_mount_cache[component_id] = (key, component)
        self._frame_counts["retained_components_new"] = int(self._frame_counts.get("retained_components_new", 0)) + 1
        return component

    def _retained_svg_component(
        self,
        *,
        component_id: str,
        svg_markup: str,
        x: float,
        y: float,
        frame: str,
        width: float,
        height: float,
        opacity: float,
    ) -> SVGComponent:
        key: tuple[Any, ...] = (
            "svg",
            hash(svg_markup),
            round(float(x), 4),
            round(float(y), 4),
            frame,
            round(float(width), 4),
            round(float(height), 4),
            round(float(opacity), 4),
        )
        cached_entry = self._retained_mount_cache.get(component_id)
        if cached_entry is not None and cached_entry[0] == key and isinstance(cached_entry[1], SVGComponent):
            self._frame_counts["retained_components_reused"] = int(self._frame_counts.get("retained_components_reused", 0)) + 1
            return cached_entry[1]
        component = SVGComponent(
            component_id=component_id,
            svg_markup=svg_markup,
            position=CoordinatePoint(float(x), float(y), frame),
            width=float(width),
            height=float(height),
            opacity=float(opacity),
        )
        self._retained_mount_cache[component_id] = (key, component)
        self._frame_counts["retained_components_new"] = int(self._frame_counts.get("retained_components_new", 0)) + 1
        return component

    @staticmethod
    def _build_scrollbar_markup(width: int, height: int, fill_hex: str) -> str:
        return (
            f'<svg width="{int(width)}" height="{int(height)}" xmlns="http://www.w3.org/2000/svg">'
            f'<rect x="0" y="0" width="{int(width)}" height="{int(height)}" rx="4" fill="{fill_hex}"/>'
            "</svg>"
        )

    def _mount_camera_overlay_scrollbar_pair(
        self,
        ctx,
        *,
        frame: str,
        track_id: str,
        thumb_id: str,
        track_x: float,
        track_y: float,
        track_w: float,
        track_h: float,
        thumb_x: float,
        thumb_y: float,
        thumb_w: float,
        thumb_h: float,
        track_markup_key: str,
        thumb_markup_key: str,
        track_opacity: float,
        thumb_opacity: float,
    ) -> None:
        self._frame_counts["camera_overlay_scrollbar_primitives"] = int(
            self._frame_counts.get("camera_overlay_scrollbar_primitives", 0)
        ) + 2
        ctx.mount_component(
            self._retained_svg_component(
                component_id=track_id,
                svg_markup=self._scrollbar_markups[track_markup_key],
                x=track_x,
                y=track_y,
                frame=frame,
                width=track_w,
                height=track_h,
                opacity=track_opacity,
            )
        )
        ctx.mount_component(
            self._retained_svg_component(
                component_id=thumb_id,
                svg_markup=self._scrollbar_markups[thumb_markup_key],
                x=thumb_x,
                y=thumb_y,
                frame=frame,
                width=thumb_w,
                height=thumb_h,
                opacity=thumb_opacity,
            )
        )

    def _begin_perf_frame(self) -> None:
        self._frame_perf = {}
        self._event_pointer_dirty_rects = []
        self._frame_counts = {
            "events_polled": 0,
            "events_processed": 0,
            "event_budget": 0,
            "event_queue_pending_before": 0,
            "event_queue_pending_after": 0,
            "event_order_digest": "0",
            "scroll_events": 0,
            "scroll_events_coalesced": 0,
            "scroll_scheduler_applied": 0,
            "scroll_scheduler_coalesced_events": 0,
            "hdi_events_dropped": 0,
            "hdi_events_coalesced": 0,
            "hdi_queue_latency_ns_max": 0,
            "hdi_queue_latency_ns_p95": 0,
            "intent_queue_depth_before": 0,
            "intent_queue_depth_after_enqueue": 0,
            "intent_queue_depth_after_drain": 0,
            "intent_queue_enqueued": 0,
            "intent_queue_drained": 0,
            "intent_queue_overflow_dropped": 0,
            "hit_test_calls": 0,
            "hit_test_candidates_checked": 0,
            "hit_test_spatial_buckets": 0,
            "layout_cache_hits": 0,
            "layout_cache_misses": 0,
            "renderer_batch_groups": 0,
            "renderer_batch_state_switches": 0,
            "retained_components_reused": 0,
            "retained_components_new": 0,
            "camera_overlay_scrollbar_primitives": 0,
            "pointer_move_events": 0,
            "non_scroll_non_pointer_events": 0,
        }

    def _hit_index_active_planes(self) -> tuple[str, ...]:
        if self._ui_page is None or self._ui_page.ir_version != "planes-v2":
            return ()
        raw = getattr(self._ui_page, "active_plane_ids", ())
        if not isinstance(raw, (list, tuple, set)):
            return ()
        return tuple(sorted(str(item) for item in raw if isinstance(item, str)))

    def _hit_index_signature_current(
        self,
    ) -> tuple[tuple[float, float], tuple[tuple[str, float, float], ...], tuple[str, ...]]:
        return (self._plane_scroll_position(), self._viewport_scroll_snapshot(), self._hit_index_active_planes())

    def _refresh_hit_test_index(self, *, force: bool = False) -> None:
        if self._ui_page is None:
            self._hit_spatial_index = {}
            self._hit_index_all = []
            self._hit_index_signature = None
            return
        signature = self._hit_index_signature_current()
        if not force and self._hit_index_signature == signature:
            self._frame_counts["hit_test_spatial_buckets"] = int(len(self._hit_spatial_index))
            return
        ordered = [component for component in self._ui_page.ordered_components_for_hit_test() if self._component_is_active(component)]
        self._hit_index_all = ordered
        buckets: dict[tuple[int, int], list[Any]] = {}
        cell_px = max(1, int(self._hit_grid_cell_px))
        for component in ordered:
            bounds = self._resolved_interaction_bounds(component)
            width = float(bounds.width)
            height = float(bounds.height)
            if width <= 0.0 or height <= 0.0:
                continue
            x, y = self._resolved_position(component)
            min_cx = int(math.floor(x / cell_px))
            max_cx = int(math.floor((x + width) / cell_px))
            min_cy = int(math.floor(y / cell_px))
            max_cy = int(math.floor((y + height) / cell_px))
            for cx in range(min_cx, max_cx + 1):
                for cy in range(min_cy, max_cy + 1):
                    key = (cx, cy)
                    if key not in buckets:
                        buckets[key] = []
                    buckets[key].append(component)
        self._hit_spatial_index = buckets
        self._hit_index_signature = signature
        self._frame_counts["hit_test_spatial_buckets"] = int(len(self._hit_spatial_index))

    def _hit_candidates_for_point(self, x: float, y: float) -> list[Any]:
        if self._ui_page is None:
            return []
        self._refresh_hit_test_index()
        cell_px = max(1, int(self._hit_grid_cell_px))
        cx = int(math.floor(float(x) / cell_px))
        cy = int(math.floor(float(y) / cell_px))
        candidates = self._hit_spatial_index.get((cx, cy))
        if candidates is not None:
            return candidates
        return self._hit_index_all

    def _current_dirty_signature(self) -> tuple[str, str | None, tuple[tuple[str, float, float], ...]]:
        theme = str(self.state.get("active_theme", "default"))
        hover = self.state.get("hover_component_id")
        hover_id = str(hover) if isinstance(hover, str) else None
        return (theme, hover_id, self._viewport_scroll_snapshot())

    def _viewport_scroll_snapshot(self) -> tuple[tuple[str, float, float], ...]:
        raw = self.state.get("viewport_scroll")
        if not isinstance(raw, dict):
            return ()
        out: list[tuple[str, float, float]] = []
        for key, value in raw.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            try:
                sx = float(value.get("x", 0.0))
                sy = float(value.get("y", 0.0))
            except (TypeError, ValueError):
                sx = 0.0
                sy = 0.0
            out.append((key, sx, sy))
        out.sort(key=lambda item: item[0])
        return tuple(out)

    def _compute_dirty_rects(
        self,
        *,
        pre_plane_scroll: tuple[float, float],
        post_plane_scroll: tuple[float, float],
        pre_signature: tuple[str, str | None, tuple[tuple[str, float, float], ...]],
        post_signature: tuple[str, str | None, tuple[tuple[str, float, float], ...]],
        events_processed: int,
    ) -> list[tuple[int, int, int, int]]:
        if self._ui_page is None:
            return []
        self._frame_scroll_shift = None
        view_w = int(self._ui_page.matrix.width)
        view_h = int(self._ui_page.matrix.height)
        full = [(0, 0, view_w, view_h)]
        if self._last_dirty_signature is None or self._last_plane_scroll is None:
            self._reset_scroll_shift_residual()
            return self._bootstrap_dirty_rects(view_w=view_w, view_h=view_h)
        if (
            pre_signature == post_signature
            and pre_plane_scroll == post_plane_scroll
            and events_processed == 0
            and self._last_dirty_signature == post_signature
            and self._last_plane_scroll == post_plane_scroll
        ):
            return []
        previous_signature = self._last_dirty_signature
        previous_plane_scroll = self._last_plane_scroll
        theme_or_hover_changed = previous_signature[0:2] != post_signature[0:2]
        hover_changed = previous_signature[1] != post_signature[1]
        theme_changed = previous_signature[0] != post_signature[0]
        viewport_scroll_changed = previous_signature[2] != post_signature[2]
        dx = float(post_plane_scroll[0] - previous_plane_scroll[0])
        dy = float(post_plane_scroll[1] - previous_plane_scroll[1])
        plane_changed = abs(dx) > 1e-9 or abs(dy) > 1e-9
        dirty_rects: list[tuple[int, int, int, int]] = []
        if hover_changed:
            dirty_rects.extend(
                self._hover_transition_dirty_rects(
                    pre_hover_id=previous_signature[1],
                    post_hover_id=post_signature[1],
                )
            )
        if theme_changed:
            theme_rects = self._theme_transition_dirty_rects(
                pre_theme=previous_signature[0],
                post_theme=post_signature[0],
                pre_hover_id=previous_signature[1],
                post_hover_id=post_signature[1],
            )
            if theme_rects is None:
                return full
            dirty_rects.extend(theme_rects)
        if viewport_scroll_changed:
            dirty_rects.extend(
                self._viewport_scroll_dirty_rects(
                    pre_viewport_scroll=previous_signature[2],
                    post_viewport_scroll=post_signature[2],
                )
            )
        if self._event_pointer_dirty_rects:
            dirty_rects.extend(self._event_pointer_dirty_rects)
        if not plane_changed:
            normalized = self._normalize_local_dirty_rects(dirty_rects, view_w=view_w, view_h=view_h)
            if normalized:
                return normalized
            if events_processed <= 0:
                return []
            if int(self._frame_counts.get("pointer_move_events", 0)) > 0:
                return []
            if int(self._frame_counts.get("scroll_events", 0)) > 0:
                return []
            if int(self._frame_counts.get("non_scroll_non_pointer_events", 0)) > 0:
                return []
            if theme_or_hover_changed or viewport_scroll_changed:
                return []
            return full
        if dirty_rects and self._has_camera_overlay_activity():
            # Preserve visual parity when camera overlays are active.
            self._reset_scroll_shift_residual()
            return full
        if not dirty_rects and self._has_camera_overlay_activity():
            self._reset_scroll_shift_residual()
            return full
        shift_x, shift_y = self._quantized_scroll_shift(dx, dy)
        adx = abs(int(shift_x))
        ady = abs(int(shift_y))
        if adx >= view_w or ady >= view_h:
            self._reset_scroll_shift_residual()
            return full
        if shift_x != 0 or shift_y != 0:
            self._frame_scroll_shift = (shift_x, shift_y)
        dirty_rects.extend(self._plane_scroll_dirty_rects(view_w=view_w, view_h=view_h, shift_x=shift_x, shift_y=shift_y))
        dirty_rects.extend(self._plane_scrollbar_dirty_rects())
        normalized = self._normalize_local_dirty_rects(dirty_rects, view_w=view_w, view_h=view_h)
        return normalized

    @staticmethod
    def _bootstrap_dirty_rects(*, view_w: int, view_h: int) -> list[tuple[int, int, int, int]]:
        """Prime first present via split rects to avoid full-frame compose mode spikes."""
        if view_w <= 0 or view_h <= 0:
            return []
        if view_w == 1:
            return [(0, 0, 1, view_h)]
        left_w = max(1, int(view_w // 2))
        right_w = int(view_w - left_w)
        if right_w <= 0:
            return [(0, 0, view_w, view_h)]
        return [(0, 0, left_w, view_h), (left_w, 0, right_w, view_h)]

    def _hover_transition_dirty_rects(
        self,
        *,
        pre_hover_id: str | None,
        post_hover_id: str | None,
    ) -> list[tuple[int, int, int, int]]:
        if self._ui_page is None:
            return []
        candidate_ids: list[str] = []
        if isinstance(pre_hover_id, str) and pre_hover_id:
            candidate_ids.append(pre_hover_id)
        if isinstance(post_hover_id, str) and post_hover_id and post_hover_id not in candidate_ids:
            candidate_ids.append(post_hover_id)
        rects: list[tuple[int, int, int, int]] = []
        for component_id in candidate_ids:
            component = self._component_index.get(component_id)
            if component is None:
                continue
            rect = self._component_dirty_rect(component, margin_px=1)
            if rect is not None:
                rects.append(rect)
        return rects

    def _theme_transition_dirty_rects(
        self,
        *,
        pre_theme: str,
        post_theme: str,
        pre_hover_id: str | None,
        post_hover_id: str | None,
    ) -> list[tuple[int, int, int, int]] | None:
        if self._ui_page is None:
            return []
        pre_bg = self._resolve_background_for_theme(pre_theme)
        post_bg = self._resolve_background_for_theme(post_theme)
        if pre_bg != post_bg:
            # Full-surface background changes require full-frame invalidation.
            return None
        hovered_before = pre_hover_id if isinstance(pre_hover_id, str) else None
        hovered_after = post_hover_id if isinstance(post_hover_id, str) else None
        rects: list[tuple[int, int, int, int]] = []
        for component in self._ui_page.components:
            if component.component_type != "text":
                continue
            if not component.visible or not self._component_is_active(component):
                continue
            props = component.style if isinstance(component.style, dict) else {}
            if not isinstance(props.get("theme_colors"), dict):
                continue
            pre_color = self._resolve_text_color_for_state(
                component_id=component.component_id,
                props=props,
                theme_name=pre_theme,
                hovered_component_id=hovered_before,
            )
            post_color = self._resolve_text_color_for_state(
                component_id=component.component_id,
                props=props,
                theme_name=post_theme,
                hovered_component_id=hovered_after,
            )
            if pre_color == post_color:
                continue
            rect = self._component_dirty_rect(component, margin_px=1)
            if rect is not None:
                rects.append(rect)
        return rects

    def _component_dirty_rect(self, component, *, margin_px: int) -> tuple[int, int, int, int] | None:
        x, y = self._resolved_position(component)
        bounds = self._resolved_interaction_bounds(component)
        props = component.style if isinstance(component.style, dict) else {}
        layout_w, layout_h = self._component_layout_size(component, props=props)
        width = max(0.0, float(bounds.width), float(layout_w))
        height = max(0.0, float(bounds.height), float(layout_h))
        if width <= 0.0 or height <= 0.0:
            return None
        margin = max(0, int(margin_px))
        left = int(math.floor(x)) - margin
        top = int(math.floor(y)) - margin
        right = int(math.ceil(x + width)) + margin
        bottom = int(math.ceil(y + height)) + margin
        w = max(0, right - left)
        h = max(0, bottom - top)
        if w <= 0 or h <= 0:
            return None
        return (left, top, w, h)

    def _resolve_background_for_theme(self, theme_name: str) -> tuple[int, int, int, int]:
        if self._ui_page is None:
            return self._bg_color
        themes = self._planes.get("themes", {})
        if isinstance(themes, dict):
            entry = themes.get(str(theme_name))
            if isinstance(entry, dict):
                color = entry.get("background")
                if isinstance(color, str):
                    return _parse_hex_rgba(color)
        return _parse_hex_rgba(self._ui_page.background)

    def _compute_scroll_shift(
        self,
        *,
        pre_plane_scroll: tuple[float, float],
        post_plane_scroll: tuple[float, float],
        pre_signature: tuple[str, str | None, tuple[tuple[str, float, float], ...]],
        post_signature: tuple[str, str | None, tuple[tuple[str, float, float], ...]],
    ) -> tuple[int, int] | None:
        _ = (pre_plane_scroll, post_plane_scroll, pre_signature, post_signature)
        return self._frame_scroll_shift

    def _quantized_scroll_shift(self, dx: float, dy: float) -> tuple[int, int]:
        # Quantize to integer shifts while carrying fractional residuals forward.
        # positive plane-scroll means content moves left/up in camera space.
        rx, ry = self._scroll_shift_residual
        effective_x = (-float(dx)) + float(rx)
        effective_y = (-float(dy)) + float(ry)
        shift_x = int(math.floor(effective_x)) if effective_x >= 0.0 else int(math.ceil(effective_x))
        shift_y = int(math.floor(effective_y)) if effective_y >= 0.0 else int(math.ceil(effective_y))
        self._scroll_shift_residual = (float(effective_x - shift_x), float(effective_y - shift_y))
        return (shift_x, shift_y)

    @staticmethod
    def _plane_scroll_dirty_rects(
        *,
        view_w: int,
        view_h: int,
        shift_x: int,
        shift_y: int,
    ) -> list[tuple[int, int, int, int]]:
        adx = abs(int(shift_x))
        ady = abs(int(shift_y))
        rects: list[tuple[int, int, int, int]] = []
        if adx > 0:
            if shift_x < 0:
                rects.append((view_w - adx, 0, adx, view_h - ady if ady > 0 else view_h))
            else:
                rects.append((0, 0, adx, view_h - ady if ady > 0 else view_h))
        if ady > 0:
            if shift_y < 0:
                rects.append((0, view_h - ady, view_w - adx if adx > 0 else view_w, ady))
            else:
                rects.append((0, 0, view_w - adx if adx > 0 else view_w, ady))
        if adx > 0 and ady > 0:
            corner_x = view_w - adx if shift_x < 0 else 0
            corner_y = view_h - ady if shift_y < 0 else 0
            rects.append((corner_x, corner_y, adx, ady))
        return rects

    def _reset_scroll_shift_residual(self) -> None:
        self._scroll_shift_residual = (0.0, 0.0)

    def _has_camera_overlay_activity(self) -> bool:
        if self._ui_page is None:
            return False
        for component in self._ui_page.components:
            if not component.visible:
                continue
            if not self._component_is_active(component):
                continue
            if self._is_overlay_attached(component) or self._is_camera_fixed(component):
                return True
        return False

    def _viewport_scroll_dirty_rects(
        self,
        *,
        pre_viewport_scroll: tuple[tuple[str, float, float], ...],
        post_viewport_scroll: tuple[tuple[str, float, float], ...],
    ) -> list[tuple[int, int, int, int]]:
        if self._ui_page is None:
            return []
        before = {item[0]: (float(item[1]), float(item[2])) for item in pre_viewport_scroll}
        after = {item[0]: (float(item[1]), float(item[2])) for item in post_viewport_scroll}
        changed_ids: set[str] = set()
        for key in set(before.keys()) | set(after.keys()):
            if key not in before or key not in after:
                changed_ids.add(key)
                continue
            bx, by = before[key]
            ax, ay = after[key]
            if abs(ax - bx) > 1e-9 or abs(ay - by) > 1e-9:
                changed_ids.add(key)
        rects: list[tuple[int, int, int, int]] = []
        for viewport_id in changed_ids:
            component = self._component_index.get(viewport_id)
            if component is None or component.component_type != "viewport":
                continue
            if not component.visible or not self._component_is_active(component):
                continue
            x, y = self._resolved_position(component)
            rects.append(
                (
                    int(math.floor(x)),
                    int(math.floor(y)),
                    int(math.ceil(float(component.width))),
                    int(math.ceil(float(component.height))),
                )
            )
        return rects

    def _plane_scrollbar_dirty_rects(self) -> list[tuple[int, int, int, int]]:
        if self._ui_page is None:
            return []
        max_x, max_y = self._plane_scroll_limits()
        if max_x <= 1e-9 and max_y <= 1e-9:
            return []
        view_w = float(self._ui_page.matrix.width)
        view_h = float(self._ui_page.matrix.height)
        rects: list[tuple[int, int, int, int]] = []
        if max_x > 1e-9:
            track_h = 6.0
            track_x = 4.0
            track_y = view_h - track_h - 2.0
            track_w = max(16.0, view_w - 12.0)
            rects.append(
                (
                    int(math.floor(track_x)),
                    int(math.floor(track_y)),
                    int(math.ceil(track_w)),
                    int(math.ceil(track_h)),
                )
            )
        if max_y > 1e-9:
            track_w = 6.0
            track_x = view_w - track_w - 2.0
            track_y = 72.0
            track_h = max(16.0, view_h - 82.0)
            rects.append(
                (
                    int(math.floor(track_x)),
                    int(math.floor(track_y)),
                    int(math.ceil(track_w)),
                    int(math.ceil(track_h)),
                )
            )
        return rects

    @staticmethod
    def _normalize_local_dirty_rects(
        rects: list[tuple[int, int, int, int]],
        *,
        view_w: int,
        view_h: int,
    ) -> list[tuple[int, int, int, int]]:
        out: list[tuple[int, int, int, int]] = []
        for (x, y, w, h) in rects:
            if w <= 0 or h <= 0:
                continue
            if x >= view_w or y >= view_h:
                continue
            cx = max(0, int(x))
            cy = max(0, int(y))
            cw = min(int(w) - max(0, -int(x)), view_w - cx)
            ch = min(int(h) - max(0, -int(y)), view_h - cy)
            if cw <= 0 or ch <= 0:
                continue
            out.append((cx, cy, cw, ch))
        out.sort(key=lambda r: (r[1], r[0], r[2], r[3]))
        deduped: list[tuple[int, int, int, int]] = []
        seen: set[tuple[int, int, int, int]] = set()
        for item in out:
            if item in seen:
                continue
            deduped.append(item)
            seen.add(item)
        return deduped

    def _is_full_frame_dirty(self, dirty_rects: list[tuple[int, int, int, int]]) -> bool:
        if self._ui_page is None:
            return False
        if len(dirty_rects) != 1:
            return False
        x, y, w, h = dirty_rects[0]
        return x == 0 and y == 0 and w == int(self._ui_page.matrix.width) and h == int(self._ui_page.matrix.height)

    def _estimate_copy_telemetry(
        self,
        *,
        compose_mode: str,
        dirty_rects: list[tuple[int, int, int, int]],
    ) -> dict[str, int]:
        if self._ui_page is None:
            return {"copy_count": 0, "copy_bytes": 0}
        if compose_mode == "full_frame":
            return {
                "copy_count": 1,
                "copy_bytes": int(self._ui_page.matrix.width) * int(self._ui_page.matrix.height) * 4,
            }
        return {
            "copy_count": int(len(dirty_rects)),
            "copy_bytes": int(sum((w * h * 4) for (_, _, w, h) in dirty_rects)),
        }

    def _merge_ctx_copy_telemetry(self, ctx) -> None:
        if not hasattr(ctx, "consume_ui_copy_telemetry"):
            return
        payload = ctx.consume_ui_copy_telemetry()
        if not isinstance(payload, dict):
            return
        perf = self.state.get("perf")
        if not isinstance(perf, dict):
            return
        perf["copy_count"] = int(payload.get("copy_count", perf.get("copy_count", 0)))
        perf["copy_bytes"] = int(payload.get("copy_bytes", perf.get("copy_bytes", 0)))
        perf["upload_bytes"] = int(payload.get("upload_bytes", perf.get("upload_bytes", 0)))
        perf["swapchain_recreate_count"] = int(
            payload.get("swapchain_recreate_count", perf.get("swapchain_recreate_count", 0))
        )
        copy_timing = perf.get("copy_timing_ms")
        if not isinstance(copy_timing, dict):
            return
        copy_timing["ui_pack"] = self._ns_to_ms(float(payload.get("ui_pack_ns", 0)))
        copy_timing["matrix_stage_clone"] = self._ns_to_ms(float(payload.get("matrix_stage_clone_ns", 0)))
        copy_timing["matrix_snapshot_clone"] = self._ns_to_ms(float(payload.get("matrix_snapshot_clone_ns", 0)))
        copy_timing["upload_pack"] = self._ns_to_ms(float(payload.get("upload_pack_ns", 0)))
        copy_timing["upload_map"] = self._ns_to_ms(float(payload.get("upload_map_ns", 0)))
        copy_timing["upload_memcpy"] = self._ns_to_ms(float(payload.get("upload_memcpy_ns", 0)))
        copy_timing["queue_submit"] = self._ns_to_ms(float(payload.get("queue_submit_ns", 0)))
        copy_timing["queue_present"] = self._ns_to_ms(float(payload.get("queue_present_ns", 0)))

    def _merge_renderer_bitmap_cache_stats(self) -> None:
        perf = self.state.get("perf")
        if not isinstance(perf, dict):
            return
        consumer = getattr(self._renderer, "consume_bitmap_cache_stats", None)
        if consumer is None or not callable(consumer):
            return
        payload = consumer()
        if not isinstance(payload, dict):
            return
        perf["scroll_bitmap_cache_enabled"] = bool(payload.get("enabled", perf.get("scroll_bitmap_cache_enabled", False)))
        perf["bitmap_cache_hits"] = int(payload.get("hits", perf.get("bitmap_cache_hits", 0)))
        perf["bitmap_cache_misses"] = int(payload.get("misses", perf.get("bitmap_cache_misses", 0)))
        perf["bitmap_cache_entry_count"] = int(payload.get("entry_count", perf.get("bitmap_cache_entry_count", 0)))

    def _incremental_present_enabled(self) -> bool:
        raw = self.state.get("incremental_present_enabled")
        if isinstance(raw, bool):
            return raw
        return bool(self._incremental_present_enabled_default)

    def _scroll_bitmap_cache_enabled(self) -> bool:
        raw = self.state.get("scroll_bitmap_cache_enabled")
        if isinstance(raw, bool):
            return raw
        return bool(self._scroll_bitmap_cache_enabled_default)

    def _scroll_scheduler_enabled(self) -> bool:
        raw = self.state.get("scroll_scheduler_enabled")
        if isinstance(raw, bool):
            return raw
        return bool(self._scroll_scheduler_enabled_default)

    def _intent_queue_enabled(self) -> bool:
        raw = self.state.get("intent_queue_enabled")
        if isinstance(raw, bool):
            return raw
        return bool(self._intent_queue_enabled_default)

    def _consume_invalidation_escape_hatch(self) -> tuple[bool, str | None]:
        raw = self.state.get("force_full_invalidation")
        if not isinstance(raw, bool) or not raw:
            return (False, None)
        self.state["force_full_invalidation"] = False
        reason_raw = self.state.get("force_full_invalidation_reason")
        reason = str(reason_raw) if isinstance(reason_raw, str) and reason_raw else "requested"
        self.state["force_full_invalidation_reason"] = None
        return (True, reason)

    def _update_present_counters(self, compose_mode: str) -> dict[str, int | float]:
        raw = self.state.get("present_counters")
        if not isinstance(raw, dict):
            raw = {}
            self.state["present_counters"] = raw
        presented = int(raw.get("presented_frames", 0))
        incremental = int(raw.get("incremental_frames", 0))
        full = int(raw.get("full_frames", 0))
        idle = int(raw.get("idle_skipped_frames", 0))
        if compose_mode == "partial_dirty":
            incremental += 1
            presented += 1
        elif compose_mode == "full_frame":
            full += 1
            presented += 1
        elif compose_mode == "idle_skip":
            idle += 1
        raw["presented_frames"] = int(presented)
        raw["incremental_frames"] = int(incremental)
        raw["full_frames"] = int(full)
        raw["idle_skipped_frames"] = int(idle)
        if presented <= 0:
            incremental_pct = 0.0
            full_pct = 0.0
        else:
            incremental_pct = float(incremental) * 100.0 / float(presented)
            full_pct = float(full) * 100.0 / float(presented)
        raw["incremental_present_pct"] = float(incremental_pct)
        raw["full_present_pct"] = float(full_pct)
        return {
            "presented_frames": int(presented),
            "incremental_frames": int(incremental),
            "full_frames": int(full),
            "idle_skipped_frames": int(idle),
            "incremental_present_pct": float(incremental_pct),
            "full_present_pct": float(full_pct),
        }

    def _add_perf_ns(self, key: str, delta_ns: int) -> None:
        self._frame_perf[key] = float(self._frame_perf.get(key, 0.0) + max(0, int(delta_ns)))

    @staticmethod
    def _ns_to_ms(value_ns: float) -> float:
        return float(value_ns) / 1_000_000.0

    def _resolved_position_base(self, component) -> tuple[float, float]:
        if self._ui_page is None:
            return (float(component.position.x), float(component.position.y))
        component_frame = component.resolved_frame(self._ui_page.default_frame)
        x = float(component.position.x)
        y = float(component.position.y)
        props = component.style if isinstance(component.style, dict) else {}
        layout_w, layout_h = self._component_layout_size(component, props=props)
        if self._ui_page.ir_version == "planes-v2":
            plane_id = getattr(component, "plane_id", None)
            if isinstance(plane_id, str) and plane_id:
                plane = self._plane_index.get(plane_id)
                if plane is not None:
                    plane_frame = str(plane.resolved_position.frame or plane.default_frame)
                    plane_x = float(plane.resolved_position.x)
                    plane_y = float(plane.resolved_position.y)
                    if plane_frame != component_frame:
                        plane_x, plane_y = self._transform_point_between_frames(
                            plane_x,
                            plane_y,
                            from_frame=plane_frame,
                            to_frame=component_frame,
                        )
                    x += plane_x
                    y += plane_y
        x, y = self._transform_point_to_screen_tl(x, y, from_frame=component_frame)
        align = str(props.get("align", "")).lower()
        if align == "center":
            x = (float(self._ui_page.matrix.width) - float(layout_w)) / 2.0
        v_align = str(props.get("v_align", "")).lower()
        if v_align == "bottom":
            margin_bottom_px = float(props.get("margin_bottom_px", 0.0))
            y = float(self._ui_page.matrix.height) - float(layout_h) - margin_bottom_px
        anchor_x_px, anchor_y_px = self._resolve_anchor_offset_px(
            component=component,
            layout_w=float(layout_w),
            layout_h=float(layout_h),
            viewport_w=float(self._ui_page.matrix.width),
            viewport_h=float(self._ui_page.matrix.height),
            props=props,
        )
        x -= anchor_x_px
        y -= anchor_y_px
        return (x, y)

    def _resolve_anchor_offset_px(
        self,
        *,
        component,
        layout_w: float,
        layout_h: float,
        viewport_w: float,
        viewport_h: float,
        props: dict[str, Any],
    ) -> tuple[float, float]:
        return self._resolve_anchor_offset_for_size(
            component=component,
            local_w=float(layout_w),
            local_h=float(layout_h),
            viewport_w=viewport_w,
            viewport_h=viewport_h,
            props=props,
        )

    def _resolve_anchor_offset_for_size(
        self,
        *,
        component,
        local_w: float,
        local_h: float,
        viewport_w: float,
        viewport_h: float,
        props: dict[str, Any],
    ) -> tuple[float, float]:
        anchor_frame = self._resolve_anchor_frame(component, props)
        font_size_px = float(props.get("font_size_px", 16.0)) if isinstance(props.get("font_size_px"), (int, float)) else 16.0
        ax_local = self._resolve_anchor_axis_local_value(
            axis="x",
            raw=props.get("anchor_x", 0.0),
            local_w=local_w,
            local_h=local_h,
            viewport_w=viewport_w,
            viewport_h=viewport_h,
            font_size_px=font_size_px,
        )
        ay_local = self._resolve_anchor_axis_local_value(
            axis="y",
            raw=props.get("anchor_y", 0.0),
            local_w=local_w,
            local_h=local_h,
            viewport_w=viewport_w,
            viewport_h=viewport_h,
            font_size_px=font_size_px,
        )
        local_reg = CoordinateFrameRegistry(
            width=max(1, int(round(local_w))),
            height=max(1, int(round(local_h))),
            default_frame="screen_tl",
        )
        try:
            sx, sy = local_reg.transform_point((ax_local, ay_local), from_frame=anchor_frame, to_frame="screen_tl")
            return (float(sx), float(sy))
        except Exception:
            return (ax_local, ay_local)

    def _resolve_anchor_axis_local_value(
        self,
        *,
        axis: str,
        raw: Any,
        local_w: float,
        local_h: float,
        viewport_w: float,
        viewport_h: float,
        font_size_px: float,
    ) -> float:
        local_size = local_w if axis == "x" else local_h
        if isinstance(raw, (int, float)):
            return float(raw) * float(local_size)
        if not isinstance(raw, str):
            return 0.0
        text = raw.strip().lower()
        if not text:
            return 0.0
        if text.endswith("%"):
            try:
                return (float(text[:-1].strip()) / 100.0) * float(local_size)
            except ValueError:
                return 0.0
        if text.endswith("px"):
            try:
                return float(text[:-2].strip())
            except ValueError:
                return 0.0
        if text.endswith("em"):
            try:
                return float(text[:-2].strip()) * float(font_size_px)
            except ValueError:
                return 0.0
        if text.endswith("vw"):
            try:
                return (float(text[:-2].strip()) / 100.0) * float(viewport_w)
            except ValueError:
                return 0.0
        if text.endswith("vh"):
            try:
                return (float(text[:-2].strip()) / 100.0) * float(viewport_h)
            except ValueError:
                return 0.0
        try:
            return float(text) * float(local_size)
        except ValueError:
            return 0.0

    def _resolve_anchor_frame(self, component, props: dict[str, Any]) -> str:
        raw = props.get("anchor_frame")
        if isinstance(raw, str) and raw.strip():
            return raw
        if (
            getattr(component, "component_type", "") == "text"
            and ("anchor_x" in props or "anchor_y" in props)
        ):
            return "cartesian_center"
        plane_id = getattr(component, "plane_id", None)
        if isinstance(plane_id, str):
            plane = self._plane_index.get(plane_id)
            if plane is not None and isinstance(plane.default_frame, str) and plane.default_frame.strip():
                return plane.default_frame
        if self._ui_page is not None and isinstance(self._ui_page.default_frame, str) and self._ui_page.default_frame.strip():
            return self._ui_page.default_frame
        return "cartesian_center"

    def _component_layout_size(self, component, *, props: dict[str, Any] | None = None) -> tuple[float, float]:
        style = props if isinstance(props, dict) else (component.style if isinstance(component.style, dict) else {})
        auto_w = bool(style.get("auto_size_width", False))
        auto_h = bool(style.get("auto_size_height", False))
        if not auto_w and not auto_h:
            return (float(component.width), float(component.height))
        measured_w, measured_h = self._measure_text_layout_size(component, style=style)
        final_w = measured_w if auto_w else float(component.width)
        final_h = measured_h if auto_h else float(component.height)
        final_w = max(0.0, float(final_w))
        final_h = max(0.0, float(final_h))
        self._auto_component_size[component.component_id] = (final_w, final_h)
        return (final_w, final_h)

    def _measure_text_layout_size(self, component, *, style: dict[str, Any]) -> tuple[float, float]:
        if component.component_type != "text":
            return (float(component.width), float(component.height))
        text = str(style.get("text", component.component_id))
        try:
            font_size_px = float(style.get("font_size_px", 14.0))
        except (TypeError, ValueError):
            font_size_px = 14.0
        max_width_px_raw = style.get("max_width_px")
        if max_width_px_raw is None:
            max_width_px = None
        else:
            try:
                max_width_px = float(max_width_px_raw)
            except (TypeError, ValueError):
                max_width_px = None
        try:
            opacity = float(style.get("opacity", 1.0))
        except (TypeError, ValueError):
            opacity = 1.0
        try:
            letter_spacing_px = float(style.get("letter_spacing_px", 0.0))
        except (TypeError, ValueError):
            letter_spacing_px = 0.0
        try:
            line_height_multiplier = float(style.get("line_height_multiplier", 1.2))
        except (TypeError, ValueError):
            line_height_multiplier = 1.2
        req = TextMeasureRequest(
            text=text,
            font=FontSpec(),
            font_size_px=font_size_px,
            appearance=TextAppearance(
                color_hex=str(style.get("color_hex", "#f5fbff")),
                opacity=max(0.0, min(1.0, opacity)),
                letter_spacing_px=letter_spacing_px,
                line_height_multiplier=max(0.01, line_height_multiplier),
            ),
            max_width_px=max_width_px,
        )
        metrics = self._renderer.measure_text(req)
        return (float(metrics.width_px), float(metrics.height_px))

    def _transform_point_to_screen_tl(self, x: float, y: float, *, from_frame: str) -> tuple[float, float]:
        return self._transform_point_between_frames(x, y, from_frame=from_frame, to_frame="screen_tl")

    def _transform_point_between_frames(
        self,
        x: float,
        y: float,
        *,
        from_frame: str,
        to_frame: str,
    ) -> tuple[float, float]:
        if from_frame == to_frame:
            return (x, y)
        registry = self._coord_registry
        if registry is None:
            return (x, y)
        try:
            tx, ty = registry.transform_point((float(x), float(y)), from_frame=from_frame, to_frame=to_frame)
            return (float(tx), float(ty))
        except Exception:
            return (x, y)

    def _is_camera_fixed(self, component) -> bool:
        props = component.style if isinstance(component.style, dict) else {}
        return bool(props.get("camera_fixed", False))

    def _is_overlay_attached(self, component) -> bool:
        return str(getattr(component, "attachment_kind", "plane")) == "camera_overlay"

    def _component_is_active(self, component) -> bool:
        if self._ui_page is None:
            return True
        if self._ui_page.ir_version != "planes-v2":
            return True
        if self._is_overlay_attached(component):
            return True
        active = set(getattr(self._ui_page, "active_plane_ids", ()))
        if not active:
            return True
        plane_id = getattr(component, "plane_id", None)
        if not isinstance(plane_id, str):
            return False
        return plane_id in active

    def _mount_viewport_cutout_mask(self, ctx, component) -> None:
        if self._ui_page is None:
            return
        frame = component.resolved_frame(self._ui_page.default_frame)
        bg = _rgba_to_hex(self._bg_color)
        x, y = self._resolved_position(component)
        w = float(component.width)
        h = float(component.height)
        full_w = float(self._ui_page.matrix.width)
        full_h = float(self._ui_page.matrix.height)
        self._mount_viewport_content(ctx, component, x=x, y=y, frame=frame)

        # Four rectangles around the viewport create a "cutout window" effect.
        masks = [
            (0.0, 0.0, full_w, max(0.0, y)),  # top
            (0.0, y + h, full_w, max(0.0, full_h - (y + h))),  # bottom
            (0.0, y, max(0.0, x), h),  # left
            (x + w, y, max(0.0, full_w - (x + w)), h),  # right
        ]
        for i, (mx, my, mw, mh) in enumerate(masks):
            if mw <= 0 or mh <= 0:
                continue
            iw = int(round(mw))
            ih = int(round(mh))
            markup = (
                f'<svg width="{iw}" height="{ih}" '
                'xmlns="http://www.w3.org/2000/svg">'
                f'<rect x="0" y="0" width="{iw}" height="{ih}" fill="{bg}"/>'
                "</svg>"
            )
            ctx.mount_component(
                self._retained_svg_component(
                    component_id=f"{component.component_id}__mask_{i}",
                    svg_markup=markup,
                    x=mx,
                    y=my,
                    frame=frame,
                    width=mw,
                    height=mh,
                    opacity=1.0,
                )
            )
        self._mount_viewport_scrollbars(ctx, component, x=x, y=y, frame=frame)


    def _initialize_viewport_scroll_state(self) -> None:
        if self._ui_page is None:
            return
        state = self.state.setdefault("viewport_scroll", {})
        if not isinstance(state, dict):
            state = {}
            self.state["viewport_scroll"] = state
        for component in self._ui_page.components:
            if component.component_type != "viewport":
                continue
            style = component.style if isinstance(component.style, dict) else {}
            scroll = style.get("scroll")
            sx = 0.0
            sy = 0.0
            if isinstance(scroll, dict):
                sx = float(scroll.get("x", 0.0))
                sy = float(scroll.get("y", 0.0))
            cx, cy = self._clamp_viewport_scroll(component, sx, sy)
            state[component.component_id] = {"x": cx, "y": cy}

    def _initialize_plane_scroll_state(self) -> None:
        state = self.state.setdefault("plane_scroll", {"x": 0.0, "y": 0.0})
        if not isinstance(state, dict):
            state = {"x": 0.0, "y": 0.0}
            self.state["plane_scroll"] = state
        try:
            sx = float(state.get("x", 0.0))
            sy = float(state.get("y", 0.0))
        except (TypeError, ValueError):
            sx = 0.0
            sy = 0.0
        cx, cy = self._clamp_plane_scroll(sx, sy)
        state["x"] = cx
        state["y"] = cy

    def _plane_scroll_position(self) -> tuple[float, float]:
        state = self.state.get("plane_scroll")
        if isinstance(state, dict):
            try:
                return (float(state.get("x", 0.0)), float(state.get("y", 0.0)))
            except (TypeError, ValueError):
                return (0.0, 0.0)
        return (0.0, 0.0)

    def _clamp_plane_scroll(self, x: float, y: float) -> tuple[float, float]:
        max_x, max_y = self._plane_scroll_limits()
        cx = min(max(0.0, float(x)), max_x)
        cy = min(max(0.0, float(y)), max_y)
        return (cx, cy)

    def _plane_scroll_limits(self) -> tuple[float, float]:
        if self._ui_page is None:
            return (0.0, 0.0)
        max_x = 0.0
        max_y = 0.0
        refs = self._viewport_content_refs()
        for component in self._ui_page.components:
            if not component.visible:
                continue
            if component.component_id in refs:
                continue
            if self._is_overlay_attached(component) or self._is_camera_fixed(component):
                continue
            if not self._component_is_active(component):
                continue
            base_x, base_y = self._resolved_position_base(component)
            right = base_x + float(component.width)
            bottom = base_y + float(component.height)
            max_x = max(max_x, right - float(self._ui_page.matrix.width))
            max_y = max(max_y, bottom - float(self._ui_page.matrix.height))
        return (max_x, max_y)

    def _apply_plane_scroll_intent(self, intent: ScrollIntent) -> tuple[float, float]:
        state = self.state.setdefault("plane_scroll", {"x": 0.0, "y": 0.0})
        if not isinstance(state, dict):
            state = {"x": 0.0, "y": 0.0}
            self.state["plane_scroll"] = state
        cur_x, cur_y = self._plane_scroll_position()
        next_x = cur_x + float(intent.delta_x)
        next_y = cur_y + float(intent.delta_y)
        clamped_x, clamped_y = self._clamp_plane_scroll(next_x, next_y)
        state["x"] = clamped_x
        state["y"] = clamped_y
        return (clamped_x - cur_x, clamped_y - cur_y)

    def _mount_plane_scrollbars(self, ctx) -> None:
        if self._ui_page is None:
            return
        max_x, max_y = self._plane_scroll_limits()
        if max_x <= 1e-9 and max_y <= 1e-9:
            return
        view_w = float(self._ui_page.matrix.width)
        view_h = float(self._ui_page.matrix.height)
        scroll_x, scroll_y = self._plane_scroll_position()
        frame = self._ui_page.default_frame

        if max_x > 1e-9:
            track_h = 6.0
            track_x = 4.0
            track_y = view_h - track_h - 2.0
            track_w = max(16.0, view_w - 12.0)
            content_w = view_w + max_x
            thumb_ratio = max(0.08, min(1.0, view_w / max(content_w, 1e-9)))
            thumb_w = max(12.0, track_w * thumb_ratio)
            span = max(0.0, track_w - thumb_w)
            thumb_x = track_x + span * (scroll_x / max_x)
            self._mount_camera_overlay_scrollbar_pair(
                ctx,
                frame=frame,
                track_id="__plane_scrollbar_x_track",
                thumb_id="__plane_scrollbar_x_thumb",
                track_x=track_x,
                track_y=track_y,
                track_w=track_w,
                track_h=track_h,
                thumb_x=thumb_x,
                thumb_y=track_y,
                thumb_w=thumb_w,
                thumb_h=track_h,
                track_markup_key="page_track_h",
                thumb_markup_key="page_thumb_h",
                track_opacity=0.86,
                thumb_opacity=0.96,
            )

        if max_y > 1e-9:
            track_w = 6.0
            track_x = view_w - track_w - 2.0
            track_y = 72.0
            track_h = max(16.0, view_h - 82.0)
            content_h = view_h + max_y
            thumb_ratio = max(0.08, min(1.0, view_h / max(content_h, 1e-9)))
            thumb_h = max(12.0, track_h * thumb_ratio)
            span = max(0.0, track_h - thumb_h)
            thumb_y = track_y + span * (scroll_y / max_y)
            self._mount_camera_overlay_scrollbar_pair(
                ctx,
                frame=frame,
                track_id="__plane_scrollbar_y_track",
                thumb_id="__plane_scrollbar_y_thumb",
                track_x=track_x,
                track_y=track_y,
                track_w=track_w,
                track_h=track_h,
                thumb_x=track_x,
                thumb_y=thumb_y,
                thumb_w=track_w,
                thumb_h=thumb_h,
                track_markup_key="page_track_v",
                thumb_markup_key="page_thumb_v",
                track_opacity=0.86,
                thumb_opacity=0.96,
            )

    def _viewport_content_refs(self) -> set[str]:
        refs: set[str] = set()
        if self._ui_page is None:
            return refs
        for component in self._ui_page.components:
            if component.component_type != "viewport":
                continue
            style = component.style if isinstance(component.style, dict) else {}
            ref = style.get("content_ref")
            if isinstance(ref, str) and ref.strip():
                refs.add(ref)
        return refs

    def _viewport_scroll_position(self, viewport_component) -> tuple[float, float]:
        state = self.state.get("viewport_scroll")
        if isinstance(state, dict):
            entry = state.get(viewport_component.component_id)
            if isinstance(entry, dict):
                try:
                    return (float(entry.get("x", 0.0)), float(entry.get("y", 0.0)))
                except (TypeError, ValueError):
                    pass
        style = viewport_component.style if isinstance(viewport_component.style, dict) else {}
        scroll = style.get("scroll")
        if isinstance(scroll, dict):
            try:
                return (float(scroll.get("x", 0.0)), float(scroll.get("y", 0.0)))
            except (TypeError, ValueError):
                return (0.0, 0.0)
        return (0.0, 0.0)

    def _clamp_viewport_scroll(self, viewport_component, x: float, y: float) -> tuple[float, float]:
        style = viewport_component.style if isinstance(viewport_component.style, dict) else {}
        ref = style.get("content_ref")
        max_x = 0.0
        max_y = 0.0
        if isinstance(ref, str) and ref in self._component_index:
            content = self._component_index[ref]
            max_x = max(0.0, float(content.width) - float(viewport_component.width))
            max_y = max(0.0, float(content.height) - float(viewport_component.height))
        cx = min(max(0.0, float(x)), max_x)
        cy = min(max(0.0, float(y)), max_y)
        return (cx, cy)

    def _apply_viewport_scroll_intent(self, viewport_component, intent: ScrollIntent) -> tuple[float, float]:
        style = viewport_component.style if isinstance(viewport_component.style, dict) else {}
        speed_x = 1.0
        speed_y = 1.0
        scroll_speed = style.get("scroll_speed")
        if isinstance(scroll_speed, dict):
            try:
                speed_x = float(scroll_speed.get("x", 1.0))
                speed_y = float(scroll_speed.get("y", 1.0))
            except (TypeError, ValueError):
                speed_x = 1.0
                speed_y = 1.0
        cur_x, cur_y = self._viewport_scroll_position(viewport_component)
        next_x = cur_x + (intent.delta_x * speed_x)
        next_y = cur_y + (intent.delta_y * speed_y)
        clamped_x, clamped_y = self._clamp_viewport_scroll(viewport_component, next_x, next_y)
        state = self.state.setdefault("viewport_scroll", {})
        if not isinstance(state, dict):
            state = {}
            self.state["viewport_scroll"] = state
        state[viewport_component.component_id] = {"x": clamped_x, "y": clamped_y}
        consumed_x = (clamped_x - cur_x) / speed_x if abs(speed_x) > 1e-12 else 0.0
        consumed_y = (clamped_y - cur_y) / speed_y if abs(speed_y) > 1e-12 else 0.0
        return (consumed_x, consumed_y)

    def _mount_viewport_content(self, ctx, viewport_component, *, x: float, y: float, frame: str) -> None:
        style = viewport_component.style if isinstance(viewport_component.style, dict) else {}
        ref = style.get("content_ref")
        if not isinstance(ref, str) or ref not in self._component_index:
            return
        content = self._component_index[ref]
        scroll_x, scroll_y = self._viewport_scroll_position(viewport_component)
        content_x = x - scroll_x
        content_y = y - scroll_y
        if content.component_type == "svg":
            if content.asset is None:
                return
            svg_path = (self._plane_dir / content.asset.source).resolve()
            svg_markup = self._load_svg_markup(svg_path)
            ctx.mount_component(
                self._retained_svg_component(
                    component_id=f"{viewport_component.component_id}__content",
                    svg_markup=svg_markup,
                    x=content_x,
                    y=content_y,
                    frame=frame,
                    width=float(content.width),
                    height=float(content.height),
                    opacity=float(content.opacity),
                )
            )
            return
        if content.component_type == "viewport":
            self._mount_viewport_content(ctx, content, x=content_x, y=content_y, frame=frame)
            self._mount_viewport_scrollbars(ctx, content, x=content_x, y=content_y, frame=frame)
            return
        if content.component_type == "text":
            props = content.style if isinstance(content.style, dict) else {}
            text = str(props.get("text", content.component_id))
            color_hex = self._resolve_text_color(content.component_id, props)
            font_size_px = float(props.get("font_size_px", 14.0))
            max_width_px = props.get("max_width_px")
            if max_width_px is not None:
                max_width_px = float(max_width_px)
            ctx.mount_component(
                self._retained_text_component(
                    component_id=f"{viewport_component.component_id}__content",
                    text=text,
                    x=content_x,
                    y=content_y,
                    frame=frame,
                    font_size_px=font_size_px,
                    color_hex=color_hex,
                    opacity=float(content.opacity),
                    max_width_px=max_width_px,
                )
            )

    def _mount_viewport_scrollbars(self, ctx, viewport_component, *, x: float, y: float, frame: str) -> None:
        style = viewport_component.style if isinstance(viewport_component.style, dict) else {}
        ref = style.get("content_ref")
        if not isinstance(ref, str) or ref not in self._component_index:
            return
        content = self._component_index[ref]
        view_w = float(viewport_component.width)
        view_h = float(viewport_component.height)
        content_w = float(content.width)
        content_h = float(content.height)
        if view_w <= 0 or view_h <= 0:
            return
        scroll_x, scroll_y = self._viewport_scroll_position(viewport_component)

        if content_w > view_w + 1e-9:
            track_h = 5.0
            track_y = y + view_h - track_h - 2.0
            track_x = x + 2.0
            track_w = max(8.0, view_w - 4.0)
            thumb_ratio = max(0.08, min(1.0, view_w / content_w))
            thumb_w = max(10.0, track_w * thumb_ratio)
            max_scroll_x = max(1e-9, content_w - view_w)
            span = max(0.0, track_w - thumb_w)
            thumb_x = track_x + span * (scroll_x / max_scroll_x)
            self._mount_camera_overlay_scrollbar_pair(
                ctx,
                frame=frame,
                track_id=f"{viewport_component.component_id}__scrollbar_x_track",
                thumb_id=f"{viewport_component.component_id}__scrollbar_x_thumb",
                track_x=track_x,
                track_y=track_y,
                track_w=track_w,
                track_h=track_h,
                thumb_x=thumb_x,
                thumb_y=track_y,
                thumb_w=thumb_w,
                thumb_h=track_h,
                track_markup_key="viewport_track_h",
                thumb_markup_key="viewport_thumb_h",
                track_opacity=0.82,
                thumb_opacity=0.95,
            )

        if content_h > view_h + 1e-9:
            track_w = 5.0
            track_x = x + view_w - track_w - 2.0
            track_y = y + 2.0
            track_h = max(8.0, view_h - 4.0)
            thumb_ratio = max(0.08, min(1.0, view_h / content_h))
            thumb_h = max(10.0, track_h * thumb_ratio)
            max_scroll_y = max(1e-9, content_h - view_h)
            span = max(0.0, track_h - thumb_h)
            thumb_y = track_y + span * (scroll_y / max_scroll_y)
            self._mount_camera_overlay_scrollbar_pair(
                ctx,
                frame=frame,
                track_id=f"{viewport_component.component_id}__scrollbar_y_track",
                thumb_id=f"{viewport_component.component_id}__scrollbar_y_thumb",
                track_x=track_x,
                track_y=track_y,
                track_w=track_w,
                track_h=track_h,
                thumb_x=track_x,
                thumb_y=thumb_y,
                thumb_w=track_w,
                thumb_h=thumb_h,
                track_markup_key="viewport_track_v",
                thumb_markup_key="viewport_thumb_v",
                track_opacity=0.82,
                thumb_opacity=0.95,
            )


def load_plane_app(
    plane_path: str | Path,
    *,
    handlers: dict[str, EventHandler] | None = None,
    strict: bool = True,
) -> PlaneApp:
    return PlaneApp(plane_path, handlers=handlers, strict=strict)


def _hook_for_event(event_type: str, payload: object) -> str | None:
    if event_type == "press" and isinstance(payload, dict):
        phase = payload.get("phase")
        phase_map = {
            "down": "on_press_down",
            "repeat": "on_press_repeat",
            "hold_start": "on_press_hold_start",
            "hold_tick": "on_press_hold_tick",
            "up": "on_press_up",
            "hold_end": "on_press_hold_end",
            "single": "on_press_single",
            "double": "on_press_double",
            "cancel": "on_press_cancel",
        }
        if phase in phase_map:
            return phase_map[phase]
    if event_type == "click":
        return "on_press_single"
    if event_type == "pointer_move":
        return "on_hover_start"
    if event_type == "scroll":
        return "on_scroll"
    if event_type == "pinch":
        return "on_pinch"
    if event_type == "rotate":
        return "on_rotate"
    return None


def _scroll_intent_from_event(event_type: str, payload: dict[str, Any], device: str | None = None) -> ScrollIntent | None:
    if event_type == "scroll":
        try:
            dx = float(payload.get("delta_x", 0.0))
            dy = float(payload.get("delta_y", 0.0))
        except (TypeError, ValueError):
            return None
        phase = str(payload.get("phase", "update"))
        momentum_phase = payload.get("momentum_phase")
        momentum = str(momentum_phase) if isinstance(momentum_phase, str) and momentum_phase else None
        source = "trackpad" if (str(device or "").lower() == "trackpad" or bool(payload.get("precise", False))) else "wheel"
        # Match system-native scroll direction expectations by treating positive
        # wheel deltas as moving the viewport camera in the opposite direction.
        return ScrollIntent(delta_x=-dx, delta_y=-dy, source=source, phase=phase, momentum_phase=momentum)
    if event_type in {"pan", "swipe"}:
        try:
            dx = float(payload.get("delta_x", 0.0))
            dy = float(payload.get("delta_y", 0.0))
        except (TypeError, ValueError):
            return None
        phase = str(payload.get("phase", "update"))
        momentum_phase = payload.get("momentum_phase")
        momentum = str(momentum_phase) if isinstance(momentum_phase, str) and momentum_phase else None
        return ScrollIntent(delta_x=-dx, delta_y=-dy, source="touch_drag", phase=phase, momentum_phase=momentum)
    return None


def resolve_planes_v2_rollout_flags() -> PlanesV2RolloutFlags:
    rollback = _env_flag("LUVATRIX_PLANES_V2_ROLLBACK_COMPAT_ADAPTER_DEFAULT", default=False)
    if rollback:
        return PlanesV2RolloutFlags(
            schema_enabled=False,
            compiler_enabled=False,
            runtime_enabled=False,
            rollback_to_compat_adapter_default=True,
        )
    return PlanesV2RolloutFlags(
        schema_enabled=_env_flag("LUVATRIX_PLANES_V2_SCHEMA", default=True),
        compiler_enabled=_env_flag("LUVATRIX_PLANES_V2_COMPILER", default=True),
        runtime_enabled=_env_flag("LUVATRIX_PLANES_V2_RUNTIME", default=True),
        rollback_to_compat_adapter_default=False,
    )


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _env_int(name: str, *, default: int, min_value: int, max_value: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    try:
        value = int(raw.strip())
    except ValueError:
        return int(default)
    return max(int(min_value), min(int(max_value), int(value)))


def _event_id_digest(event_ids: list[int]) -> str:
    h = 1469598103934665603
    for event_id in event_ids:
        h ^= int(event_id) & 0xFFFFFFFFFFFFFFFF
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def _parse_hex_rgba(value: str) -> tuple[int, int, int, int]:
    raw = value.strip()
    if not raw.startswith("#"):
        raise ValueError(f"invalid color: {value}")
    h = raw[1:]
    if len(h) == 6:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
    if len(h) == 8:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
    raise ValueError(f"invalid color: {value}")


def _rgba_to_hex(value: tuple[int, int, int, int]) -> str:
    return f"#{value[0]:02x}{value[1]:02x}{value[2]:02x}"
