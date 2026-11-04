"""Tiny iOS app that de-risks urllib-over-TLS on device.

With ``--smoke-net <url>`` in argv or ``LUVATRIX_SMOKE_NET_URL`` set (the
workflow passes it as SIMCTL_CHILD_LUVATRIX_SMOKE_NET_URL), the app performs
one GET through `UrllibTransport`, writes status/bytes/TLS version to
status.json in the app container, prints the payload, and exits. Without a
configured URL it renders an idle frame so the app still validates and runs.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Mapping, Sequence

from luvatrix.app import App
from luvatrix.net.smoke import resolve_smoke_net_url, run_smoke_net


class NetSmokeApp(App):
    def render(self) -> None:
        width = self.display.width_px
        height = self.display.height_px
        size = max(1, min(width, height) // 4)
        x = float((width - size) // 2)
        y = float((height - size) // 2)
        with self.frame(clear=(12, 24, 40, 255)) as frame:
            frame.rect(x=x, y=y, width=float(size), height=float(size), color=(64, 160, 255, 255))


def _maybe_run_smoke(argv: Sequence[str], environ: Mapping[str, str]) -> bool:
    url = resolve_smoke_net_url(argv, environ)
    if url is None:
        return False
    payload = run_smoke_net(url)
    print(f"[net_smoke] {json.dumps(payload, sort_keys=True)}", flush=True)
    # The runner reads status.json from the container; the exit code mirrors ok.
    os._exit(0 if payload["ok"] else 1)
    return True  # unreachable; for the type checker


def create() -> NetSmokeApp:
    _maybe_run_smoke(sys.argv[1:], os.environ)
    return NetSmokeApp()
