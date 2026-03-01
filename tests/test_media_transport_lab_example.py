from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image
import torch

from luvatrix_core.core.app_runtime import AppRuntime
from luvatrix_core.core.hdi_thread import HDIEvent, HDIEventSource, HDIThread
from luvatrix_core.core.sensor_manager import SensorManagerThread
from luvatrix_core.core.window_matrix import WindowMatrix

APP_DIR = Path(__file__).resolve().parents[1] / "examples" / "media_transport_lab"
MODULE_PATH = APP_DIR / "app_main.py"
SPEC = importlib.util.spec_from_file_location("media_transport_lab_app_main", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"failed to load module spec for {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

MediaTransportLabApp = MODULE.MediaTransportLabApp
_fit_preserve_aspect = MODULE._fit_preserve_aspect
_open_animated_or_fallback = MODULE._open_animated_or_fallback
_open_image_or_fallback = MODULE._open_image_or_fallback


class _NoopHDISource(HDIEventSource):
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        _ = (window_active, ts_ns)
        return []


@dataclass
class _FakeWriteEvent:
    revision: int = 1


class _FakeCtx:
    def __init__(self, width: int, height: int) -> None:
        self._snapshot = torch.zeros((height, width, 4), dtype=torch.uint8)
        self._events: list[HDIEvent] = []
        self.last_frame: torch.Tensor | None = None

    def read_matrix_snapshot(self) -> torch.Tensor:
        return self._snapshot

    def poll_hdi_events(self, max_events: int, frame: str | None = None) -> list[HDIEvent]:
        _ = (max_events, frame)
        events = self._events
        self._events = []
        return events

    def submit_write_batch(self, batch) -> _FakeWriteEvent:
        op = batch.operations[0]
        self.last_frame = op.tensor_h_w_4.clone()
        return _FakeWriteEvent()

    def queue_events(self, events: list[HDIEvent]) -> None:
        self._events.extend(events)


def _key_event(key: str) -> HDIEvent:
    return HDIEvent(
        event_id=1,
        ts_ns=1,
        window_id="w",
        device="keyboard",
        event_type="press",
        status="OK",
        payload={"phase": "down", "key": key},
    )


def _click_event(x: float, y: float) -> HDIEvent:
    return HDIEvent(
        event_id=2,
        ts_ns=2,
        window_id="w",
        device="mouse",
        event_type="click",
        status="OK",
        payload={"x": x, "y": y},
    )


class MediaTransportLabTests(unittest.TestCase):
    # 1) Design success criteria tests.
    def test_success_runtime_example_runs_and_writes_non_uniform_frames(self) -> None:
        app_dir = APP_DIR
        matrix = WindowMatrix(height=96, width=160)
        runtime = AppRuntime(
            matrix=matrix,
            hdi=HDIThread(source=_NoopHDISource()),
            sensor_manager=SensorManagerThread(providers={}),
            capability_decider=lambda capability: True,
        )

        runtime.run(app_dir, max_ticks=3, target_fps=120)
        self.assertEqual(matrix.revision, 3)

        frame = matrix.read_snapshot()
        self.assertEqual(tuple(frame.shape), (96, 160, 4))
        self.assertGreater(float(frame[:, :, :3].float().std().item()), 0.0)

    def test_success_aspect_ratio_fit_letterboxes_when_needed(self) -> None:
        fit = _fit_preserve_aspect(src_w=1920, src_h=1080, dst_w=320, dst_h=200)
        self.assertEqual(fit.width, 320)
        self.assertEqual(fit.height, 180)
        self.assertEqual(fit.x, 0)
        self.assertEqual(fit.y, 10)

    # 2) Design safety tests.
    def test_safety_missing_image_path_uses_fallback(self) -> None:
        img = _open_image_or_fallback(Path("/definitely/missing/image.png"))
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.mode, "RGBA")

    def test_safety_missing_video_path_uses_fallback_frames(self) -> None:
        frames = _open_animated_or_fallback(Path("/definitely/missing/video.gif"))
        self.assertGreaterEqual(len(frames), 2)
        self.assertTrue(all(f.duration_s > 0 for f in frames))

    # 3) Design implementation tests.
    def test_implementation_keyboard_controls_toggle_and_seek(self) -> None:
        app = MediaTransportLabApp()
        ctx = _FakeCtx(width=160, height=96)
        app.init(ctx)

        app.loop(ctx, dt=0.0)
        start_idx = app._video_idx
        start_playing = app._playing

        ctx.queue_events([_key_event("space")])
        app.loop(ctx, dt=0.0)
        self.assertNotEqual(app._playing, start_playing)

        ctx.queue_events([_key_event("right")])
        app.loop(ctx, dt=0.0)
        self.assertNotEqual(app._video_idx, start_idx)

    def test_implementation_click_controls_activate_buttons(self) -> None:
        app = MediaTransportLabApp()
        ctx = _FakeCtx(width=180, height=120)
        app.init(ctx)
        app.loop(ctx, dt=0.0)

        toggle_btn = [b for b in app._buttons if b.action == "toggle"][0]
        mid_x = (toggle_btn.x0 + toggle_btn.x1) / 2.0
        mid_y = (toggle_btn.y0 + toggle_btn.y1) / 2.0
        before = app._playing

        ctx.queue_events([_click_event(mid_x, mid_y)])
        app.loop(ctx, dt=0.0)
        self.assertNotEqual(app._playing, before)

    # 4) Design edge case tests.
    def test_edge_invalid_dimensions_returns_zero_sized_fit(self) -> None:
        fit = _fit_preserve_aspect(src_w=0, src_h=10, dst_w=100, dst_h=100)
        self.assertEqual((fit.x, fit.y, fit.width, fit.height), (0, 0, 0, 0))

    def test_edge_single_pixel_viewport_still_renders(self) -> None:
        app = MediaTransportLabApp()
        ctx = _FakeCtx(width=1, height=1)
        app.init(ctx)
        app.loop(ctx, dt=0.0)
        self.assertIsNotNone(ctx.last_frame)
        assert ctx.last_frame is not None
        self.assertEqual(tuple(ctx.last_frame.shape), (1, 1, 4))

    def test_edge_negative_dt_does_not_advance_video(self) -> None:
        app = MediaTransportLabApp()
        ctx = _FakeCtx(width=160, height=96)
        app.init(ctx)
        app.loop(ctx, dt=0.0)
        idx_before = app._video_idx

        app.loop(ctx, dt=-1.0)
        self.assertEqual(app._video_idx, idx_before)

    def test_safety_can_load_real_animated_image_durations(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "mini.gif"
            f1 = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
            f2 = Image.new("RGBA", (8, 8), (0, 255, 0, 255))
            f1.save(target, save_all=True, append_images=[f2], duration=[120, 80], loop=0)

            frames = _open_animated_or_fallback(target)
            self.assertEqual(len(frames), 2)
            self.assertAlmostEqual(frames[0].duration_s, 0.12, places=2)


if __name__ == "__main__":
    unittest.main()
