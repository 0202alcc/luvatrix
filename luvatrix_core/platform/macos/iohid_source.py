from __future__ import annotations

import ctypes
import threading
import time
from collections import deque

from luvatrix_core.core.hdi_thread import HDIEvent

# ── Framework loading ─────────────────────────────────────────────────────────

_CF = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
_IOKit = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")

# ── CoreFoundation function signatures ────────────────────────────────────────

_CF.CFRunLoopGetCurrent.restype = ctypes.c_void_p
_CF.CFRunLoopGetCurrent.argtypes = []
_CF.CFRunLoopRun.restype = None
_CF.CFRunLoopRun.argtypes = []
_CF.CFRunLoopStop.restype = None
_CF.CFRunLoopStop.argtypes = [ctypes.c_void_p]
_CF.CFNumberCreate.restype = ctypes.c_void_p
_CF.CFNumberCreate.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
_CF.CFDictionaryCreate.restype = ctypes.c_void_p
_CF.CFDictionaryCreate.argtypes = [
    ctypes.c_void_p,  # allocator
    ctypes.c_void_p,  # keys array
    ctypes.c_void_p,  # values array
    ctypes.c_long,    # numValues
    ctypes.c_void_p,  # keyCallBacks
    ctypes.c_void_p,  # valueCallBacks
]
_CF.CFArrayCreate.restype = ctypes.c_void_p
_CF.CFArrayCreate.argtypes = [
    ctypes.c_void_p,  # allocator
    ctypes.c_void_p,  # values array
    ctypes.c_long,    # numValues
    ctypes.c_void_p,  # callBacks
]
_CF.CFRelease.restype = None
_CF.CFRelease.argtypes = [ctypes.c_void_p]

# ── IOKit function signatures ─────────────────────────────────────────────────

_IOKit.IOHIDManagerCreate.restype = ctypes.c_void_p
_IOKit.IOHIDManagerCreate.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_IOKit.IOHIDManagerSetDeviceMatchingMultiple.restype = None
_IOKit.IOHIDManagerSetDeviceMatchingMultiple.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_IOKit.IOHIDManagerRegisterInputValueCallback.restype = None
_IOKit.IOHIDManagerRegisterInputValueCallback.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
]
_IOKit.IOHIDManagerScheduleWithRunLoop.restype = None
_IOKit.IOHIDManagerScheduleWithRunLoop.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
]
_IOKit.IOHIDManagerUnscheduleFromRunLoop.restype = None
_IOKit.IOHIDManagerUnscheduleFromRunLoop.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
]
_IOKit.IOHIDManagerOpen.restype = ctypes.c_int
_IOKit.IOHIDManagerOpen.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_IOKit.IOHIDManagerClose.restype = ctypes.c_int
_IOKit.IOHIDManagerClose.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_IOKit.IOHIDValueGetElement.restype = ctypes.c_void_p
_IOKit.IOHIDValueGetElement.argtypes = [ctypes.c_void_p]
_IOKit.IOHIDValueGetIntegerValue.restype = ctypes.c_long
_IOKit.IOHIDValueGetIntegerValue.argtypes = [ctypes.c_void_p]
_IOKit.IOHIDElementGetUsagePage.restype = ctypes.c_uint32
_IOKit.IOHIDElementGetUsagePage.argtypes = [ctypes.c_void_p]
_IOKit.IOHIDElementGetUsage.restype = ctypes.c_uint32
_IOKit.IOHIDElementGetUsage.argtypes = [ctypes.c_void_p]

# ── CF/IOKit constants ────────────────────────────────────────────────────────

# kCFRunLoopDefaultMode is a CFStringRef global — read its pointer value.
_kCFRunLoopDefaultMode = ctypes.c_void_p.in_dll(_CF, "kCFRunLoopDefaultMode").value

# kCFType*CallBacks are structs — we need their addresses (not their values).
_kCFTypeDictKeyCallBacks = ctypes.c_char.in_dll(_CF, "kCFTypeDictionaryKeyCallBacks")
_kCFTypeDictValCallBacks = ctypes.c_char.in_dll(_CF, "kCFTypeDictionaryValueCallBacks")
_kCFTypeArrayCallBacks = ctypes.c_char.in_dll(_CF, "kCFTypeArrayCallBacks")

_kCFNumberSInt32Type = 3  # CFNumberType: kCFNumberSInt32Type

