"""Live layout overrides for Spotify Light (MCP surface, round 31).

Alec's layout-tool loop: nudge chrome positions on the RUNNING app over MCP,
then export the overrides for baking into the layout constants. Addressable
components: the playback pill, the nav circles (home/search/more), and the
sidebar rail. Overrides are session-scoped (fresh on every boot, no
persistence), win over the app's own per-frame layout recomputation, clamp
to the window, and refuse unknown ids with a useful error.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "examples" / "spotify_light"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from luvatrix_core.core.mcp_runtime import MCP_CAPABILITIES, McpRuntimeBridge  # noqa: E402
from luvatrix_core.core.scene_graph import (  # noqa: E402
    RectNode,
    RoundedRectNode,
    SceneGraphBuffer,
    TextNode,
)

import app_main  # noqa: E402
import sl_layout  # noqa: E402
import sl_models  # noqa: E402
import sl_views  # noqa: E402

from test_spotify_light_app import _album, _artist, _nodes, _runtime, _tick, _track  # noqa: E402


@pytest.fixture
def app_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("SPOTIFY_LIGHT_CONFIG_DIR", str(tmp_path))
    scene_buffer = SceneGraphBuffer()
    runtime = _runtime(scene_buffer)
    ctx = runtime.build_context({"window.write", "hdi.keyboard", "hdi.mouse", "hdi.trackpad"})
    app = app_main.create()
    app.init(ctx)
    yield app, ctx, scene_buffer
    app.teardown()


def _with_track(app, ctx):
    app.authenticated = True
    artist = _artist("Nirvana")
    track = _track("Lithium", artist, _album("Nevermind", artist), ms=257_000)
    app.player = sl_models.PlayerState(is_playing=True, progress_ms=30_500,
                                       track=track, device=None, shuffle=False,
                                       repeat="off")
    app._player_synced_at = app.now_monotonic
    _tick(app, ctx, 2)


def _pill_ring(scene_buffer):
    rings = [n for n in _nodes(scene_buffer, RoundedRectNode)
             if n.color_rgba == sl_views.PILL_BORDER]
    assert len(rings) == 1, "expected exactly one pill ring"
    return rings[0]


def _bridge(app):
    return McpRuntimeBridge(
        app_id="test.spotify-light",
        granted_capabilities=set(MCP_CAPABILITIES),
        state_provider=lambda: {},
        app_call_timeout_s=5.0,
    )


class _Drain:
    """Run bridge.drain_app_calls on a thread, like the MCP server does."""

    def __init__(self, bridge):
        self._bridge = bridge
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        import time

        while not self._stop.is_set():
            self._bridge.drain_app_calls()
            time.sleep(0.005)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=2)


# ---------------------------------------------------------------------------
# Spec validation, anchor math, clamping, export (unit level)
# ---------------------------------------------------------------------------

class TestLayoutSpecValidation:
    NATURAL = (744.0, 16.0, 520.0, 108.0)  # the pill at 1280x800

    def test_explicit_rect_resolves_verbatim(self):
        ov = sl_layout.LayoutOverrides()
        ov.set("pill", {"rect": {"x": 100, "y": 120, "width": 300, "height": 64}})
        assert ov.resolve("pill", self.NATURAL, width=1280, height=800) == \
            (100.0, 120.0, 300.0, 64.0)

    def test_anchor_math_all_anchors(self):
        ov = sl_layout.LayoutOverrides()
        _, _, w, h = self.NATURAL
        cases = {
            "top-left": (40.0, 100.0),
            "top-right": (1280.0 - 40 - w, 100.0),
            "bottom-left": (40.0, 800.0 - 100 - h),
            "bottom-right": (1280.0 - 40 - w, 800.0 - 100 - h),
            "center": (1280.0 / 2 - w / 2 + 40, 800.0 / 2 - h / 2 + 100),
        }
        for anchor, (want_x, want_y) in cases.items():
            ov.set("pill", {"anchor": anchor, "dx": 40, "dy": 100})
            got = ov.resolve("pill", self.NATURAL, width=1280, height=800)
            assert got == pytest.approx((want_x, want_y, w, h)), anchor

    def test_anchor_size_override_grows_from_the_anchor(self):
        """A width override under a right anchor grows the rect leftward."""
        ov = sl_layout.LayoutOverrides()
        ov.set("pill", {"anchor": "top-right", "dx": 16, "dy": 16, "width": 300})
        assert ov.resolve("pill", self.NATURAL, width=1280, height=800) == \
            (964.0, 16.0, 300.0, self.NATURAL[3])

    def test_unset_component_resolves_natural(self):
        ov = sl_layout.LayoutOverrides()
        assert ov.resolve("pill", self.NATURAL, width=1280, height=800) == self.NATURAL

    def test_unknown_id_error_lists_valid_ids(self):
        ov = sl_layout.LayoutOverrides()
        with pytest.raises(sl_layout.LayoutError) as exc:
            ov.set("player_bar", {"anchor": "top-left"})
        msg = str(exc.value)
        assert "player_bar" in msg
        for valid in sl_layout.COMPONENT_IDS:
            assert valid in msg, "the error must name the valid ids"

    def test_bad_values_raise_never_store(self):
        ov = sl_layout.LayoutOverrides()
        bad_specs = [
            {"anchor": "upper-left"},                       # unknown anchor
            {"anchor": "top-left", "dx": "banana"},         # non-numeric
            {"anchor": "top-left", "dy": float("nan")},     # NaN
            {"anchor": "top-left", "width": 0},             # degenerate size
            {"anchor": "top-left", "height": -10},
            {"anchor": "top-left",
             "rect": {"x": 0, "y": 0, "width": 10, "height": 10}},  # both shapes
            {"dx": 5},                                       # neither shape
            {"rect": {"x": 0, "y": 0, "width": "wide", "height": 4}},
            {"rect": {"x": 0, "y": 0, "width": 10}},         # missing key
        ]
        for spec in bad_specs:
            with pytest.raises(sl_layout.LayoutError):
                ov.set("pill", spec)
        assert len(ov) == 0, "a rejected spec must never reach the registry"

    def test_clamps_into_window_bounds(self):
        ov = sl_layout.LayoutOverrides()
        ov.set("pill", {"rect": {"x": 1200, "y": 780, "width": 200, "height": 64}})
        assert ov.resolve("pill", self.NATURAL, width=1280, height=800) == \
            (1080.0, 736.0, 200.0, 64.0), "offscreen edges clamp back inside"
        ov.set("pill", {"rect": {"x": -50, "y": -20, "width": 460, "height": 64}})
        assert ov.resolve("pill", self.NATURAL, width=1280, height=800) == \
            (0.0, 0.0, 460.0, 64.0)
        ov.set("pill", {"anchor": "top-right", "dx": 5000, "dy": 16})
        got = ov.resolve("pill", self.NATURAL, width=1280, height=800)
        assert got[0] == 0.0 and got[2] == self.NATURAL[2], \
            "an absurd anchor offset clamps, not crashes"
        ov.set("pill", {"rect": {"x": 100, "y": 0, "width": 5000, "height": 64}})
        got = ov.resolve("pill", self.NATURAL, width=1280, height=800)
        assert got[2] <= 1280.0 and got[0] == 0.0, "oversize width shrinks to the window"

    def test_clear_one_keeps_others_clear_all_empties(self):
        ov = sl_layout.LayoutOverrides()
        ov.set("pill", {"anchor": "top-left", "dx": 1, "dy": 1})
        ov.set("nav_home", {"anchor": "top-left", "dx": 2, "dy": 2})
        assert ov.clear("pill") == ["pill"]
        assert ov.resolve("pill", self.NATURAL, width=1280, height=800) == self.NATURAL
        assert len(ov) == 1, "clearing one must keep the other"
        assert ov.clear() == ["nav_home"], "clear with no id clears everything left"
        assert len(ov) == 0

    def test_clear_unknown_id_is_an_error_listing_valid_ids(self):
        ov = sl_layout.LayoutOverrides()
        with pytest.raises(sl_layout.LayoutError) as exc:
            ov.clear("nope")
        assert "nope" in str(exc.value)

    def test_export_round_trip_preserves_resolved_geometry(self):
        ov = sl_layout.LayoutOverrides()
        ov.set("pill", {"anchor": "top-right", "dx": 40, "dy": 24})
        ov.set("nav_home", {"rect": {"x": 300, "y": 700, "width": 44, "height": 44}})
        naturals = {"pill": (744.0, 16.0, 520.0, 108.0), "nav_home": (468.0, 730.0, 44.0, 44.0)}
        before = {cid: ov.resolve(cid, naturals[cid], width=1280, height=800)
                  for cid in naturals}
        dumped = ov.export(width=1280, height=800, naturals=naturals)
        json.dumps(dumped)  # must be JSON-serializable for the bake path
        assert dumped["overrides"]["pill"]["anchor"] == "top-right"
        assert dumped["resolved"]["pill"] == list(before["pill"])
        fresh = sl_layout.LayoutOverrides()
        for cid, spec in dumped["overrides"].items():
            fresh.set(cid, spec)
        for cid, rect in before.items():
            assert fresh.resolve(cid, naturals[cid], width=1280, height=800) == \
                pytest.approx(rect), f"round-trip changed {cid}"


# ---------------------------------------------------------------------------
# MCP surface: tools, live application, precedence, clear semantics
# ---------------------------------------------------------------------------

class TestLayoutMcpSurface:

    def test_hooks_register_the_layout_tools(self, app_ctx):
        app, _, _ = app_ctx
        bridge = _bridge(app)
        assert bridge.register_app_hooks(app) == 6, \
            "two client-id tools plus layout_set/list/clear/export"
        listing = bridge.dispatcher().handle_payload(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        wire = {tool["name"]: tool for tool in listing["result"]["tools"]}
        for name in ("layout_set", "layout_list", "layout_clear", "layout_export"):
            assert name in wire, f"missing MCP tool {name}"
        assert "id" in wire["layout_set"]["inputSchema"]["properties"]

    def test_layout_set_moves_the_pill_live(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        result = app.mcp_call("layout_set", {
            "id": "pill", "rect": {"x": 100, "y": 120, "width": 300, "height": 64}})
        assert result["rect"] == [100.0, 120.0, 300.0, 64.0]
        _tick(app, ctx, 2)
        ring = _pill_ring(buf)
        assert (ring.x, ring.y, ring.width, ring.height) == (100.0, 120.0, 300.0, 64.0)
        hits = {r.action: r for r in app._hits}
        col_x, col_w, _ = sl_views.pill_column(300.0, 64.0)
        assert (hits["toggle_play"].x, hits["toggle_play"].y) == \
            (100 + col_x + col_w / 2 - 18, 120 + 69), \
            "the pill's hit regions ride the override"

    def test_overrides_win_over_app_state_recomputation(self, app_ctx):
        """State changes recompute layout from constants every frame — an
        override must survive view switches, playback changes, and (for
        explicit rects) window resizes."""
        app, ctx, buf = app_ctx
        app.authenticated = True
        _tick(app, ctx, 1)
        app.mcp_call("layout_set", {
            "id": "pill", "rect": {"x": 500, "y": 200, "width": 460, "height": 64}})
        for view in ("library", "search", "home"):
            app.view = view
            _tick(app, ctx, 1)
        _with_track(app, ctx)  # playback state changes under the override
        ctx.logical_width_px = 1000.0
        app.invalidate()  # stands in for the OS resize event
        _tick(app, ctx, 2)
        ring = _pill_ring(buf)
        assert (ring.x, ring.y, ring.width, ring.height) == (500.0, 200.0, 460.0, 64.0), \
            "view switches, playback, and resize must not stomp an explicit override"

    def test_anchor_overrides_re_resolve_against_window_size(self, app_ctx):
        app, ctx, buf = app_ctx
        app.authenticated = True
        app.mcp_call("layout_set", {"id": "pill", "anchor": "top-right", "dx": 16, "dy": 16})
        _tick(app, ctx, 2)
        assert _pill_ring(buf).x == 1280.0 - 16 - sl_views.PILL_W
        ctx.logical_width_px = 1000.0
        app.invalidate()  # stands in for the OS resize event
        _tick(app, ctx, 2)
        assert _pill_ring(buf).x == 1000.0 - 16 - sl_views.PILL_W, \
            "anchored overrides follow the window — the anchor IS the override"

    def test_nav_circles_and_sidebar_move(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        app.mcp_call("layout_set", {
            "id": "nav_home", "rect": {"x": 600, "y": 300, "width": 44, "height": 44}})
        app.mcp_call("layout_set", {
            "id": "nav_more", "rect": {"x": 660, "y": 300, "width": 44, "height": 44}})
        app.mcp_call("layout_set", {
            "id": "sidebar", "rect": {"x": 30, "y": 24, "width": 240, "height": 752}})
        _tick(app, ctx, 2)
        home = next(r for r in app._hits if r.action == "nav" and r.payload == "home")
        assert (home.x, home.y) == (600.0, 300.0)
        overflow = next(r for r in app._hits if r.action == "open_devices")
        assert (overflow.x, overflow.y) == (660.0, 300.0)
        rings = [n for n in _nodes(buf, RoundedRectNode)
                 if n.color_rgba == sl_views.GLASS_BORDER
                 and (n.x, n.y, n.width, n.height) == (30.0, 24.0, 240.0, 752.0)]
        assert rings, "the floating glass rail rides the override"
        labels = [n for n in _nodes(buf, TextNode) if n.text == "Your Library"]
        assert labels and labels[0].x == 22.0 + (30.0 - sl_views.SIDEBAR_GLASS_MARGIN), \
            "sidebar contents shift with the rail by the delta from its natural origin"

    def test_sidebar_natural_rect_is_the_floating_rail(self, app_ctx):
        app, ctx, _buf = app_ctx
        natural = app._layout_naturals(1280.0, 800.0)["sidebar"]
        m = sl_views.SIDEBAR_GLASS_MARGIN
        assert natural == (m, m, sl_views.SIDEBAR_W - 2 * m, 800.0 - 2 * m), \
            "the overridable sidebar natural tracks the floating liquid-glass rail"

    def test_layout_clear_restores_natural_geometry(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        natural = sl_views.pill_rect(1280, 800)
        app.mcp_call("layout_set", {
            "id": "pill", "rect": {"x": 100, "y": 120, "width": 300, "height": 64}})
        _tick(app, ctx, 1)
        cleared = app.mcp_call("layout_clear", {"id": "pill"})
        assert cleared["cleared"] == ["pill"]
        _tick(app, ctx, 2)
        ring = _pill_ring(buf)
        assert (ring.x, ring.y, ring.width, ring.height) == natural
        app.mcp_call("layout_set", {"id": "pill", "anchor": "top-left", "dx": 5, "dy": 5})
        app.mcp_call("layout_set", {"id": "nav_home", "anchor": "top-left", "dx": 9, "dy": 9})
        cleared = app.mcp_call("layout_clear", {})
        assert sorted(cleared["cleared"]) == ["nav_home", "pill"], "clear with no id clears all"

    def test_overrides_die_with_the_session(self, app_ctx):
        """Clear-on-boot: re-initializing the app (a new session) drops every
        override — there is no persistence file to resurrect them."""
        app, ctx, _ = app_ctx
        app.mcp_call("layout_set", {"id": "pill", "anchor": "top-left", "dx": 5, "dy": 5})
        assert app.mcp_call("layout_list", {})["overrides"], "override registered"
        app.init(ctx)  # reboot
        assert app.mcp_call("layout_list", {})["overrides"] == []

    def test_export_round_trip_over_the_wire(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        app.mcp_call("layout_set", {"id": "pill", "anchor": "top-right", "dx": 40, "dy": 24})
        app.mcp_call("layout_set", {
            "id": "nav_search", "rect": {"x": 900, "y": 700, "width": 44, "height": 44}})
        _tick(app, ctx, 2)
        pill_x_before = _pill_ring(buf).x
        exported = app.mcp_call("layout_export", {})
        json.dumps(exported)  # the bake path copies this JSON
        assert exported["window"] == {"width": 1280.0, "height": 800.0}
        app.mcp_call("layout_clear", {})
        _tick(app, ctx, 1)
        assert _pill_ring(buf).x == 744.0, "cleared overrides restore the natural layout"
        for cid, spec in exported["overrides"].items():
            app.mcp_call("layout_set", {"id": cid, **spec})
        _tick(app, ctx, 2)
        assert _pill_ring(buf).x == pill_x_before, "re-applying the export restores geometry"
        listing = app.mcp_call("layout_list", {})
        assert {o["id"] for o in listing["overrides"]} == {"pill", "nav_search"}

    def test_bad_set_never_crashes_and_scene_keeps_rendering(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        with pytest.raises(sl_layout.LayoutError) as exc:
            app.mcp_call("layout_set", {"id": "player_bar", "anchor": "top-left"})
        for valid in sl_layout.COMPONENT_IDS:
            assert valid in str(exc.value)
        with pytest.raises(sl_layout.LayoutError):
            app.mcp_call("layout_set", {"id": "pill", "anchor": "top-left", "dx": "banana"})
        _tick(app, ctx, 2)
        ring = _pill_ring(buf)
        assert (ring.x, ring.y) == (744.0, 16.0), \
            "a rejected spec must not disturb the running scene"

    def test_wire_round_trip_through_the_bridge(self, app_ctx):
        """End-to-end over JSON-RPC: tools/call queues on the server thread
        and executes between ticks on the runtime thread."""
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        bridge = _bridge(app)
        bridge.register_app_hooks(app)
        with _Drain(bridge):
            response = bridge.dispatcher().handle_payload(
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "layout_set",
                            "arguments": {"id": "pill", "anchor": "top-right",
                                          "dx": 80, "dy": 40}}})
            payload = json.loads(response["result"]["content"][0]["text"])
            assert payload["rect"] == [1280.0 - 80 - sl_views.PILL_W, 40.0,
                                       sl_views.PILL_W, sl_views.PILL_H]
            bad = bridge.dispatcher().handle_payload(
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "layout_set",
                            "arguments": {"id": "nope", "anchor": "top-left"}}})
            blob = json.dumps(bad)
            assert "nope" in blob and "pill" in blob, \
                "wire errors must carry the offender and the valid ids"
        _tick(app, ctx, 2)
        assert _pill_ring(buf).x == 1280.0 - 80 - sl_views.PILL_W
