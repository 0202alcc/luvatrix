#!/usr/bin/env python3
"""Scripted Mac probe for the Web Playback SDK surface (SL-31).

NOT a committed test: it needs a real streaming-scoped OAuth token, the
PyObjC/AppKit stack (luvatrix[macos]), and network access to Spotify. Run
on macOS:

    uv run --extra macos python examples/spotify_light/scripts/web_playback_probe.py \
        --token "$(cat /path/to/streaming_token)" --seconds 20

Mint a token with the `streaming` scope by re-running the app's login flow
after the scope lands (re-consent), or from the Spotify developer console.
Exit 0 when the SDK reaches `ready` (device registered) without fatal
errors; nonzero otherwise. Prints every bridge event as it arrives.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))


class _Handle:
    """Duck-typed window handle: AppKitNativeControlBridge only reads .window."""

    def __init__(self, window) -> None:
        self.window = window


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token", required=True, help="streaming-scoped OAuth access token")
    parser.add_argument("--device-name", default="Luvatrix Probe")
    parser.add_argument("--seconds", type=float, default=20.0)
    args = parser.parse_args()

    try:
        from AppKit import (
            NSApplication,
            NSApplicationActivationPolicyAccessory,
            NSBackingStoreBuffered,
            NSMakeRect,
            NSWindow,
        )
        from Foundation import NSDate, NSRunLoop
    except ImportError:
        print("probe requires PyObjC/AppKit: uv run --extra macos ...", file=sys.stderr)
        return 2

    from luvatrix_core.platform.macos.native_controls import AppKitNativeControlBridge
    from luvatrix_core.platform.macos.playback_surface import WKWebPlaybackSurface

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0.0, 0.0, 240.0, 120.0), 0, NSBackingStoreBuffered, False,
    )
    window.orderFrontRegardless()

    bridge = AppKitNativeControlBridge(_Handle(window))
    surface = WKWebPlaybackSurface(bridge, device_name=args.device_name, token=args.token)
    surface.start()
    surface.send("connect")
    print(f"probe: surface started, waiting up to {args.seconds:.0f}s for ready...")

    deadline = time.monotonic() + args.seconds
    ready = False
    fatal = None
    while time.monotonic() < deadline and not ready and fatal is None:
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.25)
        )
        for event in surface.drain_events():
            print(f"probe: {event.kind.value} {event.payload}", flush=True)
            if event.kind.value == "ready":
                ready = True
            elif event.kind.value in ("initialization_error", "authentication_error",
                                      "account_error"):
                fatal = event

    surface.stop()
    window.close()
    if fatal is not None:
        print(f"probe: FAILED — {fatal.kind.value}: {fatal.payload}", file=sys.stderr)
        return 1
    if not ready:
        print("probe: FAILED — no ready event before deadline", file=sys.stderr)
        return 1
    print(f"probe: OK — device registered as {surface.device_id!r}" if surface.device_id
          else "probe: OK — ready fired")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
