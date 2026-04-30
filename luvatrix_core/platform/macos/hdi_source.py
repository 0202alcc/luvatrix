from __future__ import annotations

from collections import deque
import time

from luvatrix_core.core.hdi_thread import HDIEvent, HDIEventSource


class MacOSWindowHDISource(HDIEventSource):
    """Collects local keyboard/mouse/trackpad events for a specific AppKit window.

    Keyboard and mouse are sourced from IOKit HID directly (hardware rate, no
    WindowServer round-trip) when available. Trackpad gestures (scroll, pinch,
    rotate, pressure) continue to use the NSEvent local monitor.

    If IOKit HID is unavailable (import error, NULL manager, etc.) the source
    falls back silently to the original all-NSEvent path.
    """

    def __init__(self, window_handle) -> None:
        self._window_handle = window_handle
        self._next_id = 1
        self._queued_events: deque[HDIEvent] = deque()
        self._monitor = None
        self._last_mouse_buttons_mask = 0
        # IOKit path (populated by _install_iohid; None → NSEvent fallback).
        self._iohid = None
        self._last_window_active_local = True
        self._install_iohid()
        self._install_monitor()

    # ── IOKit HID setup ───────────────────────────────────────────────────────

    def _install_iohid(self) -> None:
        try:
            from luvatrix_core.platform.macos.iohid_source import IOKitHIDSource
            from AppKit import NSEvent  # type: ignore
            src = IOKitHIDSource()
            src.start()
            loc = NSEvent.mouseLocation()
            src.calibrate_position(float(loc.x), float(loc.y))
            self._iohid = src
        except Exception:
            pass

    # ── NSEvent monitor setup ─────────────────────────────────────────────────

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

        # When IOKit is active: watch only trackpad gesture events.
        # When falling back to NSEvent-only: watch everything (original mask).
        if self._iohid is not None:
            mask = (
                NSEventMaskScrollWheel
                | NSEventMaskPressure
                | NSEventMaskMagnify
                | NSEventMaskRotate
            )
        else:
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
                    phase = _scroll_phase_name(int(event.phase()))
                    momentum_phase = _scroll_phase_name(int(event.momentumPhase()))
                    payload = {
                        "x": float(loc.x),
                        "y": _to_top_left_y(float(loc.y), view_h),
                        "delta_x": float(event.scrollingDeltaX()),
                        "delta_y": float(event.scrollingDeltaY()),
                        "precise": bool(event.hasPreciseScrollingDeltas()),
                        "phase": phase,
                        "momentum_phase": momentum_phase,
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

    # ── poll ──────────────────────────────────────────────────────────────────

    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        out: list[HDIEvent] = []

        if self._iohid is not None:
            out.extend(self._poll_iohid(window_active, ts_ns))
        else:
            out.extend(self._poll_nsevent(ts_ns))

        # Always drain NSEvent queue (trackpad gestures, or full events on fallback).
        while self._queued_events:
            out.append(self._queued_events.popleft())

        self._last_window_active_local = window_active
        return out

    def _poll_iohid(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        """Drain the IOKit HID source and synthesise a pointer_move event."""
        out: list[HDIEvent] = []

        # On window activation: discard events accumulated while inactive and
        # resync the accumulated mouse position from NSEvent.
        just_activated = window_active and not self._last_window_active_local
        if just_activated:
            self._iohid.drain_events()  # discard stale cross-app events
            try:
                from AppKit import NSEvent  # type: ignore
                loc = NSEvent.mouseLocation()
                self._iohid.calibrate_position(float(loc.x), float(loc.y))
            except Exception:
                pass

        # Get window geometry for converting screen → window-local coordinates.
        window = self._window_handle.window
        try:
            frame = window.frame()
            win_x = float(frame.origin.x)
            win_y = float(frame.origin.y)
            view = window.contentView()
            view_h = float(view.bounds().size.height)
        except Exception:
            win_x = win_y = view_h = 0.0

        for ev in self._iohid.drain_events():
            if ev.device == "keyboard":
                out.append(
                    HDIEvent(
                        event_id=self._next_id,
                        ts_ns=ev.ts_ns,
                        window_id="logger-demo",
                        device="keyboard",
                        event_type=ev.event_type,
                        status="OK",
                        payload=ev.payload,
                    )
                )
                self._next_id += 1
            elif ev.device == "mouse" and ev.event_type == "click":
                payload = dict(ev.payload) if isinstance(ev.payload, dict) else {}
                sx = float(payload.pop("screen_x", 0.0))
                sy = float(payload.pop("screen_y", 0.0))
                payload["x"] = sx - win_x
                payload["y"] = _to_top_left_y(sy - win_y, view_h)
                out.append(
                    HDIEvent(
                        event_id=self._next_id,
                        ts_ns=ev.ts_ns,
                        window_id="logger-demo",
                        device="mouse",
                        event_type="click",
                        status="OK",
                        payload=payload,
                    )
                )
                self._next_id += 1

        # Emit one pointer_move per poll with the latest accumulated position.
        sx, sy = self._iohid.current_screen_xy()
        px = sx - win_x
        py = _to_top_left_y(sy - win_y, view_h)
        out.append(
            HDIEvent(
                event_id=self._next_id,
                ts_ns=ts_ns,
                window_id="logger-demo",
                device="mouse",
                event_type="pointer_move",
                status="OK",
                payload={"x": px, "y": py, "buttons_mask": int(self._iohid.current_buttons_mask())},
            )
        )
        self._next_id += 1
        return out

    def _poll_nsevent(self, ts_ns: int) -> list[HDIEvent]:
        """Original NSEvent-only mouse position / button polling path (fallback)."""
        try:
            from AppKit import NSEvent  # type: ignore
        except Exception:
            return []
        out: list[HDIEvent] = []
        had_click_event = any(event.event_type == "click" for event in self._queued_events)
        window = self._window_handle.window
        view = window.contentView()
        local_point = None
        try:
            local_point = window.mouseLocationOutsideOfEventStream()
        except Exception:
            local_point = None
        if local_point is None:
            global_mouse = NSEvent.mouseLocation()
            window_point = window.convertPointFromScreen_(global_mouse)
            local_point = view.convertPoint_fromView_(window_point, None)
        view_h = float(view.bounds().size.height)
        px = float(local_point.x)
        py = _to_top_left_y(float(local_point.y), view_h)
        if not had_click_event:
            buttons_mask = _read_pressed_mouse_buttons_mask(NSEvent=NSEvent)
            changed = int(buttons_mask ^ self._last_mouse_buttons_mask)
            for button in (0, 1):
                bit = 1 << button
                if changed & bit:
                    phase = "down" if (buttons_mask & bit) else "up"
                    out.append(
                        HDIEvent(
                            event_id=self._next_id,
                            ts_ns=ts_ns,
                            window_id="logger-demo",
                            device="mouse",
                            event_type="click",
                            status="OK",
                            payload={"x": px, "y": py, "button": button, "phase": phase, "click_count": 1},
                        )
                    )
                    self._next_id += 1
            self._last_mouse_buttons_mask = int(buttons_mask)
        out.append(
            HDIEvent(
                event_id=self._next_id,
                ts_ns=ts_ns,
                window_id="logger-demo",
                device="mouse",
                event_type="pointer_move",
                status="OK",
                payload={"x": px, "y": py, "buttons_mask": int(self._last_mouse_buttons_mask)},
            )
        )
        self._next_id += 1
        return out

    # ── cleanup ───────────────────────────────────────────────────────────────

    def close(self) -> None:
        if self._iohid is not None:
            try:
                self._iohid.stop()
            except Exception:
                pass
            self._iohid = None
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


def _read_pressed_mouse_buttons_mask(*, NSEvent) -> int:
    try:
        mask = int(NSEvent.pressedMouseButtons())
        if mask >= 0:
            return mask
    except Exception:
        pass
    try:
        import Quartz  # type: ignore

        left_down = bool(
            Quartz.CGEventSourceButtonState(
                Quartz.kCGEventSourceStateCombinedSessionState,
                Quartz.kCGMouseButtonLeft,
            )
        )
        right_down = bool(
            Quartz.CGEventSourceButtonState(
                Quartz.kCGEventSourceStateCombinedSessionState,
                Quartz.kCGMouseButtonRight,
            )
        )
        return (1 if left_down else 0) | (2 if right_down else 0)
    except Exception:
        return 0


def _scroll_phase_name(raw: int) -> str:
    phase_map = {
        0: "none",
        1: "began",
        2: "changed",
        3: "ended",
        4: "cancelled",
        5: "may_begin",
    }
    return phase_map.get(int(raw), "unknown")