# IOKit device matching key strings (CFStringRef globals — read pointer values).
_kIOHIDDeviceUsagePageKey = ctypes.c_void_p.in_dll(_IOKit, "kIOHIDDeviceUsagePageKey").value
_kIOHIDDeviceUsageKey = ctypes.c_void_p.in_dll(_IOKit, "kIOHIDDeviceUsageKey").value

# HID usage pages
_HID_PAGE_GENERIC_DESKTOP = 0x01
_HID_PAGE_KEYBOARD = 0x07
_HID_PAGE_BUTTON = 0x09

# Generic Desktop usage IDs for device type matching and mouse axes
_HID_USAGE_MOUSE = 0x02
_HID_USAGE_KEYBOARD = 0x06
_HID_USAGE_X = 0x30
_HID_USAGE_Y = 0x31

# IOHIDValueCallback: void (*)(void *context, IOReturn result, void *sender, IOHIDValueRef value)
_IOHIDValueCallback = ctypes.CFUNCTYPE(
    None,
    ctypes.c_void_p,  # context
    ctypes.c_int,     # IOReturn result
    ctypes.c_void_p,  # sender
    ctypes.c_void_p,  # IOHIDValueRef value
)

# ── USB HID keyboard usage → (key_string, macOS_keycode) ─────────────────────
#
# key_string matches what NSEvent.charactersIgnoringModifiers() returns for the
# same physical key on a US QWERTY layout, so existing apps checking key strings
# work without modification.

_KEY_MAP: dict[int, tuple[str, int]] = {
    # Letters a–z
    0x04: ("a", 0x00), 0x05: ("b", 0x0B), 0x06: ("c", 0x08), 0x07: ("d", 0x02),
    0x08: ("e", 0x0E), 0x09: ("f", 0x03), 0x0A: ("g", 0x05), 0x0B: ("h", 0x04),
    0x0C: ("i", 0x22), 0x0D: ("j", 0x26), 0x0E: ("k", 0x28), 0x0F: ("l", 0x25),
    0x10: ("m", 0x2E), 0x11: ("n", 0x2D), 0x12: ("o", 0x1F), 0x13: ("p", 0x23),
    0x14: ("q", 0x0C), 0x15: ("r", 0x0F), 0x16: ("s", 0x01), 0x17: ("t", 0x11),
    0x18: ("u", 0x20), 0x19: ("v", 0x09), 0x1A: ("w", 0x0D), 0x1B: ("x", 0x07),
    0x1C: ("y", 0x10), 0x1D: ("z", 0x06),
    # Digits 1–0
    0x1E: ("1", 0x12), 0x1F: ("2", 0x13), 0x20: ("3", 0x14), 0x21: ("4", 0x15),
    0x22: ("5", 0x17), 0x23: ("6", 0x16), 0x24: ("7", 0x1A), 0x25: ("8", 0x1C),
    0x26: ("9", 0x19), 0x27: ("0", 0x1D),
    # Control / whitespace
    0x28: ("\r", 0x24),     # Return
    0x29: ("\x1b", 0x35),   # Escape
    0x2A: ("\x7f", 0x33),   # Backspace → macOS Delete
    0x2B: ("\t", 0x30),     # Tab
    0x2C: (" ", 0x31),      # Space
    # Punctuation
    0x2D: ("-", 0x1B), 0x2E: ("=", 0x18), 0x2F: ("[", 0x21), 0x30: ("]", 0x1E),
    0x31: ("\\", 0x2A), 0x33: (";", 0x29), 0x34: ("'", 0x27), 0x35: ("`", 0x32),
    0x36: (",", 0x2B), 0x37: (".", 0x2F), 0x38: ("/", 0x2C),
    # F-keys (NSFunctionKeyMask Unicode private-use area)
    0x3A: ("\xf704", 0x7A), 0x3B: ("\xf705", 0x78), 0x3C: ("\xf706", 0x63),
    0x3D: ("\xf707", 0x76), 0x3E: ("\xf708", 0x60), 0x3F: ("\xf709", 0x61),
    0x40: ("\xf70a", 0x62), 0x41: ("\xf70b", 0x64), 0x42: ("\xf70c", 0x65),
    0x43: ("\xf70d", 0x6D), 0x44: ("\xf70e", 0x67), 0x45: ("\xf70f", 0x6F),
    # Navigation
    0x4A: ("\xf729", 0x73),  # Home
    0x4B: ("\xf72C", 0x74),  # Page Up
    0x4C: ("\xf728", 0x75),  # Forward Delete
    0x4D: ("\xf72B", 0x77),  # End
    0x4E: ("\xf72D", 0x79),  # Page Down
    # Arrow keys
    0x4F: ("\xf703", 0x7C),  # Right
    0x50: ("\xf702", 0x7B),  # Left
    0x51: ("\xf701", 0x7D),  # Down
    0x52: ("\xf700", 0x7E),  # Up
    # Modifiers — named strings so hold/double detection works
    0x39: ("caps_lock", 0x39),
    0xE0: ("ctrl",  0x3B), 0xE1: ("shift", 0x38), 0xE2: ("opt", 0x3A), 0xE3: ("cmd", 0x37),
    0xE4: ("ctrl",  0x3E), 0xE5: ("shift", 0x3C), 0xE6: ("opt", 0x3D), 0xE7: ("cmd", 0x36),
}

