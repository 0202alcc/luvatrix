"""Native controls: host-platform UI widgets embedded in a luvatrix window.

Apps render through the scene graph, but some components — text fields above
all — are better served by the OS-native control: real IME, spellcheck,
pasteboard, focus rings, and accessibility. A native-control bridge creates
and positions those controls over the render surface and bridges value
changes back into app state.

Platform targets create a bridge when their window starts and register it
here; apps reach it through ``luvatrix.app.native_controls()``. Where no
bridge exists (headless, web, or an unsupported host), apps keep their drawn
components — see ``NullNativeControlBridge``.

Two input conflicts are solved by ``GatedHDIEventSource``: keyboard events
must not reach the app while a native control is first responder, and pointer
events inside a native control's frame must not also trigger scene hits.
"""
from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from luvatrix_core.core.hdi_thread import HDIEvent, HDIEventSource


@runtime_checkable
class NativeInputGate(Protocol):
    """Decides which HDI events a native-control layer claims."""

    def suppress_keyboard(self) -> bool:
        """True while app-level keyboard handling must stay silent."""
        ...

    def consume_point(self, x: float, y: float) -> bool:
        """True when a window-local top-left point lands on a native control."""
        ...


class GatedHDIEventSource(HDIEventSource):
    """Wraps an HDI source and drops events claimed by native controls.

    Pointer *moves* always pass (hover feedback is harmless); keyboard events
    drop while the gate suppresses them; click and scroll events drop at
    points the gate consumes. A failing gate fails open so input is never
    silently eaten.
    """

    def __init__(self, source: HDIEventSource, gate: NativeInputGate) -> None:
        self._source = source
        self._gate = gate

    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        events = self._source.poll(window_active, ts_ns)
        try:
            suppress_keyboard = bool(self._gate.suppress_keyboard())
        except Exception:
            suppress_keyboard = False
        out: list[HDIEvent] = []
        for event in events:
            if suppress_keyboard and event.device == "keyboard":
                continue
            if event.event_type in ("click", "scroll"):
                payload = event.payload
                if isinstance(payload, dict):
                    try:
                        consumed = bool(
                            self._gate.consume_point(
                                float(payload.get("x", 0.0)), float(payload.get("y", 0.0))
                            )
                        )
                    except Exception:
                        consumed = False
                    if consumed:
                        continue
            out.append(event)
        return out

    def close(self) -> None:
        close_source = getattr(self._source, "close", None)
        if callable(close_source):
            close_source()
        close_gate = getattr(self._gate, "close", None)
        if callable(close_gate):
            close_gate()


@runtime_checkable
class NativeTextField(Protocol):
    """Handle for one embedded native text field.

    Coordinates are window-local, top-left origin, logical points — the same
    space the scene graph uses. All methods must be called on the main thread.
    """

    @property
    def value(self) -> str: ...

    def set_value(self, value: str) -> None: ...

    def set_frame(self, x: float, y: float, width: float, height: float) -> None: ...

    def show(self) -> None: ...

    def hide(self) -> None: ...

    @property
    def is_visible(self) -> bool: ...

    def focus(self) -> None: ...

    def resign(self) -> None: ...

    def destroy(self) -> None: ...


@runtime_checkable
class NativeGlassSurface(Protocol):
    """Handle for one embedded native glass/material surface.

    Decorative material plate (Liquid Glass on macOS 26+, vibrancy below)
    placed over the render surface. Coordinates are window-local, top-left
    origin, logical points. Glass surfaces never consume input — the bridge
    gate only claims points inside interactive controls.
    """

    @property
    def frame(self) -> tuple[float, float, float, float]: ...

    def set_frame(self, x: float, y: float, width: float, height: float) -> None: ...

    def show(self) -> None: ...

    def hide(self) -> None: ...

    @property
    def is_visible(self) -> bool: ...

    def set_corner_radius(self, radius: float) -> None:
        """Update the plate's corner radius (dynamic silhouettes, e.g. the
        Liquid Glass size rule flipping a tall pill to a rounded rect)."""
        ...

    def destroy(self) -> None: ...


@runtime_checkable
class NativeButton(Protocol):
    """Handle for one embedded native push button.

    Borderless, focus-ring-free button in the Liquid Glass family — typically
    parented inside a glass surface's content host. Coordinates are
    window-local, top-left origin, logical points.
    """

    @property
    def frame(self) -> tuple[float, float, float, float]: ...

    def set_frame(self, x: float, y: float, width: float, height: float) -> None: ...

    def show(self) -> None: ...

    def hide(self) -> None: ...

    @property
    def is_visible(self) -> bool: ...

    def set_enabled(self, enabled: bool) -> None: ...

    def destroy(self) -> None: ...


