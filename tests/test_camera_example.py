from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
import unittest

import torch

from luvatrix_core.core.app_runtime import AppRuntime
from luvatrix_core.core.hdi_thread import HDIEvent, HDIEventSource, HDIThread
from luvatrix_core.core.sensor_manager import SensorManagerThread, SensorSample
from luvatrix_core.core.window_matrix import WindowMatrix


APP_DIR = Path(__file__).resolve().parents[1] / "examples" / "camera"
MODULE_PATH = APP_DIR / "app_main.py"
SPEC = importlib.util.spec_from_file_location("camera_app_main", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"failed to load module spec for {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

CameraLabApp = MODULE.CameraLabApp
TouchButton = MODULE.TouchButton
format_camera_status_lines = MODULE.format_camera_status_lines
format_camera_compact_status_lines = MODULE.format_camera_compact_status_lines
format_camera_collapsed_status_lines = MODULE.format_camera_collapsed_status_lines
planned_camera_mode_statuses = MODULE.planned_camera_mode_statuses


class _NoopHDISource(HDIEventSource):
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        _ = (window_active, ts_ns)
        return []


class _CameraProvider:
    def read(self) -> tuple[object, str]:
        return {"permission": "granted", "bridge": "pending"}, "metadata"


@dataclass
class _FakeWriteEvent:
    revision: int = 1


class _FakeCtx:
    def __init__(self, width: int, height: int, sample: SensorSample) -> None:
        self._snapshot = torch.zeros((height, width, 4), dtype=torch.uint8)
        self._sample = sample
        self.last_frame: torch.Tensor | None = None

    def read_matrix_snapshot(self) -> torch.Tensor:
        return self._snapshot

    def poll_hdi_events(self, max_events: int, frame: str | None = None) -> list[HDIEvent]:
        _ = (max_events, frame)
        return []

    def read_sensor(self, sensor_type: str) -> SensorSample:
        return SensorSample(
            sample_id=self._sample.sample_id,
            ts_ns=self._sample.ts_ns,
            sensor_type=sensor_type,
            status=self._sample.status,
            value=self._sample.value,
            unit=self._sample.unit,
        )

    def submit_write_batch(self, batch) -> _FakeWriteEvent:
        op = batch.operations[0]
        self.last_frame = op.tensor_h_w_4.clone()
        return _FakeWriteEvent()


class CameraExampleTests(unittest.TestCase):
    def test_manifest_loads_android_camera_scaffold(self) -> None:
        runtime = AppRuntime(
            matrix=WindowMatrix(height=1, width=1),
            hdi=HDIThread(source=_NoopHDISource()),
            sensor_manager=SensorManagerThread(providers={}),
            host_os="android",
        )

        manifest = runtime.load_manifest(APP_DIR)

        self.assertEqual(manifest.app_id, "examples.camera")
        self.assertEqual(manifest.platform_support, ["android"])
        self.assertIn("window.write", manifest.required_capabilities)
        self.assertIn("sensor.camera", manifest.optional_capabilities)
        self.assertIn("sensor.display", manifest.optional_capabilities)
        self.assertEqual(manifest.display_native_width, 393)
        self.assertEqual(manifest.display_native_height, 852)

    def test_app_runs_headlessly_and_writes_non_uniform_frames(self) -> None:
        matrix = WindowMatrix(height=96, width=54)
        runtime = AppRuntime(
            matrix=matrix,
            hdi=HDIThread(source=_NoopHDISource()),
            sensor_manager=SensorManagerThread(providers={"camera.permission": _CameraProvider()}),
            capability_decider=lambda capability: True,
            host_os="android",
        )

        runtime.run(APP_DIR, max_ticks=3, target_fps=120)

        self.assertEqual(matrix.revision, 3)
        frame = matrix.read_snapshot()
        self.assertEqual(tuple(frame.shape), (96, 54, 4))
        self.assertGreater(float(frame[:, :, :3].float().std().item()), 0.0)

    def test_missing_camera_provider_renders_bridge_pending_without_crash(self) -> None:
        sample = SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type="camera.permission",
            status="UNAVAILABLE",
            value=None,
            unit=None,
        )
        app = CameraLabApp()
        ctx = _FakeCtx(width=180, height=120, sample=sample)

        app.init(ctx)
        app.loop(ctx, dt=0.0)

        self.assertIsNotNone(ctx.last_frame)
        assert ctx.last_frame is not None
        self.assertEqual(tuple(ctx.last_frame.shape), (120, 180, 4))
        lines = format_camera_status_lines(app._last_samples)
        self.assertTrue(any("UNAVAILABLE" in line for line in lines))

    def test_helper_formatting_names_yuv_and_raw_modes(self) -> None:
        statuses = planned_camera_mode_statuses()
        lines = format_camera_status_lines([])
        text = "\n".join(lines + [status.name for status in statuses])

        self.assertIn("YUV_420_888 live preview", text)
        self.assertIn("RAW_SENSOR capture", text)
        self.assertNotIn("bridge pending", "\n".join(lines))

    def test_helper_formatting_summarizes_dual_camera_telemetry(self) -> None:
        sample = SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type="camera.device",
            status="OK",
            value={
                "mode": "dual",
                "dual_supported": True,
                "dual_active": True,
                "active_camera_ids": ["0", "2"],
                "streams": {
                    "primary": {
                        "width": 1920,
                        "height": 1080,
                    },
                },
                "inventory": {
                    "hidden_camera_probes": [
                        {
                            "camera_id": "2",
                            "status": "characteristics_ok",
                            "facing": "back",
                            "color_filter_arrangement": "MONO",
                            "monochrome_supported": True,
                            "yuv_420_888_sizes": [{"width": 1600, "height": 1200}],
                        }
                    ],
                    "cameras": [
                        {
                            "camera_id": "0",
                            "facing": "back",
                            "is_logical_multi_camera": True,
                            "physical_camera_ids": ["0a", "0b"],
                            "physical_camera_details": [
                                {
                                    "camera_id": "0a",
                                    "color_filter_arrangement": "RGGB",
                                    "focal_lengths_mm": [4.2],
                                },
                                {
                                    "camera_id": "0b",
                                    "color_filter_arrangement": "MONO",
                                    "monochrome_supported": True,
                                    "focal_lengths_mm": [2.1],
                                },
                            ],
                        },
                        {"camera_id": "2", "facing": "back"},
                    ],
                },
            },
            unit="metadata",
        )

        text = "\n".join(format_camera_status_lines([sample]))

        self.assertIn("rear cameras: 2", text)
        self.assertIn("rear 0: logical physical=2", text)
        self.assertIn("physical 0b: MONO mono focal=2.1mm", text)
        self.assertIn("hidden rear sensor: MONO exposed", text)
        self.assertIn("hidden id 2: back MONO mono yuv=1600x1200", text)
        self.assertIn("active=0,2", text)
        self.assertIn("dual preview: supported active", text)
        self.assertIn("primary YUV matrix: 1920x1080", text)

    def test_touch_buttons_route_to_camera_bridge_commands(self) -> None:
        app = CameraLabApp()
        app._buttons = [
            TouchButton("cycle_primary", "switch camera", 0.0, 0.0, 100.0, 60.0),
            TouchButton("toggle_dual", "dual preview", 120.0, 0.0, 220.0, 60.0),
        ]
        app._last_samples = [
            SensorSample(
                sample_id=1,
                ts_ns=1,
                sensor_type="camera.device",
                status="OK",
                value={
                    "camera_id": "0",
                    "primary_camera_id": "0",
                    "dual_supported": True,
                    "dual_active": False,
                    "inventory": {
                        "cameras": [
                            {"camera_id": "0", "facing": "back"},
                            {"camera_id": "2", "facing": "back"},
                        ],
                    },
                },
                unit="metadata",
            )
        ]
        calls: list[tuple[str, object]] = []
        old_primary = MODULE._android_set_primary_camera
        old_dual = MODULE._android_set_dual_preview_enabled
        old_quality = MODULE._android_set_preview_quality_mode
        old_target = MODULE._android_set_preview_target_mode
        old_sharpness = MODULE._android_set_preview_sharpness_mode
        old_layers = MODULE._android_set_preview_convolution_layers
        old_pipeline = MODULE._android_set_preview_pipeline_mode
        old_refresh = MODULE._android_set_refresh_hint_mode
        MODULE._android_set_primary_camera = lambda camera_id: calls.append(("primary", camera_id))
        MODULE._android_set_dual_preview_enabled = lambda enabled: calls.append(("dual", enabled))
        MODULE._android_set_preview_quality_mode = lambda mode: calls.append(("quality", mode))
        MODULE._android_set_preview_target_mode = lambda mode: calls.append(("target", mode))
        MODULE._android_set_preview_sharpness_mode = lambda mode: calls.append(("sharpness", mode))
        MODULE._android_set_preview_convolution_layers = lambda layers: calls.append(("layers", layers))
        MODULE._android_set_preview_pipeline_mode = lambda mode: calls.append(("pipeline", mode))
        MODULE._android_set_refresh_hint_mode = lambda mode: calls.append(("refresh", mode))
        try:
            app._handle_touch_action(50.0, 30.0)
            app._handle_touch_action(150.0, 30.0)
            app._buttons = [TouchButton("cycle_preview_quality", "qual", 0.0, 0.0, 100.0, 60.0)]
            app._last_samples[0].value["preview_quality"] = "max"
            app._handle_touch_action(50.0, 30.0)
            app._handle_touch_action(50.0, 30.0)
            app._buttons = [TouchButton("cycle_preview_target", "target", 0.0, 0.0, 100.0, 60.0)]
            app._handle_touch_action(50.0, 30.0)
            app._handle_touch_action(50.0, 30.0)
            app._buttons = [TouchButton("cycle_preview_sharpness", "sharp", 0.0, 0.0, 100.0, 60.0)]
            app._handle_touch_action(50.0, 30.0)
            app._handle_touch_action(50.0, 30.0)
            app._buttons = [TouchButton("cycle_preview_convolution_layers", "layer", 0.0, 0.0, 100.0, 60.0)]
            app._handle_touch_action(50.0, 30.0)
            app._handle_touch_action(50.0, 30.0)
            app._buttons = [TouchButton("cycle_preview_pipeline", "pipe", 0.0, 0.0, 100.0, 60.0)]
            app._handle_touch_action(50.0, 30.0)
            app._handle_touch_action(50.0, 30.0)
            app._buttons = [TouchButton("cycle_refresh_hint", "Hz", 0.0, 0.0, 100.0, 60.0)]
            app._handle_touch_action(50.0, 30.0)
            app._handle_touch_action(50.0, 30.0)
        finally:
            MODULE._android_set_primary_camera = old_primary
            MODULE._android_set_dual_preview_enabled = old_dual
            MODULE._android_set_preview_quality_mode = old_quality
            MODULE._android_set_preview_target_mode = old_target
            MODULE._android_set_preview_sharpness_mode = old_sharpness
            MODULE._android_set_preview_convolution_layers = old_layers
            MODULE._android_set_preview_pipeline_mode = old_pipeline
            MODULE._android_set_refresh_hint_mode = old_refresh

        self.assertEqual(
            calls,
            [
                ("primary", "2"),
                ("dual", True),
                ("quality", "balanced"),
                ("quality", "fast"),
                ("target", "solo"),
                ("target", "full"),
                ("sharpness", "clean"),
                ("sharpness", "lowlight"),
                ("layers", 1),
                ("layers", 2),
                ("pipeline", "preview"),
                ("pipeline", "record"),
                ("refresh", "120"),
                ("refresh", "highest"),
            ],
        )

    def test_buttons_do_not_restart_when_only_one_rear_or_dual_unsupported(self) -> None:
        app = CameraLabApp()
        app._buttons = [
            TouchButton("cycle_primary", "switch camera", 0.0, 0.0, 100.0, 60.0),
            TouchButton("toggle_dual", "dual preview", 120.0, 0.0, 220.0, 60.0),
        ]
        app._last_samples = [
            SensorSample(
                sample_id=1,
                ts_ns=1,
                sensor_type="camera.device",
                status="OK",
                value={
                    "camera_id": "0",
                    "primary_camera_id": "0",
                    "dual_supported": False,
                    "dual_active": False,
                    "inventory": {
                        "cameras": [
                            {"camera_id": "0", "facing": "back"},
                            {"camera_id": "1", "facing": "front"},
                        ],
                    },
                },
                unit="metadata",
            )
        ]
        calls: list[tuple[str, object]] = []
        old_primary = MODULE._android_set_primary_camera
        old_dual = MODULE._android_set_dual_preview_enabled
        MODULE._android_set_primary_camera = lambda camera_id: calls.append(("primary", camera_id))
        MODULE._android_set_dual_preview_enabled = lambda enabled: calls.append(("dual", enabled))
        try:
            app._handle_touch_action(50.0, 30.0)
            self.assertEqual(app._last_action_status, "no alternate rear camera exposed")
            app._handle_touch_action(150.0, 30.0)
            self.assertEqual(app._last_action_status, "dual preview unsupported by Camera2")
        finally:
            MODULE._android_set_primary_camera = old_primary
            MODULE._android_set_dual_preview_enabled = old_dual

        self.assertEqual(calls, [])

    def test_single_rear_physical_zero_reports_hidden_sensor_not_exposed(self) -> None:
        sample = SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type="camera.device",
            status="OK",
            value={
                "status": "running",
                "permission": "granted",
                "device_count": 2,
                "mode": "single",
                "dual_supported": False,
                "dual_active": False,
                "active_camera_ids": ["0"],
                "inventory": {
                    "cameras": [
                        {
                            "camera_id": "0",
                            "facing": "back",
                            "is_logical_multi_camera": False,
                            "physical_camera_ids": [],
                            "physical_camera_details": [],
                        },
                        {"camera_id": "1", "facing": "front"},
                    ],
                },
            },
            unit="metadata",
        )

        text = "\n".join(format_camera_status_lines([sample]))

        self.assertIn("camera.device: OK status=running permission=granted devices=2", text)
        self.assertIn("rear 0: single physical=0", text)
        self.assertIn("hidden rear sensor: not exposed by Camera2", text)

    def test_hidden_probe_failures_are_summarized(self) -> None:
        sample = SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type="camera.device",
            status="OK",
            value={
                "inventory": {
                    "hidden_camera_probes": [
                        {"camera_id": "2", "status": "characteristics_failed"},
                        {"camera_id": "3", "status": "characteristics_failed"},
                    ],
                    "cameras": [
                        {"camera_id": "0", "facing": "back"},
                    ],
                },
            },
            unit="metadata",
        )

        text = "\n".join(format_camera_status_lines([sample]))

        self.assertIn("hidden id probes: 2 blocked", text)

    def test_resolution_probe_reports_public_108mp_candidate(self) -> None:
        sample = SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type="camera.device",
            status="OK",
            value={
                "inventory": {
                    "cameras": [
                        {
                            "camera_id": "0",
                            "facing": "back",
                            "resolution_probe": {
                                "standard": {
                                    "jpeg": [{"width": 4000, "height": 3000, "megapixels": 12.0}],
                                },
                                "maximum_resolution": {
                                    "supported": True,
                                    "jpeg": [{"width": 12000, "height": 9000, "megapixels": 108.0}],
                                },
                                "public_108mp_candidate": True,
                                "raw_public_supported": True,
                            },
                        }
                    ],
                },
            },
            unit="metadata",
        )

        text = "\n".join(format_camera_status_lines([sample]))

        self.assertIn("best still: std 4000x3000 | maxres 12000x9000", text)
        self.assertIn("108MP public path: yes", text)
        self.assertIn("RAW public: yes", text)

    def test_resolution_probe_reports_no_maxres_candidate(self) -> None:
        sample = SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type="camera.device",
            status="OK",
            value={
                "inventory": {
                    "cameras": [
                        {
                            "camera_id": "0",
                            "facing": "back",
                            "resolution_probe": {
                                "standard": {
                                    "jpeg": [{"width": 4000, "height": 3000, "megapixels": 12.0}],
                                },
                                "maximum_resolution": {
                                    "supported": False,
                                    "jpeg": [],
                                },
                                "public_108mp_candidate": False,
                                "raw_public_supported": False,
                            },
                        }
                    ],
                },
            },
            unit="metadata",
        )

        text = "\n".join(format_camera_status_lines([sample]))

        self.assertIn("best still: std 4000x3000 | maxres none", text)
        self.assertIn("108MP public path: no", text)
        self.assertIn("RAW public: no", text)

    def test_probe_summary_reports_partial_no_distinctly(self) -> None:
        sample = SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type="camera.device",
            status="OK",
            value={
                "inventory": {
                    "probe_summary": {
                        "public_108mp_verdict": "no_partial",
                        "probe_status": "partial",
                        "raw_public_supported": True,
                        "largest_public_still": {"width": 3840, "height": 2160, "megapixels": 8.29},
                        "largest_public_any": {"width": 8000, "height": 6000, "megapixels": 48.0},
                    },
                    "cameras": [
                        {"camera_id": "0", "facing": "back"},
                    ],
                },
            },
            unit="metadata",
        )

        text = "\n".join(format_camera_status_lines([sample]))

        self.assertIn("best still: 3840x2160", text)
        self.assertIn("largest any: 8000x6000", text)
        self.assertIn("108MP public path: no_partial", text)
        self.assertIn("probe confidence: partial", text)
        self.assertIn("RAW public: yes", text)

    def test_probe_summary_reports_failed_as_unknown(self) -> None:
        sample = SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type="camera.device",
            status="OK",
            value={
                "inventory": {
                    "probe_summary": {
                        "public_108mp_verdict": "unknown_failed",
                        "probe_status": "failed",
                        "raw_public_supported": False,
                    },
                    "cameras": [
                        {"camera_id": "0", "facing": "back"},
                    ],
                },
            },
            unit="metadata",
        )

        text = "\n".join(format_camera_status_lines([sample]))

        self.assertIn("best still: none", text)
        self.assertIn("largest any: none", text)
        self.assertIn("108MP public path: unknown", text)
        self.assertIn("probe confidence: failed", text)

    def test_display_refresh_telemetry_is_formatted_with_camera_fps(self) -> None:
        samples = [
            SensorSample(
                sample_id=1,
                ts_ns=1,
                sensor_type="camera.device",
                status="OK",
                value={
                    "streams": {"primary": {"fps_estimate": 29.85}},
                    "inventory": {"cameras": [{"camera_id": "0", "facing": "back"}]},
                },
                unit="metadata",
            ),
            SensorSample(
                sample_id=2,
                ts_ns=1,
                sensor_type="display.refresh",
                status="OK",
                value={
                    "supported_modes": [
                        {"refresh_hz": 60.0},
                        {"refresh_hz": 120.0},
                    ],
                    "requested_refresh_hz": 120.0,
                    "selected_mode_hz": 120.0,
                    "actual_refresh_hz": 60.0,
                    "surface_frame_rate_hz": 120.0,
                    "refresh_hint_mode": "120",
                    "honored": False,
                },
                unit="metadata",
            ),
        ]

        text = "\n".join(format_camera_status_lines(samples))

        self.assertIn("display.refresh: OK request=120 actual=60", text)
        self.assertIn("display modes: 60,120", text)
        self.assertIn("refresh: req120 mode120 actual60 hint120 120", text)
        self.assertIn("refresh request: 120", text)
        self.assertIn("refresh actual: 60 clamped", text)
        self.assertIn("camera fps: 29.9", text)

    def test_raw_capture_telemetry_is_formatted(self) -> None:
        sample = SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type="camera.device",
            status="OK",
            value={
                "raw_capture": {
                    "status": "saved",
                    "raw_supported": True,
                    "width": 4000,
                    "height": 3000,
                    "sensor_orientation_degrees": 90,
                    "display_rotation_degrees": 0,
                    "raw_to_display_rotation_degrees": 90,
                    "lens_focal_length_mm": 5.4,
                    "lens_aperture": 1.8,
                    "preview_png_path": "/data/user/0/com.luvatrix.app/files/raw/camera_raw_1_preview.png",
                    "preview_export_status": "saved",
                    "preview_export_error": "",
                    "last_dng_path": "/data/user/0/com.luvatrix.app/files/raw/camera_raw_1.dng",
                    "last_error": "",
                },
                "inventory": {"cameras": [{"camera_id": "0", "facing": "back"}]},
            },
            unit="metadata",
        )

        text = "\n".join(format_camera_status_lines([sample]))

        self.assertIn("RAW capture: saved", text)
        self.assertIn("RAW size: 4000x3000", text)
        self.assertIn("RAW orientation: sensor 90 display 0 rotate 90", text)
        self.assertIn("RAW lens: 5.4mm f/1.8", text)
        self.assertIn("preview: camera_raw_1_preview.png", text)
        self.assertIn("saved: camera_raw_1.dng", text)

    def test_compact_hud_omits_debug_inventory_by_default(self) -> None:
        sample = SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type="camera.device",
            status="OK",
            value={
                "mode": "single",
                "camera_id": "0",
                "active_camera_ids": ["0"],
                "raw_controls": {
                    "mode": "manual",
                    "requested_iso": 800,
                    "requested_shutter_ns": 33_333_333,
                    "requested_focus_distance_diopters": 2.0,
                },
                "preview_controls": {
                    "mode": "manual",
                    "requested_iso": 800,
                    "requested_shutter_ns": 33_333_333,
                    "requested_focus_distance_diopters": 2.0,
                    "actual_iso": 790,
                    "actual_exposure_time_ns": 33_333_333,
                },
                "raw_capture": {
                    "status": "ready",
                    "raw_supported": True,
                    "width": 4000,
                    "height": 3000,
                },
                "preview_renderer": "cpu_yuv_bilinear",
                "preview_gpu_ready": False,
                "inventory": {"cameras": [{"camera_id": "0", "facing": "back"}]},
            },
            unit="metadata",
        )

        text = "\n".join(format_camera_compact_status_lines([sample], action_status="ready"))

        self.assertIn("manual=manual", text)
        self.assertIn("iso req=800 actual=790", text)
        self.assertIn("shutter req=1/30 actual=1/30", text)
        self.assertIn("focus req=2.0d", text)
        self.assertNotIn("preview:", text)
        self.assertNotIn("raw:", text)
        self.assertNotIn("rear cameras:", text)
        self.assertNotIn("hidden rear sensor:", text)

    def test_compact_hud_formats_gpu_private_preview(self) -> None:
        sample = SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type="camera.device",
            status="OK",
            value={
                "mode": "single",
                "camera_id": "0",
                "active_camera_ids": ["0"],
                "preview_renderer": "gpu_private_vulkan",
                "preview_gpu_ready": True,
                "preview_quality": "max",
                "preview_target_mode": "raw",
                "preview_pipeline_mode": "preview",
                "private_preview": {
                    "status": "running",
                    "width": 2560,
                    "height": 1440,
                    "selected_width": 2560,
                    "selected_height": 1440,
                    "active_targets": ["private_preview", "raw_sensor"],
                    "attempt_index": 0,
                    "attempt_count": 3,
                    "frames": 9,
                    "dropped_frames": 0,
                    "fps_estimate": 28.6,
                },
                "gpu_preview": {
                    "status": "running",
                    "import_fps": 28.2,
                    "draw_fps": 119.6,
                    "last_draw_ms": 4.7,
                    "last_import_ms": 2.4,
                    "overlay_uploads": 3,
                    "overlay_cache_hits": 11,
                    "queue_waits": 8,
                    "import_cache_hits": 24,
                    "import_cache_misses": 5,
                    "import_cache_entries": 3,
                    "import_cache_evictions": 1,
                    "last_import_cache_hit": True,
                    "intermediate_width": 1280,
                    "intermediate_height": 720,
                    "intermediate_updates": 7,
                    "intermediate_reuses": 19,
                    "last_intermediate_ms": 1.8,
                    "downsample_filter": "natural",
                    "filter_preset": "natural",
                    "downsample_taps": 5,
                    "filter_taps": 5,
                    "downsample_strength": 0.15,
                    "luma_smoothing": 0.08,
                    "chroma_smoothing": 0.55,
                    "edge_preserve": 0.65,
                    "convolution_layers": 2,
                    "crop_fit_blend": 0.5,
                    "color_mode": "neutral",
                    "red_gain": 1.06,
                    "green_gain": 1.0,
                    "blue_gain": 0.94,
                    "last_downsample_ms": 1.8,
                    "last_filter_ms": 1.8,
                    "frames_in_flight": 2,
                    "frame_fence_waits": 12,
                    "image_fence_waits": 3,
                },
            },
            unit="metadata",
        )

        text = "\n".join(format_camera_compact_status_lines([sample]))

        self.assertIn("quality=max", text)
        self.assertIn("target=raw", text)
        self.assertIn("pipeline=preview", text)
        self.assertIn("layer=2 fit=0.50", text)
        self.assertIn("sharp=natural taps=5 luma=0.08 chroma=0.55 edge=0.65 str=0.15", text)
        self.assertIn("wb=neutral rgb=1.06/1.00/0.94", text)
        self.assertIn("manual=unknown", text)
        self.assertNotIn("preview:", text)
        self.assertNotIn("perf:", text)

    def test_collapsed_hud_uses_short_top_bar_lines(self) -> None:
        sample = SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type="camera.device",
            status="OK",
            value={
                "preview_renderer": "gpu_private_vulkan",
                "preview_gpu_ready": True,
                "preview_quality": "max",
                "preview_target_mode": "raw",
                "preview_pipeline_mode": "hq",
                "private_preview": {"width": 2560, "height": 1440, "fps_estimate": 28.6},
                "gpu_preview": {"import_fps": 28.2, "draw_fps": 60.0, "last_draw_ms": 4.7},
                "raw_capture": {"status": "ready", "raw_supported": True},
            },
            unit="metadata",
        )
        display = SensorSample(
            sample_id=2,
            ts_ns=1,
            sensor_type="display.refresh",
            status="OK",
            value={"refresh_hint_mode": "60", "actual_refresh_hz": 60.0},
            unit="metadata",
        )

        text = "\n".join(format_camera_collapsed_status_lines([sample, display], action_status="ready"))

        self.assertIn("quality=max", text)
        self.assertIn("target=raw", text)
        self.assertIn("pipeline=hq", text)
        self.assertIn("manual=unknown", text)
        self.assertNotIn("preview:", text)
        self.assertNotIn("fps:", text)
        self.assertNotIn("raw:", text)
        self.assertNotIn("perf3:", text)
        self.assertNotIn("perf4:", text)

    def test_full_diagnostics_include_gpu_preview_counters(self) -> None:
        sample = SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type="camera.device",
            status="OK",
            value={
                "mode": "single",
                "camera_id": "0",
                "active_camera_ids": ["0"],
                "preview_renderer": "gpu_private_vulkan",
                "preview_gpu_ready": True,
                "preview_quality": "balanced",
                "preview_target_mode": "raw",
                "preview_pipeline_mode": "hq",
                "preview_pipeline": {
                    "mode": "hq",
                    "template": "preview",
                    "applied_options": ["edge_high_quality", "nr_high_quality"],
                    "errors": [],
                },
                "private_preview": {
                    "status": "running",
                    "width": 2560,
                    "height": 1440,
                    "preset": "balanced",
                    "selected_width": 2560,
                    "selected_height": 1440,
                    "candidate_count": 4,
                    "target_mode": "raw",
                    "active_target_mode": "raw",
                    "attempt_index": 1,
                    "attempt_count": 7,
                    "active_targets": ["private_preview", "raw_sensor"],
                    "last_good_combo": {
                        "quality": "balanced",
                        "width": 2560,
                        "height": 1440,
                        "include_yuv_cache": False,
                        "include_raw_sensor": True,
                    },
                    "yuv_cache_width": 1920,
                    "yuv_cache_height": 1080,
                    "fps_estimate": 28.6,
                    "failed_attempts": [
                        {"width": 4000, "height": 3000, "reason": "session configure failed"},
                    ],
                },
                "gpu_preview": {
                    "status": "running",
                    "imports": 2,
                    "draws": 17,
                    "failures": 0,
                    "import_fps": 28.2,
                    "draw_fps": 119.6,
                    "last_draw_ms": 4.7,
                    "last_import_ms": 2.4,
                    "queue_waits": 8,
                    "overlay_uploads": 3,
                    "overlay_cache_hits": 11,
                    "imports_on_render_thread": 2,
                    "import_cache_hits": 24,
                    "import_cache_misses": 5,
                    "import_cache_entries": 3,
                    "import_cache_evictions": 1,
                    "last_import_cache_hit": True,
                    "intermediate_enabled": True,
                    "intermediate_width": 1280,
                    "intermediate_height": 720,
                    "intermediate_updates": 7,
                    "intermediate_reuses": 19,
                    "last_intermediate_ms": 1.8,
                    "downsample_filter": "natural",
                    "filter_preset": "natural",
                    "downsample_taps": 5,
                    "filter_taps": 5,
                    "downsample_strength": 0.15,
                    "luma_smoothing": 0.08,
                    "chroma_smoothing": 0.55,
                    "edge_preserve": 0.65,
                    "color_mode": "auto",
                    "red_gain": 1.0,
                    "green_gain": 1.0,
                    "blue_gain": 1.0,
                    "last_downsample_ms": 1.8,
                    "last_filter_ms": 1.8,
                    "frames_in_flight": 2,
                    "current_frame_slot": 1,
                    "frame_fence_waits": 12,
                    "image_fence_waits": 3,
                    "acquired_image_index": 2,
                    "sync_mode": "frames_in_flight",
                },
                "inventory": {"cameras": [{"camera_id": "0", "facing": "back"}]},
            },
            unit="metadata",
        )

        text = "\n".join(format_camera_status_lines([sample]))

        self.assertIn("preview: gpu private 2560x1440", text)
        self.assertIn(
            "preview diag: preset=balanced | selected=2560x1440 | private candidates=4 | target=raw | attempt=2/7 | targets=private_preview+raw_sensor | yuv cache=1920x1080 | private fps=28.6",
            text,
        )
        self.assertIn("last good: balanced 2560x1440 noyuv+raw", text)
        self.assertIn("perf2: sel 2560x1440 private+raw a2/7", text)
        self.assertIn("perf3: d119.6 i2.4ms m7/19 1.8ms", text)
        self.assertIn("filter: natural taps=5 luma=0.08 chroma=0.55 edge=0.65 str=0.15 1.8ms", text)
        self.assertIn("perf4: cH24/5/3e1 o3/11 w8 f2 fw12 iw3", text)
        self.assertIn("private failed: 4000x3000 session configure failed", text)
        self.assertIn("pipeline: mode=hq | template=preview | applied=edge_high_quality,nr_high_quality", text)
        self.assertIn("gpu preview: running imports=2 draws=17 failures=0 imp=28.2 draw=119.6 4.7ms import=2.4ms uploads=3 hits=11 waits=8 rt_imports=2 mid=1280x720 mid_updates=7 mid_reuses=19 mid=1.8ms filter=natural taps=5 luma=0.08 chroma=0.55 edge=0.65 down=1.8ms frames=2 slot=1 img=2 fw=12 iw=3 sync=frames_in_flight", text)

    def test_compact_hud_formats_private_preview_fallback(self) -> None:
        sample = SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type="camera.device",
            status="OK",
            value={
                "mode": "single",
                "camera_id": "0",
                "active_camera_ids": ["0"],
                "preview_renderer": "fallback_cpu_yuv",
                "preview_gpu_ready": False,
                "private_preview": {
                    "status": "fallback",
                    "width": 1920,
                    "height": 1080,
                    "last_error": "native import unavailable",
                },
            },
            unit="metadata",
        )

        text = "\n".join(format_camera_compact_status_lines([sample]))

        self.assertIn("manual=unknown", text)
        self.assertNotIn("preview:", text)

    def test_raw_capture_preview_error_is_formatted(self) -> None:
        sample = SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type="camera.device",
            status="OK",
            value={
                "raw_capture": {
                    "status": "saved",
                    "raw_supported": True,
                    "width": 4000,
                    "height": 3000,
                    "preview_export_status": "error",
                    "preview_export_error": "preview conversion failed",
                    "last_dng_path": "/data/user/0/com.luvatrix.app/files/raw/camera_raw_1.dng",
                    "last_error": "",
                },
                "inventory": {"cameras": [{"camera_id": "0", "facing": "back"}]},
            },
            unit="metadata",
        )

        text = "\n".join(format_camera_status_lines([sample]))

        self.assertIn("preview error: preview conversion failed", text)

    def test_raw_capture_missing_optional_metadata_stays_compact(self) -> None:
        sample = SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type="camera.device",
            status="OK",
            value={
                "raw_capture": {
                    "status": "saved",
                    "raw_supported": True,
                    "width": 4000,
                    "height": 3000,
                    "last_dng_path": "/data/user/0/com.luvatrix.app/files/raw/camera_raw_1.dng",
                    "last_error": "",
                },
                "inventory": {"cameras": [{"camera_id": "0", "facing": "back"}]},
            },
            unit="metadata",
        )

        text = "\n".join(format_camera_status_lines([sample]))

        self.assertNotIn("RAW orientation:", text)
        self.assertNotIn("RAW lens:", text)
        self.assertFalse(any(line.startswith("preview: ") for line in text.splitlines()))
        self.assertNotIn("preview error:", text)

    def test_raw_capture_button_routes_to_android_bridge(self) -> None:
        app = CameraLabApp()
        app._buttons = [
            TouchButton("capture_raw", "raw capture", 0.0, 0.0, 100.0, 60.0),
        ]
        app._last_samples = [
            SensorSample(
                sample_id=1,
                ts_ns=1,
                sensor_type="camera.device",
                status="OK",
                value={
                    "raw_capture": {
                        "status": "ready",
                        "raw_supported": True,
                        "width": 4000,
                        "height": 3000,
                    },
                    "inventory": {"cameras": [{"camera_id": "0", "facing": "back"}]},
                },
                unit="metadata",
            )
        ]
        calls: list[str] = []
        old_capture = MODULE._android_capture_raw_still
        MODULE._android_capture_raw_still = lambda: calls.append("raw")
        try:
            app._handle_touch_action(50.0, 30.0)
        finally:
            MODULE._android_capture_raw_still = old_capture

        self.assertEqual(calls, ["raw"])
        self.assertEqual(app._last_action_status, "capturing RAW still")

    def test_keyboard_raw_controls_route_to_android_bridge(self) -> None:
        app = CameraLabApp()
        app._last_samples = [
            SensorSample(
                sample_id=1,
                ts_ns=1,
                sensor_type="camera.device",
                status="OK",
                value={"preview_controls": {"mode": "auto"}},
                unit="metadata",
            )
        ]
        calls: list[tuple[str, object]] = []
        old_mode = MODULE._android_set_preview_manual_mode
        old_iso = MODULE._android_adjust_raw_iso
        old_shutter = MODULE._android_adjust_raw_shutter
        old_focus = MODULE._android_adjust_raw_focus
        old_reset = MODULE._android_reset_raw_capture_controls
        old_wb = MODULE._android_set_preview_white_balance_mode
        MODULE._android_set_preview_manual_mode = lambda mode: calls.append(("mode", mode))
        MODULE._android_adjust_raw_iso = lambda delta: calls.append(("iso", delta))
        MODULE._android_adjust_raw_shutter = lambda delta: calls.append(("shutter", delta))
        MODULE._android_adjust_raw_focus = lambda delta: calls.append(("focus", delta))
        MODULE._android_reset_raw_capture_controls = lambda: calls.append(("reset", 0))
        MODULE._android_set_preview_white_balance_mode = lambda mode: calls.append(("wb", mode))
        try:
            app._handle_camera_key("m")
            app._handle_camera_key("w")
            app._handle_camera_key("]")
            app._handle_camera_key("-")
            app._handle_camera_key(".")
            app._handle_camera_key("0")
        finally:
            MODULE._android_set_preview_manual_mode = old_mode
            MODULE._android_adjust_raw_iso = old_iso
            MODULE._android_adjust_raw_shutter = old_shutter
            MODULE._android_adjust_raw_focus = old_focus
            MODULE._android_reset_raw_capture_controls = old_reset
            MODULE._android_set_preview_white_balance_mode = old_wb

        self.assertEqual(calls, [("mode", "manual"), ("wb", "neutral"), ("iso", 1), ("shutter", -1), ("focus", 1), ("reset", 0)])

    def test_touch_raw_controls_route_to_android_bridge(self) -> None:
        app = CameraLabApp()
        app._last_samples = [
            SensorSample(
                sample_id=1,
                ts_ns=1,
                sensor_type="camera.device",
                status="OK",
                value={"preview_controls": {"mode": "auto"}},
                unit="metadata",
            )
        ]
        app._buttons = [
            TouchButton("toggle_raw_mode", "mode", 0.0, 0.0, 50.0, 40.0),
            TouchButton("iso_down", "ISO-", 60.0, 0.0, 110.0, 40.0),
            TouchButton("iso_up", "ISO+", 120.0, 0.0, 170.0, 40.0),
            TouchButton("shutter_down", "S-", 180.0, 0.0, 230.0, 40.0),
            TouchButton("shutter_up", "S+", 240.0, 0.0, 290.0, 40.0),
            TouchButton("focus_down", "F-", 300.0, 0.0, 350.0, 40.0),
            TouchButton("focus_up", "F+", 360.0, 0.0, 410.0, 40.0),
            TouchButton("cycle_preview_white_balance", "WB", 420.0, 0.0, 470.0, 40.0),
        ]
        calls: list[tuple[str, object]] = []
        old_mode = MODULE._android_set_preview_manual_mode
        old_iso = MODULE._android_adjust_raw_iso
        old_shutter = MODULE._android_adjust_raw_shutter
        old_focus = MODULE._android_adjust_raw_focus
        old_reset = MODULE._android_reset_raw_capture_controls
        old_wb = MODULE._android_set_preview_white_balance_mode
        MODULE._android_set_preview_manual_mode = lambda mode: calls.append(("mode", mode))
        MODULE._android_adjust_raw_iso = lambda delta: calls.append(("iso", delta))
        MODULE._android_adjust_raw_shutter = lambda delta: calls.append(("shutter", delta))
        MODULE._android_adjust_raw_focus = lambda delta: calls.append(("focus", delta))
        MODULE._android_reset_raw_capture_controls = lambda: calls.append(("reset", 0))
        MODULE._android_set_preview_white_balance_mode = lambda mode: calls.append(("wb", mode))
        try:
            for x in (25.0, 85.0, 145.0, 205.0, 265.0, 325.0, 385.0, 445.0):
                app._handle_touch_action(x, 20.0)
        finally:
            MODULE._android_set_preview_manual_mode = old_mode
            MODULE._android_adjust_raw_iso = old_iso
            MODULE._android_adjust_raw_shutter = old_shutter
            MODULE._android_adjust_raw_focus = old_focus
            MODULE._android_reset_raw_capture_controls = old_reset
            MODULE._android_set_preview_white_balance_mode = old_wb

        self.assertEqual(
            calls,
            [
                ("mode", "manual"),
                ("iso", -1),
                ("iso", 1),
                ("shutter", -1),
                ("shutter", 1),
                ("focus", -1),
                ("focus", 1),
                ("wb", "neutral"),
            ],
        )

    def test_generated_touch_buttons_include_device_controls(self) -> None:
        app = CameraLabApp()
        buttons = app._control_buttons(width=480.0, height=900.0, margin=16.0)
        actions = {button.action for button in buttons}

        self.assertEqual(len(buttons), 12)
        self.assertEqual(
            actions,
            {
                "cycle_preview_quality",
                "cycle_preview_target",
                "cycle_preview_convolution_layers",
                "cycle_preview_pipeline",
                "toggle_raw_mode",
                "cycle_preview_white_balance",
                "iso_down",
                "iso_up",
                "shutter_down",
                "shutter_up",
                "focus_down",
                "focus_up",
            },
        )

    def test_touch_hud_toggle_switches_line_sets(self) -> None:
        app = CameraLabApp()
        app._buttons = [TouchButton("toggle_debug", "HUD", 0.0, 0.0, 100.0, 60.0)]

        app._handle_touch_action(50.0, 30.0)

        self.assertEqual(app._hud_mode, "compact")
        self.assertFalse(app._debug_hud)
        self.assertEqual(app._last_action_status, "HUD compact")

        app._handle_touch_action(50.0, 30.0)

        self.assertEqual(app._hud_mode, "debug")
        self.assertTrue(app._debug_hud)
        self.assertEqual(app._last_action_status, "HUD debug")

    def test_debug_hud_toggle_switches_line_sets(self) -> None:
        app = CameraLabApp()
        self.assertEqual(app._hud_mode, "collapsed")
        self.assertFalse(app._debug_hud)
        app._handle_camera_key("h")
        self.assertEqual(app._hud_mode, "compact")
        self.assertFalse(app._debug_hud)
        app._handle_camera_key("h")
        self.assertEqual(app._hud_mode, "debug")
        self.assertTrue(app._debug_hud)
        self.assertEqual(app._last_action_status, "HUD debug")

    def test_hud_line_fitting_clips_long_lines(self) -> None:
        lines = MODULE._fit_hud_lines(["abcdefghijklmnopqrstuvwxyz"], max_chars=12, max_lines=3)

        self.assertEqual(lines, ["abcdefghijk…", "lmnopqrstuv…", "wxyz"])


if __name__ == "__main__":
    unittest.main()