# ── CF helpers ────────────────────────────────────────────────────────────────

def _cf_number(value: int) -> int:
    """Create a CFNumber (SInt32). Caller must CFRelease."""
    buf = ctypes.c_int32(value)
    return int(_CF.CFNumberCreate(None, _kCFNumberSInt32Type, ctypes.byref(buf)))


def _matching_dict(usage_page: int, usage: int) -> int:
    """Create an IOKit device-matching CFDictionary. Caller must CFRelease."""
    page_num = _cf_number(usage_page)
    usage_num = _cf_number(usage)
    keys_arr = (ctypes.c_void_p * 2)(_kIOHIDDeviceUsagePageKey, _kIOHIDDeviceUsageKey)
    vals_arr = (ctypes.c_void_p * 2)(page_num, usage_num)
    d = int(_CF.CFDictionaryCreate(
        None,
        ctypes.cast(keys_arr, ctypes.c_void_p),
        ctypes.cast(vals_arr, ctypes.c_void_p),
        2,
        ctypes.addressof(_kCFTypeDictKeyCallBacks),
        ctypes.addressof(_kCFTypeDictValCallBacks),
    ))
    _CF.CFRelease(page_num)
    _CF.CFRelease(usage_num)
    return d


def _cf_array(items: list[int]) -> int:
    """Create a CFArray of CF objects. Caller must CFRelease."""
    arr = (ctypes.c_void_p * len(items))(*items)
    return int(_CF.CFArrayCreate(
        None,
        ctypes.cast(arr, ctypes.c_void_p),
        len(items),
        ctypes.addressof(_kCFTypeArrayCallBacks),
    ))

# ── IOKitHIDSource ────────────────────────────────────────────────────────────


