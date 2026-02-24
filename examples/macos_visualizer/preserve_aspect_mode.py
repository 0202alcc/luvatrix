from __future__ import annotations

import time
from pathlib import Path
import sys

import torch

# Allow running this file directly without installing the package.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from luvatrix_core.core.display_runtime import DisplayRuntime
from luvatrix_core.core.window_matrix import FullRewrite, WindowMatrix, WriteBatch
from luvatrix_core.platform.macos import MacOSVulkanPresenter
from luvatrix_core.targets.vulkan_target import VulkanTarget


def main() -> None:
    width, height = 640, 360
    matrix = WindowMatrix(height=height, width=width)
    presenter = MacOSVulkanPresenter(
        width=width,
        height=height,
        title="Luvatrix Preserve Aspect Mode",
        preserve_aspect_ratio=True,
    )
    target = VulkanTarget(presenter=presenter)
    runtime = DisplayRuntime(matrix=matrix, target=target)

    target.start()
    try:
        for t in range(300):
            if presenter.should_close():
                break
            frame = torch.zeros((height, width, 4), dtype=torch.uint8)
            frame[:, :, 0] = (t * 3) % 256
            gx = torch.linspace(0, 255, width, dtype=torch.float32).to(torch.uint8)
            gy = torch.linspace(0, 255, height, dtype=torch.float32).to(torch.uint8)
            frame[:, :, 1] = gx.unsqueeze(0).expand(height, width)
            frame[:, :, 2] = gy.unsqueeze(1).expand(height, width)
            frame[:, :, 3] = 255

            matrix.submit_write_batch(WriteBatch([FullRewrite(frame)]))
            runtime.run_once(timeout=0.0)
            presenter.pump_events()
            time.sleep(1 / 30)
    finally:
        target.stop()


if __name__ == "__main__":
    main()