@runtime_checkable
class NativeWebView(Protocol):
    """Handle for one embedded native web view (e.g. WKWebView).

    Used for embedded OAuth: the app loads the provider's authorize page, and
    the bridge cancels any navigation matching ``redirect_prefix`` and reports
    the full URL instead — credentials never touch app code. Coordinates are
    window-local, top-left origin, logical points.
    """

    @property
    def frame(self) -> tuple[float, float, float, float]: ...

    def load_url(self, url: str) -> None: ...

    @property
    def can_go_back(self) -> bool:
        """True when the view has page history to step back through."""
        ...

    def go_back(self) -> None:
        """Step back one page in the view's history (no-op when none)."""
        ...

    def set_frame(self, x: float, y: float, width: float, height: float) -> None: ...

    def show(self) -> None: ...

    def hide(self) -> None: ...

    @property
    def is_visible(self) -> bool: ...

    def destroy(self) -> None: ...


@runtime_checkable
class NativeControlBridge(Protocol):
    """Factory + input gate for native controls over one window."""

    @property
    def available(self) -> bool:
        """False when the host cannot embed native controls right now."""
        ...

    @property
    def supports_under_glass(self) -> bool:
        """True when a glass surface can sit BELOW the render surface.

        Requires the window's render-host split (the Metal layer lives on a
        host view) plus a presenter that honors a fully transparent clear by
        making the layer and window see-through. Only then does
        ``placement="under"`` show real material instead of hiding behind an
        opaque render layer."""
        ...

    def create_web_view(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        redirect_prefix: str = "",
        on_redirect: Callable[[str], None] | None = None,
        on_navigation_state: Callable[[], None] | None = None,
    ) -> NativeWebView: ...

    def create_button(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        title: str,
        within: NativeGlassSurface | None = None,
        on_press: Callable[[], None] | None = None,
    ) -> NativeButton: ...

    def create_text_field(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        placeholder: str = "",
        value: str = "",
        secure: bool = False,
        within: NativeGlassSurface | None = None,
        bordered: bool = True,
        on_change: Callable[[str], None] | None = None,
        on_submit: Callable[[str], None] | None = None,
    ) -> NativeTextField: ...

    def create_glass_surface(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        corner_radius: float = 0.0,
        style: str = "regular",
        placement: str = "above",
    ) -> NativeGlassSurface:
        """``placement="above"`` composites the plate over the render surface
        (it blurs scene content beneath — fine behind native controls).
        ``placement="under"`` slots it below the render surface so scene
        content draws crisply on top; requires ``supports_under_glass``."""
        ...

    def close(self) -> None: ...


class _NullTextField:
    """In-memory stand-in so app code can hold a handle without capability checks."""

    def __init__(self, *, x, y, width, height, placeholder, value, on_change, on_submit) -> None:
        self.frame = (x, y, width, height)
        self.placeholder = placeholder
        self._value = value
        self._on_change = on_change
        self._on_submit = on_submit
        self.is_visible = True
        self.destroyed = False

    @property
    def value(self) -> str:
        return self._value

    def set_value(self, value: str) -> None:
        self._value = value
        if self._on_change is not None:
            self._on_change(value)

    def set_frame(self, x: float, y: float, width: float, height: float) -> None:
        self.frame = (x, y, width, height)

    def show(self) -> None:
        self.is_visible = True

    def hide(self) -> None:
        self.is_visible = False

    def focus(self) -> None:
        pass

    def resign(self) -> None:
        pass

    def destroy(self) -> None:
        self.destroyed = True


class _NullGlassSurface:
    """In-memory stand-in for a glass surface on unsupported hosts."""

    def __init__(self, *, x, y, width, height, corner_radius=0.0, style="regular",
                 placement="above") -> None:
        self.frame = (x, y, width, height)
        self.corner_radius = corner_radius
        self.style = style
        self.placement = placement
        self.is_visible = True
        self.destroyed = False

    def set_frame(self, x: float, y: float, width: float, height: float) -> None:
        self.frame = (x, y, width, height)

    def set_corner_radius(self, radius: float) -> None:
        self.corner_radius = radius

    def show(self) -> None:
        self.is_visible = True

    def hide(self) -> None:
        self.is_visible = False

    def destroy(self) -> None:
        self.destroyed = True


