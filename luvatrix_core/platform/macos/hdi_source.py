from __future__ import annotations

from collections import deque
import time

from luvatrix_core.core.hdi_thread import HDIEvent, HDIEventSource


class MacOSWindowHDISource(HDIEventSource):
    """Collects local keyboard/mouse/trackpad events for a specific AppKit window."""

    def __init__(self, window_handle) -> None:
        self._window_handle = window_handle
        self._next_id = 1
        self._queued_events: deque[HDIEvent] = deque()
        self._monitor = None
        self._install_monitor()

    def _install_monitor(self) -> None:
        try:
            from AppKit import (  # type: ignore
                NSEvent,
                NSEventMaskKeyDown,
                NSEventMaskKeyUp,
                NSEventMaskScrollWheel,
                NSEventMaskPressure,
                NSEventMaskMagnify,
                NSEventMaskRotate,
                NSEventMaskLeftMouseDown,
                NSEventMaskLeftMouseUp,
                NSEventMaskRightMouseDown,
                NSEventMaskRightMouseUp,
                NSEventTypeKeyDown,
                NSEventTypeKeyUp,
                NSEventTypeScrollWheel,
                NSEventTypePressure,
                NSEventTypeMagnify,
                NSEventTypeRotate,
                NSEventTypeLeftMouseDown,
                NSEventTypeLeftMouseUp,
                NSEventTypeRightMouseDown,
                NSEventTypeRightMouseUp,
            )
        except Exception:
            return
        mask = (
            NSEventMaskKeyDown
            | NSEventMaskKeyUp
            | NSEventMaskScrollWheel
            | NSEventMaskPressure
            | NSEventMaskMagnify
            | NSEventMaskRotate
            | NSEventMaskLeftMouseDown
            | NSEventMaskLeftMouseUp
            | NSEventMaskRightMouseDown
            | NSEventMaskRightMouseUp
        )

        def handler(event):
            try:
                window = event.window()
                if window is not None and window != self._window_handle.window:
                    return event
                event_type = int(event.type())
                if event_type == int(NSEventTypeKeyDown):
                    hdi_type = "key_down"
                    device = "keyboard"
                    payload = {"key": str(event.charactersIgnoringModifiers() or ""), "code": int(event.keyCode())}
                elif event_type == int(NSEventTypeKeyUp):
                    hdi_type = "key_up"
                    device = "keyboard"
                    payload = {"key": str(event.charactersIgnoringModifiers() or ""), "code": int(event.keyCode())}
                elif event_type == int(NSEventTypeScrollWheel):
                    hdi_type = "scroll"
                    device = "trackpad"
                    loc = event.locationInWindow()
                    view = self._window_handle.window.contentView()
                    view_h = float(view.bounds().size.height)
                    payload = {
                        "x": float(loc.x),
                        "y": _to_top_left_y(float(loc.y), view_h),
                        "delta_x": float(event.scrollingDeltaX()),
                        "delta_y": float(event.scrollingDeltaY()),
                    }
                elif event_type == int(NSEventTypePressure):
                    hdi_type = "pressure"
                    device = "trackpad"
                    loc = event.locationInWindow()
                    view = self._window_handle.window.contentView()
                    view_h = float(view.bounds().size.height)
                    payload = {
                        "x": float(loc.x),
                        "y": _to_top_left_y(float(loc.y), view_h),
                        "pressure": float(event.pressure()),
                        "stage": int(event.stage()),
                    }
                elif event_type == int(NSEventTypeMagnify):
                    hdi_type = "pinch"
                    device = "trackpad"
                    loc = event.locationInWindow()
                    view = self._window_handle.window.contentView()
                    view_h = float(view.bounds().size.height)
                    payload = {
                        "x": float(loc.x),
                        "y": _to_top_left_y(float(loc.y), view_h),
                        "magnification": float(event.magnification()),
                    }
                elif event_type == int(NSEventTypeRotate):
                    hdi_type = "rotate"
                    device = "trackpad"
                    loc = event.locationInWindow()
                    view = self._window_handle.window.contentView()
                    view_h = float(view.bounds().size.height)
                    payload = {
                        "x": float(loc.x),
                        "y": _to_top_left_y(float(loc.y), view_h),
                        "rotation": float(event.rotation()),
                    }
                elif event_type in (int(NSEventTypeLeftMouseDown), int(NSEventTypeRightMouseDown)):
                    hdi_type = "click"
                    device = "trackpad"
                    loc = event.locationInWindow()
                    view = self._window_handle.window.contentView()
                    view_h = float(view.bounds().size.height)
                    payload = {
                        "x": float(loc.x),
                        "y": _to_top_left_y(float(loc.y), view_h),
                        "button": 0 if event_type == int(NSEventTypeLeftMouseDown) else 1,
                        "phase": "down",
                        "click_count": int(event.clickCount()),
                    }
                elif event_type in (int(NSEventTypeLeftMouseUp), int(NSEventTypeRightMouseUp)):
                    hdi_type = "click"
                    device = "trackpad"
                    loc = event.locationInWindow()
                    view = self._window_handle.window.contentView()
                    view_h = float(view.bounds().size.height)
                    payload = {
                        "x": float(loc.x),
                        "y": _to_top_left_y(float(loc.y), view_h),
                        "button": 0 if event_type == int(NSEventTypeLeftMouseUp) else 1,
                        "phase": "up",
                        "click_count": int(event.clickCount()),
                    }
                else:
                    return event
                self._queued_events.append(
                    HDIEvent(
                        event_id=self._next_id,
                        ts_ns=time.time_ns(),
                        window_id="logger-demo",
                        device=device,  # type: ignore[arg-type]
                        event_type=hdi_type,
                        status="OK",
                        payload=payload,
                    )
                )
                self._next_id += 1
            except Exception:
                return event
            return event

        self._monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, handler)

    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        try:
            from AppKit import NSEvent  # type: ignore
        except Exception:
            return []
        out: list[HDIEvent] = []
        while self._queued_events:
            out.append(self._queued_events.popleft())
        window = self._window_handle.window
        view = window.contentView()
        global_mouse = NSEvent.mouseLocation()
        window_point = window.convertPointFromScreen_(global_mouse)
        local_point = view.convertPoint_fromView_(window_point, None)
        view_h = float(view.bounds().size.height)
        out.append(
            HDIEvent(
                event_id=self._next_id,
                ts_ns=ts_ns,
                window_id="logger-demo",
                device="mouse",
                event_type="pointer_move",
                status="OK",
                payload={"x": float(local_point.x), "y": _to_top_left_y(float(local_point.y), view_h)},
            )
        )
        self._next_id += 1
        return out

    def close(self) -> None:
        if self._monitor is None:
            return
        try:
            from AppKit import NSEvent  # type: ignore
        except Exception:
            self._monitor = None
            return
        try:
            NSEvent.removeMonitor_(self._monitor)
        finally:
            self._monitor = None

def _to_top_left_y(local_y: float, view_height: float) -> float:
    h = max(1.0, float(view_height))
    y = (h - 1.0) - float(local_y)
    if y < 0.0:
        return 0.0
    if y > (h - 1.0):
        return h - 1.0
    return y
