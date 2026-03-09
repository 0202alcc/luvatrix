from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

import torch

from examples.planes_v2.hello_plane.app_main import create
from examples.planes_v2.training_protocol import run_validation
from luvatrix_core.core.app_runtime import AppContext
from luvatrix_core.core.hdi_thread import HDIEvent
from luvatrix_core.core.sensor_manager import SensorSample
from luvatrix_core.core.window_matrix import WindowMatrix
from luvatrix_core.platform.macos.vulkan_backend import MoltenVKMacOSBackend
from luvatrix_core.platform.macos.window_system import MacOSWindowHandle


HELLO_APP_DIR = Path(__file__).resolve().parents[1]
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
GOLDEN_SCREENSHOT = GOLDEN_DIR / "hello_plane_debug_screenshot.png"


class _FakeWindowSystem:
    def create_window(
        self,
        width: int,
        height: int,
        title: str,
        use_metal_layer: bool = True,
        preserve_aspect_ratio: bool = False,
        menu_config=None,
    ) -> MacOSWindowHandle:
        _ = (width, height, title, use_metal_layer, preserve_aspect_ratio, menu_config)

        class _Layer:
            pass

        return MacOSWindowHandle(window=object(), layer=_Layer())

    def destroy_window(self, handle: MacOSWindowHandle) -> None:
        _ = handle

    def pump_events(self) -> None:
        return

    def is_window_open(self, handle: MacOSWindowHandle) -> bool:
        _ = handle
        return True


class _QueuedHDI:
    def __init__(self) -> None:
        self._events: list[HDIEvent] = []

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def queue(self, event: HDIEvent) -> None:
        self._events.append(event)

    def poll_events(self, max_events: int) -> list[HDIEvent]:
        out = list(self._events[: max(0, int(max_events))])
        self._events = self._events[max(0, int(max_events)) :]
        return out

    def consume_telemetry(self) -> dict[str, int]:
        return {}


class _NoopSensorManager:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def read_sensor(self, sensor_type: str) -> SensorSample:
        return SensorSample(
            sample_id=0,
            ts_ns=0,
            sensor_type=sensor_type,
            status="UNAVAILABLE",
            value=None,
            unit=None,
        )


def _read_png_dimensions(path: Path) -> tuple[int, int]:
    raw = path.read_bytes()
    if len(raw) < 24:
        raise AssertionError("png payload too small")
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("invalid png header")
    width, height = struct.unpack("!II", raw[16:24])
    return (width, height)


