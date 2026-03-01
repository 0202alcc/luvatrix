from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import torch

from luvatrix_core.core.window_matrix import FullRewrite, WriteBatch
from luvatrix_core.core.hdi_thread import HDIEvent


APP_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class VideoFrame:
    image: Image.Image
    duration_s: float


@dataclass(frozen=True)
class ButtonRect:
    action: str
    x0: int
    y0: int
    x1: int
    y1: int

    def contains(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1


@dataclass(frozen=True)
class AspectFit:
    x: int
    y: int
    width: int
    height: int


def _env_path(name: str) -> Path | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _fit_preserve_aspect(src_w: int, src_h: int, dst_w: int, dst_h: int) -> AspectFit:
    if src_w <= 0 or src_h <= 0 or dst_w <= 0 or dst_h <= 0:
        return AspectFit(0, 0, 0, 0)
    scale = min(float(dst_w) / float(src_w), float(dst_h) / float(src_h))
    out_w = max(1, int(round(src_w * scale)))
    out_h = max(1, int(round(src_h * scale)))
    x = (dst_w - out_w) // 2
    y = (dst_h - out_h) // 2
    return AspectFit(x=x, y=y, width=out_w, height=out_h)


def _open_image_or_fallback(path: Path | None) -> Image.Image:
    if path is not None and path.exists():
        with Image.open(path) as img:
            return img.convert("RGBA")
    return _build_demo_image(640, 360)


def _open_animated_or_fallback(path: Path | None) -> list[VideoFrame]:
    if path is not None and path.exists():
        with Image.open(path) as src:
            frame_count = int(getattr(src, "n_frames", 1))
            out: list[VideoFrame] = []
            for idx in range(frame_count):
                src.seek(idx)
                raw_duration_ms = int(src.info.get("duration", 80) or 80)
                duration_s = max(0.02, float(raw_duration_ms) / 1000.0)
                out.append(VideoFrame(image=src.convert("RGBA"), duration_s=duration_s))
            if out:
                return out
    return _build_demo_video_frames(width=640, height=360, frames=48)


def _build_demo_image(width: int, height: int) -> Image.Image:
    img = Image.new("RGBA", (width, height), (18, 24, 34, 255))
    draw = ImageDraw.Draw(img)

    # Subtle gradient bands, deterministic and dependency-free.
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(16 + 70 * t)
        g = int(20 + 40 * t)
        b = int(36 + 50 * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    block_w = max(16, width // 12)
    block_h = max(16, height // 8)
    for gy in range(0, height, block_h):
        for gx in range(0, width, block_w):
            if (gx // block_w + gy // block_h) % 2 == 0:
                draw.rectangle([(gx, gy), (gx + block_w - 1, gy + block_h - 1)], outline=(185, 211, 238, 90))

    draw.rounded_rectangle([(width * 0.08, height * 0.12), (width * 0.92, height * 0.88)], radius=24, outline=(255, 255, 255, 210), width=3)
    draw.polygon(
        [
            (width * 0.45, height * 0.35),
            (width * 0.45, height * 0.65),
            (width * 0.65, height * 0.50),
        ],
        fill=(255, 120, 80, 230),
    )
    return img


def _build_demo_video_frames(width: int, height: int, frames: int) -> list[VideoFrame]:
    out: list[VideoFrame] = []
    radius = max(12, min(width, height) // 9)
    for idx in range(frames):
        img = Image.new("RGBA", (width, height), (9, 14, 20, 255))
        draw = ImageDraw.Draw(img)

        for y in range(height):
            t = y / max(1, height - 1)
            draw.line([(0, y), (width, y)], fill=(10, int(20 + 60 * t), int(40 + 90 * t), 255))

        phase = float(idx) / max(1, frames - 1)
        cx = int((width * 0.1) + phase * width * 0.8)
        cy = int(height * (0.5 + 0.28 * math.sin(phase * math.tau * 2.0)))
        draw.ellipse([(cx - radius, cy - radius), (cx + radius, cy + radius)], fill=(255, 124, 96, 240), outline=(255, 255, 255, 220), width=3)

        out.append(VideoFrame(image=img, duration_s=1.0 / 24.0))
    return out


def _as_tensor_rgba(image: Image.Image) -> torch.Tensor:
    data = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    return torch.from_numpy(data.copy())


class MediaTransportLabApp:
    def __init__(self) -> None:
        self._image_path = _env_path("LUVATRIX_MEDIA_IMAGE_PATH")
        self._video_path = _env_path("LUVATRIX_MEDIA_VIDEO_PATH")

        self._image = _open_image_or_fallback(self._image_path)
        self._video = _open_animated_or_fallback(self._video_path)
        self._mode = os.getenv("LUVATRIX_MEDIA_MODE", "video").strip().lower()
        if self._mode not in ("image", "video"):
            self._mode = "video"

        self._video_idx = 0
        self._video_clock_s = 0.0
        self._playing = True

        self._width = 0
        self._height = 0
        self._buttons: list[ButtonRect] = []

    def init(self, ctx) -> None:
        snap = ctx.read_matrix_snapshot()
        self._height, self._width, _ = snap.shape

    def loop(self, ctx, dt: float) -> None:
        events = ctx.poll_hdi_events(max_events=128, frame="screen_tl")
        self._update_controls(events)

        if self._mode == "video" and self._playing:
            self._advance_video(max(0.0, dt))

        frame = self._render_frame()
        ctx.submit_write_batch(WriteBatch([FullRewrite(_as_tensor_rgba(frame))]))

    def stop(self, ctx) -> None:
        _ = ctx

    def _advance_video(self, dt: float) -> None:
        if not self._video:
            return
        self._video_clock_s += dt
        while self._video_clock_s >= self._video[self._video_idx].duration_s:
            self._video_clock_s -= self._video[self._video_idx].duration_s
            self._video_idx = (self._video_idx + 1) % len(self._video)

    def _render_frame(self) -> Image.Image:
        canvas = Image.new("RGBA", (self._width, self._height), (6, 9, 14, 255))
        draw = ImageDraw.Draw(canvas)

        controls_h = max(42, min(72, int(round(self._height * 0.16))))
        media_h = max(1, self._height - controls_h)

        media = self._current_media_frame()
        fit = _fit_preserve_aspect(media.width, media.height, self._width, media_h)
        if fit.width > 0 and fit.height > 0:
            resized = media.resize((fit.width, fit.height), Image.Resampling.BICUBIC)
            canvas.paste(resized, (fit.x, fit.y), resized)

        bar_top = media_h
        draw.rectangle([(0, bar_top), (self._width, self._height)], fill=(10, 15, 24, 255))

        self._buttons = self._draw_controls(draw, bar_top, controls_h)
        return canvas

    def _draw_controls(self, draw: ImageDraw.ImageDraw, bar_top: int, controls_h: int) -> list[ButtonRect]:
        gap = max(8, controls_h // 7)
        btn_h = controls_h - 2 * gap
        btn_w = max(56, int(round(self._width * 0.16)))
        total_w = 3 * btn_w + 2 * gap
        left = max(0, (self._width - total_w) // 2)
        y0 = bar_top + gap
        y1 = y0 + btn_h

        buttons = [
            ButtonRect("rewind", left, y0, left + btn_w, y1),
            ButtonRect("toggle", left + btn_w + gap, y0, left + 2 * btn_w + gap, y1),
            ButtonRect("forward", left + 2 * btn_w + 2 * gap, y0, left + 3 * btn_w + 2 * gap, y1),
        ]

        for b in buttons:
            draw.rounded_rectangle([(b.x0, b.y0), (b.x1, b.y1)], radius=8, fill=(24, 34, 48, 255), outline=(156, 174, 201, 255), width=2)

        # Rewind icon.
        rw = buttons[0]
        cx = (rw.x0 + rw.x1) // 2
        cy = (rw.y0 + rw.y1) // 2
        tri_w = max(10, (rw.x1 - rw.x0) // 6)
        tri_h = max(10, (rw.y1 - rw.y0) // 3)
        draw.polygon([(cx + tri_w // 2, cy - tri_h), (cx + tri_w // 2, cy + tri_h), (cx - tri_w, cy)], fill=(242, 245, 250, 255))
        draw.polygon([(cx + tri_w + tri_w // 2, cy - tri_h), (cx + tri_w + tri_w // 2, cy + tri_h), (cx, cy)], fill=(242, 245, 250, 255))

        # Toggle icon.
        tg = buttons[1]
        tcx = (tg.x0 + tg.x1) // 2
        tcy = (tg.y0 + tg.y1) // 2
        if self._playing and self._mode == "video":
            bar_w = max(4, (tg.x1 - tg.x0) // 12)
            bar_h = max(12, (tg.y1 - tg.y0) // 2)
            draw.rectangle([(tcx - bar_w - 2, tcy - bar_h // 2), (tcx - 2, tcy + bar_h // 2)], fill=(242, 245, 250, 255))
            draw.rectangle([(tcx + 2, tcy - bar_h // 2), (tcx + bar_w + 2, tcy + bar_h // 2)], fill=(242, 245, 250, 255))
        else:
            play_w = max(12, (tg.x1 - tg.x0) // 4)
            play_h = max(12, (tg.y1 - tg.y0) // 3)
            draw.polygon([(tcx - play_w // 3, tcy - play_h), (tcx - play_w // 3, tcy + play_h), (tcx + play_w, tcy)], fill=(242, 245, 250, 255))

        # Forward icon.
        ff = buttons[2]
        cx = (ff.x0 + ff.x1) // 2
        cy = (ff.y0 + ff.y1) // 2
        draw.polygon([(cx - tri_w // 2, cy - tri_h), (cx - tri_w // 2, cy + tri_h), (cx + tri_w, cy)], fill=(242, 245, 250, 255))
        draw.polygon([(cx - tri_w - tri_w // 2, cy - tri_h), (cx - tri_w - tri_w // 2, cy + tri_h), (cx, cy)], fill=(242, 245, 250, 255))

        return buttons

    def _current_media_frame(self) -> Image.Image:
        if self._mode == "image":
            return self._image
        if not self._video:
            return self._image
        return self._video[self._video_idx].image

    def _update_controls(self, events: list[HDIEvent]) -> None:
        for event in events:
            if event.status != "OK":
                continue
            if event.device == "keyboard" and event.event_type == "press":
                if isinstance(event.payload, dict):
                    phase = str(event.payload.get("phase", ""))
                    key = str(event.payload.get("key", "")).lower()
                    if phase in ("down", "single", "repeat"):
                        self._handle_key(key)
            if event.device in ("mouse", "trackpad") and event.event_type in ("click", "tap"):
                if isinstance(event.payload, dict):
                    x = event.payload.get("x")
                    y = event.payload.get("y")
                    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                        for button in self._buttons:
                            if button.contains(float(x), float(y)):
                                self._apply_action(button.action)
                                break

    def _handle_key(self, key: str) -> None:
        if key in ("space", "k"):
            self._apply_action("toggle")
            return
        if key in ("left", "a", "j"):
            self._apply_action("rewind")
            return
        if key in ("right", "d", "l"):
            self._apply_action("forward")
            return
        if key == "m":
            self._mode = "image" if self._mode == "video" else "video"
            return

    def _apply_action(self, action: str) -> None:
        if action == "toggle":
            if self._mode == "image":
                self._mode = "video"
            self._playing = not self._playing
            return
        if action == "rewind":
            if self._video:
                self._video_idx = (self._video_idx - 5) % len(self._video)
                self._video_clock_s = 0.0
            return
        if action == "forward":
            if self._video:
                self._video_idx = (self._video_idx + 5) % len(self._video)
                self._video_clock_s = 0.0



def create():
    return MediaTransportLabApp()