class IOKitHIDSource:
    """
    Delivers keyboard and mouse events directly from the IOKit HID layer,
    bypassing WindowServer. Runs an IOHIDManager on a dedicated CFRunLoop thread
    so callbacks fire at hardware report rate.

    Mouse position is accumulated from relative deltas. Call calibrate_position()
    with a known screen coordinate (e.g. from NSEvent.mouseLocation()) after
    startup and after window activation to prevent drift.

    IOKit captures input globally (not limited to the active app). The caller is
    responsible for discarding events accumulated while its window was inactive;
    see drain_events() notes below.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: deque[HDIEvent] = deque()
        self._next_id = 1_000_000  # distinct from NSEvent source IDs
        # Screen position in NSEvent bottom-left coordinates.
        self._screen_x = 0.0
        self._screen_y = 0.0
        self._buttons_mask = 0
        self._run_loop: int | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        # Keep callback alive for the lifetime of this object (ctypes CFUNCTYPE GC guard).
        self._callback_ref: _IOHIDValueCallback | None = None
        self._manager: int = self._create_manager()

    def _create_manager(self) -> int:
        mgr = int(_IOKit.IOHIDManagerCreate(None, 0))
        if not mgr:
            raise RuntimeError("IOHIDManagerCreate returned NULL")
        kb_dict = _matching_dict(_HID_PAGE_GENERIC_DESKTOP, _HID_USAGE_KEYBOARD)
        ms_dict = _matching_dict(_HID_PAGE_GENERIC_DESKTOP, _HID_USAGE_MOUSE)
        device_list = _cf_array([kb_dict, ms_dict])
        _IOKit.IOHIDManagerSetDeviceMatchingMultiple(mgr, device_list)
        _CF.CFRelease(device_list)
        _CF.CFRelease(kb_dict)
        _CF.CFRelease(ms_dict)
        cb = _IOHIDValueCallback(self._on_value)
        self._callback_ref = cb
        _IOKit.IOHIDManagerRegisterInputValueCallback(mgr, cb, None)
        return mgr

    def _on_value(self, context: int, result: int, sender: int, value_ref: int) -> None:
        try:
            elem = _IOKit.IOHIDValueGetElement(value_ref)
            if not elem:
                return
            page = int(_IOKit.IOHIDElementGetUsagePage(elem))
            usage = int(_IOKit.IOHIDElementGetUsage(elem))
            int_val = int(_IOKit.IOHIDValueGetIntegerValue(value_ref))
            ts_ns = time.time_ns()

            if page == _HID_PAGE_KEYBOARD:
                mapping = _KEY_MAP.get(usage)
                if mapping is None:
                    return
                key_str, mac_code = mapping
                ev = HDIEvent(
                    event_id=0,  # assigned in drain_events
                    ts_ns=ts_ns,
                    window_id="",
                    device="keyboard",
                    event_type="key_down" if int_val else "key_up",
                    status="OK",
                    payload={"key": key_str, "code": mac_code},
                )
                with self._lock:
                    self._queue.append(ev)

            elif page == _HID_PAGE_GENERIC_DESKTOP:
                if usage == _HID_USAGE_X:
                    with self._lock:
                        self._screen_x += float(int_val)
                elif usage == _HID_USAGE_Y:
                    # IOKit Y: positive = physically down → NSEvent Y (bottom-left) decreases.
                    with self._lock:
                        self._screen_y -= float(int_val)

            elif page == _HID_PAGE_BUTTON:
                button_idx = usage - 1
                if button_idx > 7:
                    return
                bit = 1 << button_idx
                with self._lock:
                    old_mask = self._buttons_mask
                    if int_val:
                        self._buttons_mask |= bit
                        changed = not bool(old_mask & bit)
                    else:
                        self._buttons_mask &= ~bit
                        changed = bool(old_mask & bit)
                    if changed:
                        sx, sy = self._screen_x, self._screen_y
                        ev = HDIEvent(
                            event_id=0,  # assigned in drain_events
                            ts_ns=ts_ns,
                            window_id="",
                            device="mouse",
                            event_type="click",
                            status="OK",
                            payload={
                                "screen_x": sx,
                                "screen_y": sy,
                                "button": button_idx,
                                "phase": "down" if int_val else "up",
                                "click_count": 1,
                            },
                        )
                        self._queue.append(ev)
        except Exception:
            pass

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._thread_main,
            name="luvatrix-iohid",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def _thread_main(self) -> None:
        rl = _CF.CFRunLoopGetCurrent()
        self._run_loop = rl
        _IOKit.IOHIDManagerScheduleWithRunLoop(self._manager, rl, _kCFRunLoopDefaultMode)
        _IOKit.IOHIDManagerOpen(self._manager, 0)
        self._ready.set()
        _CF.CFRunLoopRun()  # blocks until stop() calls CFRunLoopStop
        _IOKit.IOHIDManagerUnscheduleFromRunLoop(self._manager, rl, _kCFRunLoopDefaultMode)
        _IOKit.IOHIDManagerClose(self._manager, 0)

    def stop(self) -> None:
        if self._run_loop is not None:
            _CF.CFRunLoopStop(self._run_loop)
            self._run_loop = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def drain_events(self) -> list[HDIEvent]:
        """
        Return and clear all pending events. Does NOT assign window_id or
        final event_ids — the caller (MacOSWindowHDISource) does that.

        Call drain_events() and discard the result whenever the window
        transitions from inactive to active to flush stale events that arrived
        while another app was in focus.
        """
        with self._lock:
            out = list(self._queue)
            self._queue.clear()
            return out

    def calibrate_position(self, screen_x: float, screen_y: float) -> None:
        """Synchronise the accumulated screen position to a known coordinate."""
        with self._lock:
            self._screen_x = float(screen_x)
            self._screen_y = float(screen_y)

    def current_screen_xy(self) -> tuple[float, float]:
        """Latest accumulated mouse position in NSEvent screen coordinates (bottom-left origin)."""
        with self._lock:
            return (self._screen_x, self._screen_y)

    def current_buttons_mask(self) -> int:
        with self._lock:
            return self._buttons_mask