def _read_png_rgba(path: Path) -> torch.Tensor:
    raw = path.read_bytes()
    if len(raw) < 8 or raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("invalid png header")

    pos = 8
    width = 0
    height = 0
    bit_depth = 0
    color_type = 0
    compressed = bytearray()

    while pos + 8 <= len(raw):
        chunk_len = struct.unpack("!I", raw[pos : pos + 4])[0]
        pos += 4
        chunk_type = raw[pos : pos + 4]
        pos += 4
        chunk_data = raw[pos : pos + chunk_len]
        pos += chunk_len
        pos += 4  # crc

        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, compression, filt, interlace = struct.unpack(
                "!IIBBBBB", chunk_data
            )
            if bit_depth != 8 or color_type != 6 or compression != 0 or filt != 0 or interlace != 0:
                raise AssertionError("unsupported png format for regression comparison")
        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)
        elif chunk_type == b"IEND":
            break

    if width <= 0 or height <= 0:
        raise AssertionError("missing png IHDR")
    if not compressed:
        raise AssertionError("missing png IDAT")

    decoded = zlib.decompress(bytes(compressed))
    stride = width * 4
    expected_len = height * (1 + stride)
    if len(decoded) != expected_len:
        raise AssertionError("unexpected png payload length")

    out = torch.zeros((height, width, 4), dtype=torch.uint8)
    prev = torch.zeros((stride,), dtype=torch.uint8)
    offset = 0
    for row in range(height):
        filt = decoded[offset]
        offset += 1
        scanline = torch.tensor(list(decoded[offset : offset + stride]), dtype=torch.uint8)
        offset += stride

        if filt == 0:
            recon = scanline
        elif filt == 1:
            recon = scanline.clone()
            for i in range(4, stride):
                recon[i] = (int(recon[i]) + int(recon[i - 4])) & 0xFF
        elif filt == 2:
            recon = (scanline.to(torch.int16) + prev.to(torch.int16)).remainder(256).to(torch.uint8)
        elif filt == 3:
            recon = scanline.clone()
            for i in range(stride):
                left = int(recon[i - 4]) if i >= 4 else 0
                up = int(prev[i])
                recon[i] = (int(recon[i]) + ((left + up) // 2)) & 0xFF
        elif filt == 4:
            recon = scanline.clone()
            for i in range(stride):
                a = int(recon[i - 4]) if i >= 4 else 0
                b = int(prev[i])
                c = int(prev[i - 4]) if i >= 4 else 0
                p = a + b - c
                pa = abs(p - a)
                pb = abs(p - b)
                pc = abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                recon[i] = (int(recon[i]) + pr) & 0xFF
        else:
            raise AssertionError(f"unsupported png filter type: {filt}")

        out[row] = recon.view(width, 4)
        prev = recon

    return out


class HelloPlaneAppTests(unittest.TestCase):
    def test_create_wires_expected_components(self) -> None:
        app = create()
        components = app._planes.get("components", [])
        self.assertIsInstance(components, list)
        ids = {str(c.get("id")) for c in components if isinstance(c, dict)}
        self.assertTrue({"title_text", "status_text", "btn_toggle_theme", "panel_bg"}.issubset(ids))

    def test_validation_artifact_reports_pass(self) -> None:
        artifact_path = run_validation(HELLO_APP_DIR)
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["app_id"], "hello_plane")
        self.assertEqual(payload["status"], "PASS")
        self.assertTrue(payload["interactive_checks"]["theme_toggled"])
        self.assertTrue(payload["all_checks_passed"])

    def test_debug_header_screenshot_captures_expected_frame(self) -> None:
        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        profile = {
            "supported": True,
            "enable_default_debug_root": True,
            "declared_capabilities": ["debug.root.default"],
            "unsupported_reason": None,
            "host_os": "macos",
        }
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "debug_menu"
            backend.configure_debug_menu(
                app_id="examples.planes_v2.hello_plane",
                profile=profile,
                artifact_dir=out,
            )
            app = create()
            ctx = AppContext(
                matrix=WindowMatrix(height=540, width=960),
                hdi=_QueuedHDI(),
                sensor_manager=_NoopSensorManager(),
                granted_capabilities={"window.write"},
            )
            app.init(ctx)
            app.loop(ctx, 0.016)
            rgba = ctx.read_matrix_snapshot().clone()
            expected_digest = backend._frame_digest(rgba)
            backend._capture_presented_frame(rgba)

            result = backend.dispatch_debug_menu_action("debug.menu.capture.screenshot")
            self.assertEqual(result.status, "EXECUTED")

            png_paths = sorted((out / "captures").glob("*.png"))
            sidecar_paths = sorted((out / "captures").glob("*.json"))
            self.assertEqual(len(png_paths), 1)
            self.assertEqual(len(sidecar_paths), 1)
            self.assertEqual(_read_png_dimensions(png_paths[0]), (960, 540))

            sidecar = json.loads(sidecar_paths[0].read_text(encoding="utf-8"))
            self.assertEqual(sidecar["route"], "examples.planes_v2.hello_plane")
            self.assertEqual(sidecar["provenance_id"], expected_digest)

            self.assertTrue(GOLDEN_SCREENSHOT.exists(), f"missing golden screenshot: {GOLDEN_SCREENSHOT}")
            golden_rgba = _read_png_rgba(GOLDEN_SCREENSHOT)
            captured_rgba = _read_png_rgba(png_paths[0])
            self.assertEqual(tuple(golden_rgba.shape), tuple(captured_rgba.shape))

            diff_mask = (golden_rgba != captured_rgba).any(dim=2)
            changed = int(diff_mask.sum().item())
            total = int(diff_mask.numel())
            ratio = float(changed) / float(max(1, total))
            threshold = 0.005

            if ratio > threshold:
                diff_rgba = torch.zeros_like(captured_rgba)
                diff_rgba[..., 3] = 255
                diff_rgba[diff_mask, 0] = 255
                diff_rgba[~diff_mask, 1] = 80
                diff_path = out / "captures" / "hello_plane_debug_screenshot.diff.png"
                backend._write_png_rgba(diff_rgba, diff_path)
                self.fail(
                    f"screenshot regression detected: changed_pixels={changed}/{total} ratio={ratio:.6f} "
                    f"(diff: {diff_path})"
                )


if __name__ == "__main__":
    unittest.main()
