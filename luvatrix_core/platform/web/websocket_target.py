from __future__ import annotations


class RemoteFramebufferWebRuntimeRemoved(RuntimeError):
    """Raised when legacy PNG-over-WebSocket web runtime APIs are requested."""


def __getattr__(name: str) -> object:
    raise RemoteFramebufferWebRuntimeRemoved(
        "The legacy web framebuffer runtime has been removed. "
        "Use `luvatrix build-web APP_DIR --out DIST` or `luvatrix serve-web APP_DIR` "
        "for the browser-side runtime."
    )