class _NullNativeButton:
    """In-memory stand-in for a native button on unsupported hosts."""

    def __init__(self, *, x, y, width, height, title, on_press) -> None:
        self.frame = (x, y, width, height)
        self.title = title
        self._on_press = on_press
        self.is_visible = True
        self.enabled = True
        self.destroyed = False

    def set_frame(self, x: float, y: float, width: float, height: float) -> None:
        self.frame = (x, y, width, height)

    def show(self) -> None:
        self.is_visible = True

    def hide(self) -> None:
        self.is_visible = False

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def press(self) -> None:
        if self.enabled and self._on_press is not None:
            self._on_press()

    def destroy(self) -> None:
        self.destroyed = True


class _NullWebView:
    """In-memory stand-in for a web view on unsupported hosts."""

    def __init__(self, *, x, y, width, height, redirect_prefix, on_redirect,
                 on_navigation_state=None) -> None:
        self.frame = (x, y, width, height)
        self.redirect_prefix = redirect_prefix
        self._on_redirect = on_redirect
        self._on_navigation_state = on_navigation_state
        self.is_visible = True
        self.destroyed = False
        self.loaded_urls: list[str] = []

    def load_url(self, url: str) -> None:
        self.loaded_urls.append(url)

    @property
    def can_go_back(self) -> bool:
        return False

    def go_back(self) -> None:
        pass

    def set_frame(self, x: float, y: float, width: float, height: float) -> None:
        self.frame = (x, y, width, height)

    def show(self) -> None:
        self.is_visible = True

    def hide(self) -> None:
        self.is_visible = False

    def destroy(self) -> None:
        self.destroyed = True


class NullNativeControlBridge:
    """Bridge for hosts without native-control support.

    ``available`` is False so apps keep their drawn components; handles are
    inert in-memory stubs so defensive app code never crashes.
    """

    @property
    def available(self) -> bool:
        return False

    @property
    def supports_under_glass(self) -> bool:
        return False

    def create_web_view(self, **kwargs) -> _NullWebView:
        return _NullWebView(
            x=kwargs.get("x", 0.0),
            y=kwargs.get("y", 0.0),
            width=kwargs.get("width", 0.0),
            height=kwargs.get("height", 0.0),
            redirect_prefix=kwargs.get("redirect_prefix", ""),
            on_redirect=kwargs.get("on_redirect"),
            on_navigation_state=kwargs.get("on_navigation_state"),
        )

    def create_button(self, **kwargs) -> _NullNativeButton:
        return _NullNativeButton(
            x=kwargs.get("x", 0.0),
            y=kwargs.get("y", 0.0),
            width=kwargs.get("width", 0.0),
            height=kwargs.get("height", 0.0),
            title=kwargs.get("title", ""),
            on_press=kwargs.get("on_press"),
        )

    def create_text_field(self, **kwargs) -> _NullTextField:
        return _NullTextField(
            x=kwargs.get("x", 0.0),
            y=kwargs.get("y", 0.0),
            width=kwargs.get("width", 0.0),
            height=kwargs.get("height", 0.0),
            placeholder=kwargs.get("placeholder", ""),
            value=kwargs.get("value", ""),
            on_change=kwargs.get("on_change"),
            on_submit=kwargs.get("on_submit"),
        )

    def create_glass_surface(self, **kwargs) -> _NullGlassSurface:
        return _NullGlassSurface(
            x=kwargs.get("x", 0.0),
            y=kwargs.get("y", 0.0),
            width=kwargs.get("width", 0.0),
            height=kwargs.get("height", 0.0),
            corner_radius=kwargs.get("corner_radius", 0.0),
            style=kwargs.get("style", "regular"),
            placement=kwargs.get("placement", "above"),
        )

    def suppress_keyboard(self) -> bool:
        return False

    def consume_point(self, x: float, y: float) -> bool:
        return False

    def close(self) -> None:
        pass


_active_bridge: NativeControlBridge | NullNativeControlBridge | None = None


def register_native_control_bridge(bridge: NativeControlBridge | NullNativeControlBridge) -> None:
    global _active_bridge
    _active_bridge = bridge


def unregister_native_control_bridge(bridge: object | None = None) -> None:
    global _active_bridge
    if bridge is None or _active_bridge is bridge:
        _active_bridge = None


def active_native_control_bridge() -> NativeControlBridge | NullNativeControlBridge | None:
    """The bridge for the currently running window, if a target registered one.

    Apps must still check ``bridge.available`` — a bridge whose window was
    destroyed reports False until the next target start re-registers.
    """
    return _active_bridge
