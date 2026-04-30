from __future__ import annotations

from luvatrix_core import accel
from luvatrix_core.core.window_matrix import FullRewrite, WriteBatch


class HelloWorldApp:
    def init(self, ctx) -> None:
        snap = ctx.read_matrix_snapshot()
        h, w, _ = snap.shape

        frame = accel.zeros((h, w, 4))
        # Dark blue background
        frame[:, :, 0] = 30
        frame[:, :, 1] = 30
        frame[:, :, 2] = 46
        frame[:, :, 3] = 255

        # Centered white rect (~1/4 width, ~1/8 height)
        s = max(1, min(w, h) // 4)
        rw, rh = s, s
        x0, y0 = (w - rw) // 2, (h - rh) // 2
        frame[y0 : y0 + rh, x0 : x0 + rw, :] = 255

        ctx.submit_write_batch(WriteBatch([FullRewrite(frame)]))

    def loop(self, ctx, dt: float) -> None:
        pass

    def stop(self, ctx) -> None:
        pass


def create() -> HelloWorldApp:
    return HelloWorldApp()
