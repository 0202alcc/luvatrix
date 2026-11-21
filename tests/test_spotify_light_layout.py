"""Live layout overrides for Spotify Light (MCP surface, round 31).

Alec's layout-tool loop: nudge chrome positions on the RUNNING app over MCP,
then export the overrides for baking into the layout constants. Addressable
components: the playback pill, the nav circles (home/search/more), and the
sidebar rail — plus, since round 33, the pill's interior (pill.art,
pill.progress, pill.transport) in pill-local space. Overrides persist to
the app's declarative layout file (round 36: layout_set/layout_clear write
through; setup() reads it at boot, so a nudge survives restart as an
ordinary git diff), win over the app's own per-frame layout recomputation,
clamp to the window (or the pill, for interior ids), and refuse unknown
ids with a useful error.
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
    CircleNode,
    CpuLayerNode,
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
    _redirect_layout_file(tmp_path, monkeypatch)
    scene_buffer = SceneGraphBuffer()
    runtime = _runtime(scene_buffer)
    ctx = runtime.build_context({"window.write", "hdi.keyboard", "hdi.mouse", "hdi.trackpad"})
    app = app_main.create()
    app.init(ctx)
    yield app, ctx, scene_buffer
    app.teardown()


def _redirect_layout_file(tmp_path, monkeypatch):
    """Point the persisted-layout file (round 36) at a tmp copy of the
    shipped one: boots see the baked specs, writes never touch the repo."""
    layout_file = tmp_path / "layout.toml"
    shipped = getattr(sl_layout, "APP_LAYOUT_FILE", None)
    if shipped is not None and Path(shipped).exists():
        layout_file.write_text(Path(shipped).read_text())
    monkeypatch.setenv("SPOTIFY_LIGHT_LAYOUT_FILE", str(layout_file))


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
    NATURAL = (692.0, 16.0, 572.0, 108.0)  # the pill at 1280x800 (SL-23)

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
        naturals = {"pill": (692.0, 16.0, 572.0, 108.0), "nav_home": (468.0, 730.0, 44.0, 44.0)}
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
        assert bridge.register_app_hooks(app) == 7, \
            "two client-id tools plus layout_set/align/list/clear/export"
        listing = bridge.dispatcher().handle_payload(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        wire = {tool["name"]: tool for tool in listing["result"]["tools"]}
        for name in ("layout_set", "layout_align", "layout_list", "layout_clear",
                     "layout_export"):
            assert name in wire, f"missing MCP tool {name}"
        assert "id" in wire["layout_set"]["inputSchema"]["properties"]
        for param in ("id", "edge", "to", "ref_edge", "offset"):
            assert param in wire["layout_align"]["inputSchema"]["properties"], \
                f"layout_align is missing the {param} param"

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
        assert (hits["toggle_play"].x, hits["toggle_play"].y) == \
            (100 + 300.0 / 2 - 18, 120 + 69), \
            "the pill's hit regions ride the override (play = pill center, SL-23)"

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
        app.mcp_call("layout_clear", {})  # isolate from the shipped nav_more entry
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

    def test_overrides_survive_reboot_via_the_layout_file(self, app_ctx):
        """Round 36 inverts the old session-scoped contract: a nudge persists
        to the layout file, so re-initializing the app (a reboot) resurrects
        it — and a persisted clear stays cleared."""
        app, ctx, _ = app_ctx
        app.mcp_call("layout_set", {"id": "pill", "anchor": "top-left", "dx": 5, "dy": 5})
        assert app.mcp_call("layout_list", {})["overrides"], "override registered"
        app.init(ctx)  # reboot
        ids = {o["id"] for o in app.mcp_call("layout_list", {})["overrides"]}
        assert "pill" in ids, "the persisted nudge must survive the reboot"
        app.mcp_call("layout_clear", {"id": "pill"})
        app.init(ctx)  # reboot again
        ids = {o["id"] for o in app.mcp_call("layout_list", {})["overrides"]}
        assert "pill" not in ids, "a persisted clear must stay cleared"

    def test_export_round_trip_over_the_wire(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        app.mcp_call("layout_clear", {})  # isolate from the shipped nav_more entry
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
        assert _pill_ring(buf).x == 692.0, "cleared overrides restore the natural layout"
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
        assert (ring.x, ring.y) == (692.0, 16.0), \
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


# ---------------------------------------------------------------------------
# Round 36 (Alec, SL-20): the nudge itself persists. layout_set/layout_clear
# write through to a declarative data file (sl_layout.APP_LAYOUT_FILE, TOML —
# the same file setup() reads at boot), so an MCP-moved component survives
# restart and shows up as an ordinary git diff. Specs persist in their
# resize-safe form (anchor + inward dx/dy); a raw rect is only the
# degenerate fallback. layout_export stays purely for inspection.
# ---------------------------------------------------------------------------

class TestLayoutPersistence:

    @staticmethod
    def _boot(tmp_path, monkeypatch, *, file_text: str | None):
        """Boot the app against a tmp layout file with the given contents
        (None = seeded from the shipped file, like app_ctx)."""
        monkeypatch.setenv("SPOTIFY_LIGHT_CONFIG_DIR", str(tmp_path))
        tmp_path.mkdir(parents=True, exist_ok=True)
        layout_file = tmp_path / "layout.toml"
        if file_text is None:
            shipped = sl_layout.APP_LAYOUT_FILE
            file_text = Path(shipped).read_text() if Path(shipped).exists() else ""
        layout_file.write_text(file_text)
        monkeypatch.setenv("SPOTIFY_LIGHT_LAYOUT_FILE", str(layout_file))
        scene_buffer = SceneGraphBuffer()
        ctx = _runtime(scene_buffer).build_context(
            {"window.write", "hdi.keyboard", "hdi.mouse", "hdi.trackpad"})
        app = app_main.create()
        app.init(ctx)
        return app, ctx, scene_buffer, layout_file

    def test_layout_set_writes_the_spec_to_the_layout_file(self, tmp_path, monkeypatch):
        app, ctx, _buf, layout_file = self._boot(tmp_path, monkeypatch, file_text=None)
        result = app.mcp_call("layout_set", {
            "id": "nav_home", "anchor": "bottom-right", "dx": 30, "dy": 40})
        assert result["persisted"] is True
        text = layout_file.read_text()
        assert '["nav_home"]' in text, "table headers quote the id (round 37: dotted ids)"
        assert 'anchor = "bottom-right"' in text
        assert "dx = 30.0" in text and "dy = 40.0" in text, \
            "the spec persists in its resize-safe anchor form, not as pixels"

    def test_persisted_specs_load_at_startup(self, tmp_path, monkeypatch):
        _, _, _, layout_file = self._boot(tmp_path, monkeypatch, file_text=None)
        layout_file.write_text(
            '[nav_home]\nanchor = "bottom-right"\ndx = 30.0\ndy = 40.0\n')
        app2, ctx2, _buf2, _ = self._boot(tmp_path / "second", monkeypatch,
                                          file_text=layout_file.read_text())
        _with_track(app2, ctx2)
        home = next(r for r in app2._hits if r.action == "nav" and r.payload == "home")
        assert (home.x, home.y) == (1280.0 - 30 - 44, 800.0 - 40 - 44), \
            "the rebooted app resolves the persisted spec, not the code natural"

    def test_persisted_anchor_spec_is_resize_safe(self, tmp_path, monkeypatch):
        app, ctx, _buf, _ = self._boot(
            tmp_path, monkeypatch,
            file_text='[nav_home]\nanchor = "bottom-right"\ndx = 30.0\ndy = 40.0\n')
        _with_track(app, ctx)
        for w in (1280.0, 1100.0, 940.0):
            ctx.logical_width_px = w
            app.invalidate()
            _tick(app, ctx, 2)
            home = next(r for r in app._hits if r.action == "nav" and r.payload == "home")
            assert home.x == w - 30 - 44, f"anchor spec stranded at width {w}"

    def test_absolute_rect_persists_as_degenerate_fallback(self, tmp_path, monkeypatch):
        app, ctx, _buf, layout_file = self._boot(tmp_path, monkeypatch, file_text=None)
        app.mcp_call("layout_set", {
            "id": "nav_home", "rect": {"x": 600, "y": 300, "width": 44, "height": 44}})
        text = layout_file.read_text()
        assert '["nav_home".rect]' in text and "x = 600.0" in text
        app2, ctx2, _b2, _ = self._boot(tmp_path / "second", monkeypatch,
                                        file_text=layout_file.read_text())
        _with_track(app2, ctx2)
        home = next(r for r in app2._hits if r.action == "nav" and r.payload == "home")
        assert (home.x, home.y, home.w, home.h) == (600.0, 300.0, 44.0, 44.0)

    def test_layout_clear_removes_the_persisted_entry(self, tmp_path, monkeypatch):
        app, ctx, _buf, layout_file = self._boot(tmp_path, monkeypatch, file_text=None)
        _with_track(app, ctx)
        assert '[["nav_more".align]]' in layout_file.read_text(), \
            "fixture seeds the shipped entry (round 38: the align form)"
        cleared = app.mcp_call("layout_clear", {"id": "nav_more"})
        assert cleared["cleared"] == ["nav_more"]
        assert "nav_more" not in layout_file.read_text()
        _tick(app, ctx, 2)
        overflow = next(r for r in app._hits if r.action == "open_devices")
        dock_cy = sl_views.dock_cluster_rect(1280, 800)[1] + sl_views.DOCK_SLOT_H / 2
        assert (overflow.x, overflow.y) == (1280.0 - 16 - 44, dock_cy - 22), \
            "clearing the persisted entry restores the code natural"

    def test_clear_all_empties_the_file(self, tmp_path, monkeypatch):
        app, ctx, _buf, layout_file = self._boot(tmp_path, monkeypatch, file_text=None)
        app.mcp_call("layout_set", {"id": "pill", "anchor": "top-left", "dx": 5, "dy": 5})
        cleared = app.mcp_call("layout_clear", {})
        assert sorted(cleared["cleared"]) == ["nav_more", "pill", "pill.progress"], \
            "the shipped nav_more + pill.progress entries clear along with the new one"
        assert "[" not in layout_file.read_text(), "no spec tables survive a clear-all"

    def test_roundtrip_preserves_specs(self, tmp_path, monkeypatch):
        app, ctx, _buf, layout_file = self._boot(tmp_path, monkeypatch, file_text=None)
        app.mcp_call("layout_set", {"id": "pill", "anchor": "top-right", "dx": 40, "dy": 24})
        app.mcp_call("layout_set", {
            "id": "nav_home", "rect": {"x": 300, "y": 700, "width": 44, "height": 44}})
        app2, ctx2, _b2, _ = self._boot(tmp_path / "second", monkeypatch,
                                        file_text=layout_file.read_text())
        before = app.layout_overrides.specs()
        after = app2.layout_overrides.specs()
        assert after == before, "a save/load round-trip must not drift the specs"

    def test_malformed_file_fails_soft(self, tmp_path, monkeypatch):
        app, ctx, _buf, _ = self._boot(tmp_path, monkeypatch,
                                       file_text="this is [ not toml ===\n")
        _with_track(app, ctx)
        overflow = next(r for r in app._hits if r.action == "open_devices")
        dock_cy = sl_views.dock_cluster_rect(1280, 800)[1] + sl_views.DOCK_SLOT_H / 2
        assert (overflow.x, overflow.y) == (1280.0 - 16 - 44, dock_cy - 22), \
            "a corrupt file must not kill the app — code naturals rule"

    def test_shipped_layout_file_bakes_nav_more_left_of_the_pill(self):
        """SL-19's end-to-end artifact, RE-SPEC'D in round 38 (SL-23): the
        window-anchor form retired — nav_more persists as a two-rule align
        RELATIONSHIP (right → pill.left −12 keep-size, center_y →
        pill.center_y), so the circle rides the pill's left edge at 12pt
        forever, however wide the pill grows. Geometry pins live in
        TestPlayCenteredPillGeometry."""
        import tomllib
        data = tomllib.loads(Path(sl_layout.APP_LAYOUT_FILE).read_text())
        rules = data["nav_more"]["align"]
        assert isinstance(rules, list) and len(rules) == 2, \
            "one array-of-tables entry per axis — no anchor form survives"
        by_edge = {rule["edge"]: rule for rule in rules}
        assert by_edge["right"]["to"] == "pill" and by_edge["right"]["ref_edge"] == "left"
        assert by_edge["right"]["offset"] == -12.0 and by_edge["right"]["keep"] == "size"
        assert by_edge["center_y"] == {"edge": "center_y", "to": "pill",
                                       "ref_edge": "center_y", "offset": 0.0}
        assert "anchor" not in data["nav_more"], "the last window-anchor form retired"

    def test_shipped_layout_file_bakes_the_progress_alignment(self):
        """SL-21's end-to-end artifact (round 37): the repo's layout.toml —
        written by layout_align itself — pins the strip's left edge to the
        text column's left as a RELATIONSHIP, resolving to (110, 59, 404, 3)
        pill-local (right edge 514) at the round-38 shipping pill size
        (PILL_W 572): the left-edge pin holds, the natural right edge rides
        the wider column. The runner cross-checks exactly this."""
        import tomllib
        data = tomllib.loads(Path(sl_layout.APP_LAYOUT_FILE).read_text())
        align = data["pill.progress"]["align"]
        assert align == {"edge": "left", "to": "pill.title",
                         "ref_edge": "left", "offset": 0.0}
        ov = sl_layout.LayoutOverrides()
        for cid, spec in data.items():
            ov.set(cid, spec)
        nats = _interior_naturals(pw=572.0)
        rect = ov.resolve("pill.progress", nats["pill.progress"],
                          width=572, height=108, naturals=nats)
        assert rect == (110.0, 59.0, 404.0, 3.0)
        assert rect[0] + rect[2] == 514.0, "natural right edge, 40pt inside the column pad"


class TestPillInteriorOverrides:
    """Round 33 (Alec): the layout surface extends INWARD — pill.art,
    pill.progress, and pill.transport are addressable in PILL-LOCAL space:
    (0, 0) is the pill's top-left, rects and anchors clamp into the pill
    (never the window), and locals compose with whole-pill moves — a pill
    override carries the interior, an interior override keeps its local
    offset across pill moves. Size is a layout input where the geometry has
    one: the art tile (square, min(w, h)) and the progress strip width; the
    transport cluster positions by its rect's center with fixed 34pt hits."""

    def test_interior_ids_are_addressable(self):
        for cid in ("pill.art", "pill.progress", "pill.title", "pill.transport"):
            assert cid in sl_layout.COMPONENT_IDS
        with pytest.raises(sl_layout.LayoutError) as exc:
            sl_layout.LayoutOverrides().set(
                "pill.nope", {"rect": {"x": 0, "y": 0, "width": 4, "height": 4}})
        assert "pill.art" in str(exc.value), "the error names the valid interior ids"

    def test_interior_naturals_derive_from_the_pill_column(self):
        col_x, col_w, art = sl_views.pill_column(520.0, 108.0)
        assert sl_views.pill_art_local(520.0, 108.0) == (12.0, 12.0, 84.0, 84.0)
        gx, gy, gw, gh = sl_views.pill_progress_local(520.0, 108.0)
        assert (gx, gy, gh) == (col_x + 34.0, 59.0, 3.0)
        assert gw == pytest.approx(col_w - 74.0)
        tx, ty, tw, th = sl_views.pill_transport_local(520.0, 108.0)
        assert (tx + tw / 2, ty + th / 2) == pytest.approx((260.0, 87.0)), \
            "SL-23: the transport centers on the PILL, not the text column"

    def test_default_scene_matches_the_naturals(self, app_ctx):
        """No overrides: the drawn art tile, seek hit, and play hit sit at the
        exported natural locals offset by the pill — the override surface
        describes the shipping geometry, not a parallel one."""
        app, ctx, buf = app_ctx
        app.mcp_call("layout_clear", {})  # isolate from the shipped layout file entries
        _with_track(app, ctx)
        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        ax, ay, _, _ = sl_views.pill_art_local(pw, ph)
        art = [n for n in _nodes(buf, CpuLayerNode) if n.width == 84]
        assert art and (art[0].x, art[0].y) == (px + ax, py + ay)
        gx, _, gw, _ = sl_views.pill_progress_local(pw, ph)
        seek = [r for r in app._hits if r.action == "seek_bar"]
        assert seek and (seek[0].x, seek[0].w) == (px + gx, gw)
        tx, ty, tw, th = sl_views.pill_transport_local(pw, ph)
        play = [r for r in app._hits if r.action == "toggle_play"]
        assert play and (play[0].x, play[0].y) == (px + tx + tw / 2 - 18, py + ty + th / 2 - 18)

    def test_art_override_moves_and_resizes_in_local_space(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        result = app.mcp_call("layout_set", {
            "id": "pill.art", "rect": {"x": 20, "y": 22, "width": 64, "height": 64}})
        assert result["rect"] == [20.0, 22.0, 64.0, 64.0], "interior rects report local"
        _tick(app, ctx, 2)
        px, py, _, _ = sl_views.pill_rect(1280, 800)
        art = [n for n in _nodes(buf, CpuLayerNode) if n.width == 64]
        assert art and (art[0].x, art[0].y) == (px + 20, py + 22)

    def test_interior_clamps_into_the_pill_not_the_window(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        app.mcp_call("layout_set", {
            "id": "pill.art", "rect": {"x": 500, "y": -30, "width": 84, "height": 84}})
        _tick(app, ctx, 2)
        px, py, _, _ = sl_views.pill_rect(1280, 800)
        art = [n for n in _nodes(buf, CpuLayerNode) if n.width == 84]
        assert art and (art[0].x, art[0].y) == (px + 488.0, py + 0.0), \
            "500pt fits the window but not the 572pt pill — the clamp is pill-local"

    def test_art_rides_a_whole_pill_move(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        app.mcp_call("layout_set", {
            "id": "pill.art", "rect": {"x": 24, "y": 12, "width": 84, "height": 84}})
        app.mcp_call("layout_set", {
            "id": "pill", "rect": {"x": 100, "y": 120, "width": 520, "height": 108}})
        _tick(app, ctx, 2)
        art = [n for n in _nodes(buf, CpuLayerNode) if n.width == 84]
        assert art and (art[0].x, art[0].y) == (124.0, 132.0), \
            "the local override composes with the moved pill"

    def test_progress_override_moves_the_strip_and_times_ride(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        app.mcp_call("layout_set", {
            "id": "pill.progress", "rect": {"x": 150, "y": 70, "width": 200, "height": 3}})
        _tick(app, ctx, 2)
        px, py, _, _ = sl_views.pill_rect(1280, 800)
        seek = [r for r in app._hits if r.action == "seek_bar"]
        assert seek and (seek[0].x, seek[0].y, seek[0].w) == (px + 150, py + 64, 200.0)
        frame = buf.latest_frame()
        # Round 37: the time labels sit ABOVE the strip's ends — the elapsed
        # label left-aligned at the strip's left, the duration's right edge
        # at the strip's right — so a strip aligned to the text column never
        # paints a label over the art tile.
        elapsed = [n for n in frame.nodes
                   if isinstance(n, TextNode) and n.text in ("0:30", "0:31")]
        assert elapsed and (elapsed[0].x, elapsed[0].y) == (px + 150, py + 70 - 11), \
            "the elapsed label sits above the strip's left end"
        duration = [n for n in frame.nodes if isinstance(n, TextNode) and n.text == "4:17"]
        dur_w = ctx.measure_text("4:17", font_size_px=9.0,
                                 font_family=sl_views.FONT_FAMILY)
        assert duration and duration[0].x == pytest.approx(px + 150 + 200 - dur_w), \
            "the duration label's right edge rides the strip's right end"
        assert duration[0].y == py + 70 - 11

    def test_transport_override_moves_the_cluster(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        app.mcp_call("layout_set", {
            "id": "pill.transport", "rect": {"x": 150, "y": 20, "width": 130, "height": 36}})
        _tick(app, ctx, 2)
        px, py, _, _ = sl_views.pill_rect(1280, 800)
        cx, cy = px + 150 + 65, py + 20 + 18
        hits = {r.action: r for r in app._hits if r.action in ("toggle_play", "prev", "next")}
        assert (hits["toggle_play"].x, hits["toggle_play"].y, hits["toggle_play"].w) == \
            (cx - 18, cy - 18, 36.0)
        assert (hits["prev"].x, hits["prev"].w) == (cx - 65, 34.0)
        assert (hits["next"].x, hits["next"].w) == (cx + 31, 34.0)
        disc = [n for n in _nodes(buf, CircleNode) if n.radius == 16]
        assert disc and (disc[0].cx, disc[0].cy) == (cx, cy), "the play disc rides the cluster"

    def test_transport_anchor_resolves_inside_the_pill(self, app_ctx):
        """Interior anchors measure inward from the PILL's corners."""
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        result = app.mcp_call("layout_set", {
            "id": "pill.transport", "anchor": "bottom-right", "dx": 10, "dy": 8})
        assert result["rect"] == [432.0, 64.0, 130.0, 36.0]

    def test_export_round_trip_includes_interior(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        app.mcp_call("layout_set", {
            "id": "pill.art", "rect": {"x": 24, "y": 12, "width": 72, "height": 72}})
        app.mcp_call("layout_set", {
            "id": "pill.transport", "anchor": "bottom-right", "dx": 10, "dy": 8})
        exported = app.mcp_call("layout_export", {})
        assert exported["resolved"]["pill.art"] == [24.0, 12.0, 72.0, 72.0]
        assert exported["resolved"]["pill.transport"] == [432.0, 64.0, 130.0, 36.0]
        app.mcp_call("layout_clear", {})
        for cid, spec in exported["overrides"].items():
            app.mcp_call("layout_set", {"id": cid, **spec})
        _tick(app, ctx, 2)
        px, py, _, _ = sl_views.pill_rect(1280, 800)
        art = [n for n in _nodes(buf, CpuLayerNode) if n.width == 72]
        assert art and (art[0].x, art[0].y) == (px + 24, py + 12)
        play = [r for r in app._hits if r.action == "toggle_play"]
        assert (play[0].x, play[0].y) == (px + 432 + 65 - 18, py + 64), \
            "cleared and re-imported specs reproduce the scene"

    def test_interior_override_survives_state_changes(self, app_ctx):
        app, ctx, buf = app_ctx
        app.mcp_call("layout_set", {
            "id": "pill.art", "rect": {"x": 30, "y": 12, "width": 60, "height": 60}})
        app.authenticated = True
        for view in ("library", "search", "home"):
            app.view = view
            _tick(app, ctx, 1)
        _with_track(app, ctx)
        px, py, _, _ = sl_views.pill_rect(1280, 800)
        art = [n for n in _nodes(buf, CpuLayerNode) if n.width == 60]
        assert art and (art[0].x, art[0].y) == (px + 30, py + 12)

    def test_bad_interior_spec_never_reaches_the_scene(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        with pytest.raises(sl_layout.LayoutError):
            app.mcp_call("layout_set", {"id": "pill.art", "anchor": "top-left", "dx": "banana"})
        _tick(app, ctx, 2)
        px, py, _, _ = sl_views.pill_rect(1280, 800)
        ax, ay, _, _ = sl_views.pill_art_local(520.0, 108.0)
        art = [n for n in _nodes(buf, CpuLayerNode) if n.width == 84]
        assert art and (art[0].x, art[0].y) == (px + ax, py + ay), \
            "a rejected spec leaves the natural interior untouched"

    def test_wire_round_trip_interior(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        bridge = _bridge(app)
        bridge.register_app_hooks(app)
        with _Drain(bridge):
            response = bridge.dispatcher().handle_payload(
                {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                 "params": {"name": "layout_set",
                            "arguments": {"id": "pill.art",
                                          "rect": {"x": 26, "y": 18, "width": 70, "height": 70}}}})
            payload = json.loads(response["result"]["content"][0]["text"])
            assert payload["rect"] == [26.0, 18.0, 70.0, 70.0]
        _tick(app, ctx, 2)
        px, py, _, _ = sl_views.pill_rect(1280, 800)
        art = [n for n in _nodes(buf, CpuLayerNode) if n.width == 70]
        assert art and (art[0].x, art[0].y) == (px + 26, py + 18)


# ---------------------------------------------------------------------------
# Round 37 (Alec, SL-22): the third spec form — edge-to-edge ALIGNMENT
# between two layout ids, persisted as a relationship. SL-21 rides it:
# pill.progress left → pill.title left.
# ---------------------------------------------------------------------------

def _interior_naturals(pw=520.0, ph=108.0):
    """The pill-local natural rects for a given pill frame (round-37 tests
    exercise a 520pt frame; pass pw=572.0 for the SL-23 shipping size)."""
    return {
        "pill.art": sl_views.pill_art_local(pw, ph),
        "pill.progress": sl_views.pill_progress_local(pw, ph),
        "pill.title": sl_views.pill_title_local(pw, ph),
        "pill.transport": sl_views.pill_transport_local(pw, ph),
    }


class TestLayoutAlignSpec:
    """Unit level: {align: {edge, to, ref_edge, offset}} resolves against
    the reference's CURRENT rect (natural or overridden). Edge alignment
    moves the named edge to the reference line + offset and keeps the
    opposite edge fixed (the extent changes); center alignment keeps the
    size (only the position changes). References stay in one frame:
    interior ids reference interior ids (or the pill frame itself as
    "pill"), window ids reference window ids."""

    def test_pill_title_is_the_text_column(self):
        assert "pill.title" in sl_layout.INTERIOR_IDS
        assert sl_views.pill_title_local(520.0, 108.0) == (110.0, 21.0, 392.0, 32.0), \
            "the title/artist column: right of the art + gap, above the strip"

    def test_left_align_keeps_the_right_edge_fixed(self):
        """The SL-21 geometry: progress left → text-column left grows the
        strip leftward; the right edge holds at 462 (the runner's spec)."""
        ov = sl_layout.LayoutOverrides()
        ov.set("pill.progress", {"align": {
            "edge": "left", "to": "pill.title", "ref_edge": "left", "offset": 0}})
        nats = _interior_naturals()
        got = ov.resolve("pill.progress", nats["pill.progress"],
                         width=520, height=108, naturals=nats)
        assert got == (110.0, 59.0, 352.0, 3.0)
        assert got[0] + got[2] == 462.0, "right edge unmoved"

    def test_right_align_keeps_the_left_edge_fixed(self):
        ov = sl_layout.LayoutOverrides()
        ov.set("pill.progress", {"align": {
            "edge": "right", "to": "pill.title", "ref_edge": "right"}})
        nats = _interior_naturals()
        got = ov.resolve("pill.progress", nats["pill.progress"],
                         width=520, height=108, naturals=nats)
        assert got == (144.0, 59.0, 358.0, 3.0), \
            "left holds at 144; the right edge grows to the column's right (502)"

    def test_center_alignment_keeps_the_size(self):
        nats = _interior_naturals()
        ov = sl_layout.LayoutOverrides()
        ov.set("pill.progress", {"align": {
            "edge": "center_x", "to": "pill.title", "ref_edge": "center_x"}})
        got = ov.resolve("pill.progress", nats["pill.progress"],
                         width=520, height=108, naturals=nats)
        assert got == pytest.approx((306.0 - 159.0, 59.0, 318.0, 3.0)), \
            "only the position moves; the strip keeps its width"
        ov2 = sl_layout.LayoutOverrides()
        ov2.set("pill.progress", {"align": {
            "edge": "center_y", "to": "pill.art", "ref_edge": "center_y"}})
        got2 = ov2.resolve("pill.progress", nats["pill.progress"],
                           width=520, height=108, naturals=nats)
        assert got2 == pytest.approx((144.0, 54.0 - 1.5, 318.0, 3.0))

    def test_top_and_bottom_align_keep_the_vertical_extent(self):
        nats = _interior_naturals()
        ov = sl_layout.LayoutOverrides()
        ov.set("pill.progress", {"align": {
            "edge": "top", "to": "pill.art", "ref_edge": "top"}})
        got = ov.resolve("pill.progress", nats["pill.progress"],
                         width=520, height=108, naturals=nats)
        assert got == (144.0, 12.0, 318.0, 50.0), "bottom edge (62) fixed; the top moves"
        ov2 = sl_layout.LayoutOverrides()
        ov2.set("pill.progress", {"align": {
            "edge": "bottom", "to": "pill.art", "ref_edge": "bottom"}})
        got2 = ov2.resolve("pill.progress", nats["pill.progress"],
                           width=520, height=108, naturals=nats)
        assert got2 == (144.0, 59.0, 318.0, 37.0), \
            "top fixed; the bottom edge moves to the art's bottom (96)"

    def test_offset_shifts_the_aligned_edge(self):
        ov = sl_layout.LayoutOverrides()
        ov.set("pill.progress", {"align": {
            "edge": "left", "to": "pill.title", "ref_edge": "left", "offset": 6}})
        nats = _interior_naturals()
        got = ov.resolve("pill.progress", nats["pill.progress"],
                         width=520, height=108, naturals=nats)
        assert got == (116.0, 59.0, 346.0, 3.0)

    def test_resolution_uses_the_references_current_rect(self):
        """The relationship tracks the reference: an override on pill.title
        moves the aligned strip edge; a natural reference resolves naturally."""
        ov = sl_layout.LayoutOverrides()
        ov.set("pill.progress", {"align": {"edge": "left", "to": "pill.title"}})
        ov.set("pill.title", {"rect": {"x": 130, "y": 21, "width": 360, "height": 32}})
        nats = _interior_naturals()
        got = ov.resolve("pill.progress", nats["pill.progress"],
                         width=520, height=108, naturals=nats)
        assert got == (130.0, 59.0, 332.0, 3.0), \
            "the reference's override wins the resolution; the right edge still holds 462"
        ov2 = sl_layout.LayoutOverrides()
        ov2.set("pill.progress", {"align": {"edge": "left", "to": "pill.title"}})
        assert ov2.resolve("pill.progress", nats["pill.progress"],
                           width=520, height=108, naturals=nats)[0] == 110.0

    def test_interior_ids_can_align_to_the_pill_frame(self):
        """The pseudo-reference "pill" is the local frame itself: (0, 0, pw, ph)."""
        ov = sl_layout.LayoutOverrides()
        ov.set("pill.progress", {"align": {
            "edge": "right", "to": "pill", "ref_edge": "right", "offset": -50}})
        nats = _interior_naturals()
        got = ov.resolve("pill.progress", nats["pill.progress"],
                         width=520, height=108, naturals=nats)
        assert got == (144.0, 59.0, 326.0, 3.0), "left fixed; right edge at 520 - 50"

    def test_a_collapsed_extent_guards_to_one_point(self):
        ov = sl_layout.LayoutOverrides()
        ov.set("pill.progress", {"align": {
            "edge": "left", "to": "pill.title", "ref_edge": "right"}})  # 502 > right 462
        nats = _interior_naturals()
        got = ov.resolve("pill.progress", nats["pill.progress"],
                         width=520, height=108, naturals=nats)
        assert got == (461.0, 59.0, 1.0, 3.0), "the extent collapses to 1pt, never negative"

    def test_window_ids_align_in_window_space(self):
        ov = sl_layout.LayoutOverrides()
        ov.set("nav_home", {"align": {
            "edge": "right", "to": "nav_search", "ref_edge": "left", "offset": -12}})
        nats = sl_views.window_naturals(1280.0, 800.0)
        hx, hy, _, hh = nats["nav_home"]
        search_left = nats["nav_search"][0]
        got = ov.resolve("nav_home", nats["nav_home"],
                         width=1280, height=800, naturals=nats)
        assert got == pytest.approx((hx, hy, search_left - 12 - hx, hh)), \
            "right edge pinned 12pt left of the search circle; the left edge holds"

    def test_align_resolution_needs_the_frame_naturals(self):
        ov = sl_layout.LayoutOverrides()
        ov.set("pill.progress", {"align": {"edge": "left", "to": "pill.title"}})
        with pytest.raises(sl_layout.LayoutError):
            ov.resolve("pill.progress", (144.0, 59.0, 318.0, 3.0), width=520, height=108)

    def test_bad_align_specs_raise_and_never_store(self):
        bad = [
            {"edge": "middle", "to": "pill.title"},                        # unknown edge
            {"edge": "left", "to": "pill.title", "ref_edge": "sideways"},  # unknown ref_edge
            {"edge": "left", "to": "pill.title", "ref_edge": "top"},       # cross-axis
            {"edge": "left", "to": "pill.nope"},                           # unknown reference
            {"edge": "left", "to": "pill.progress"},                       # self-reference
            {"edge": "left", "to": "nav_home"},                            # interior → window
            {"edge": "left", "to": "pill.title", "offset": "banana"},      # non-numeric
            {"edge": "left", "to": "pill.title", "offset": float("nan")},  # NaN
            {"edge": "left"},                                              # missing reference
        ]
        for spec in bad:
            ov = sl_layout.LayoutOverrides()
            with pytest.raises(sl_layout.LayoutError):
                ov.set("pill.progress", {"align": spec})
            assert len(ov) == 0, f"a rejected spec must never reach the registry: {spec}"
        ov = sl_layout.LayoutOverrides()
        with pytest.raises(sl_layout.LayoutError):
            ov.set("nav_home", {"align": {"edge": "left", "to": "pill.title"}})
        assert len(ov) == 0, "window ids cannot reference the pill's interior"

    def test_align_cycles_are_rejected_at_set_time(self):
        ov = sl_layout.LayoutOverrides()
        ov.set("pill.art", {"align": {"edge": "left", "to": "pill.transport"}})
        with pytest.raises(sl_layout.LayoutError) as exc:
            ov.set("pill.transport", {"align": {"edge": "left", "to": "pill.art"}})
        assert "cycle" in str(exc.value)
        assert ov.specs()["pill.art"]["align"]["to"] == "pill.transport", \
            "the earlier spec survives; the cycle-closing one never lands"
        assert "pill.transport" not in ov.specs()
        ov2 = sl_layout.LayoutOverrides()
        ov2.set("pill.art", {"align": {"edge": "left", "to": "pill.progress"}})
        ov2.set("pill.progress", {"align": {"edge": "left", "to": "pill.transport"}})
        with pytest.raises(sl_layout.LayoutError):
            ov2.set("pill.transport", {"align": {"edge": "left", "to": "pill.art"}})
        assert "pill.transport" not in ov2.specs(), "longer cycles rejected too"


class TestLayoutAlignTool:
    """MCP surface: layout_align applies through the same override machinery
    as layout_set — visual immediately, persisted via the layout.toml
    write-through, as a RELATIONSHIP (never resolved pixels)."""

    def test_align_applies_immediately_and_persists_the_relationship(self, app_ctx):
        """SL-21 through the tool: pin the strip's left edge to the text
        column's left. The runner's acceptance on 1280x800: (110, 59, 404, 3)
        pill-local on the round-38 plate, right edge 514."""
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        result = app.mcp_call("layout_align", {
            "id": "pill.progress", "edge": "left",
            "to": "pill.title", "ref_edge": "left"})
        assert result["rect"] == [110.0, 59.0, 404.0, 3.0]
        assert result["persisted"] is True
        text = sl_layout.default_path().read_text()
        assert '["pill.progress".align]' in text
        assert 'edge = "left"' in text and 'to = "pill.title"' in text
        assert 'ref_edge = "left"' in text and "offset = 0.0" in text
        assert "110.0" not in text, "the relationship persists, never resolved pixels"
        _tick(app, ctx, 2)
        px, _, _, _ = sl_views.pill_rect(1280, 800)
        seek = [r for r in app._hits if r.action == "seek_bar"]
        assert seek and (seek[0].x, seek[0].w) == (px + 110, 404.0)
        app.init(ctx)  # reboot: the file is the source of truth
        _with_track(app, ctx)
        px, _, _, _ = sl_views.pill_rect(1280, 800)
        seek = [r for r in app._hits if r.action == "seek_bar"]
        assert seek and (seek[0].x, seek[0].w) == (px + 110, 404.0), \
            "the persisted relationship survives the reboot"

    def test_align_tracks_a_later_reference_move(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        app.mcp_call("layout_align", {
            "id": "pill.progress", "edge": "left", "to": "pill.title", "ref_edge": "left"})
        app.mcp_call("layout_set", {
            "id": "pill.title", "rect": {"x": 130, "y": 21, "width": 360, "height": 32}})
        _tick(app, ctx, 2)
        px, _, _, _ = sl_views.pill_rect(1280, 800)
        seek = [r for r in app._hits if r.action == "seek_bar"]
        assert seek and (seek[0].x, seek[0].w) == (px + 130, 384.0), \
            "the aligned edge tracks the reference's current rect (right edge still 514)"

    def test_align_is_resize_safe(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        app.mcp_call("layout_align", {
            "id": "pill.progress", "edge": "left", "to": "pill.title", "ref_edge": "left"})
        ctx.logical_width_px = 1000.0
        app.invalidate()  # stands in for the OS resize event
        _tick(app, ctx, 2)
        px, _, _, _ = sl_views.pill_rect(1000, 800)
        seek = [r for r in app._hits if r.action == "seek_bar"]
        assert seek and seek[0].x - px == 110.0 and seek[0].w == 404.0, \
            "pill-local alignment is indifferent to the window size"

    def test_align_errors_never_touch_scene_or_file(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        before_text = sl_layout.default_path().read_text()
        seek_before = [(r.x, r.w) for r in app._hits if r.action == "seek_bar"]
        bad_calls = [
            {"id": "pill.progress", "edge": "left", "to": "pill.title",
             "ref_edge": "top"},                                     # cross-axis
            {"id": "pill.progress", "edge": "left", "to": "pill.progress",
             "ref_edge": "left"},                                    # self-reference
            {"id": "pill.progress", "edge": "middle", "to": "pill.title",
             "ref_edge": "left"},                                    # unknown edge
            {"id": "nav_home", "edge": "left", "to": "pill.title",
             "ref_edge": "left"},                                    # cross-frame
            {"id": "pill.progress", "edge": "left", "to": "pill.nope",
             "ref_edge": "left"},                                    # unknown reference
            {"id": "pill.progress", "edge": "left", "to": "pill.title",
             "ref_edge": "left", "offset": "banana"},                # non-numeric
        ]
        for args in bad_calls:
            with pytest.raises(sl_layout.LayoutError):
                app.mcp_call("layout_align", args)
        assert sl_layout.default_path().read_text() == before_text, \
            "a rejected align never reaches the layout file"
        _tick(app, ctx, 2)
        seek_after = [(r.x, r.w) for r in app._hits if r.action == "seek_bar"]
        assert seek_after == seek_before, "a rejected align never disturbs the scene"

    def test_align_cycle_is_rejected_and_never_persists(self, app_ctx):
        app, ctx, _ = app_ctx
        app.mcp_call("layout_align", {
            "id": "pill.art", "edge": "left", "to": "pill.transport", "ref_edge": "left"})
        with pytest.raises(sl_layout.LayoutError) as exc:
            app.mcp_call("layout_align", {
                "id": "pill.transport", "edge": "left", "to": "pill.art", "ref_edge": "left"})
        assert "cycle" in str(exc.value)
        assert '["pill.transport".align]' not in sl_layout.default_path().read_text(), \
            "the cycle never persisted"

    def test_clear_removes_the_align_entry(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        app.mcp_call("layout_align", {
            "id": "pill.progress", "edge": "left", "to": "pill.title", "ref_edge": "left"})
        assert "pill.progress" in sl_layout.default_path().read_text()
        app.mcp_call("layout_clear", {"id": "pill.progress"})
        assert "pill.progress" not in sl_layout.default_path().read_text()
        _tick(app, ctx, 2)
        px, _, _, _ = sl_views.pill_rect(1280, 800)
        gx, _, gw, _ = sl_views.pill_progress_local(572.0, 108.0)
        seek = [r for r in app._hits if r.action == "seek_bar"]
        assert seek and (seek[0].x, seek[0].w) == (px + gx, gw), \
            "clearing the align entry restores the code natural"


class TestPillTitleInterior:
    """Round 37 (SL-22): the text column becomes a real interior id so the
    align surface has a meaningful reference — pill.title is the
    title/artist column ("Nothing playing" + subtitle when idle). Moving it
    moves the texts; the progress strip aligns to it."""

    def test_default_scene_matches_the_title_natural(self, app_ctx):
        app, ctx, buf = app_ctx
        app.mcp_call("layout_clear", {})  # isolate from the shipped layout file entries
        _with_track(app, ctx)
        px, py, _, _ = sl_views.pill_rect(1280, 800)
        tx, ty, _, _ = sl_views.pill_title_local(520.0, 108.0)
        title = [n for n in _nodes(buf, TextNode) if n.text == "Lithium"]
        artist = [n for n in _nodes(buf, TextNode) if n.text == "Nirvana"]
        assert title and (title[0].x, title[0].y) == (px + tx, py + ty)
        assert artist and artist[0].y == py + ty + 14, "artist rides the column's second row"

    def test_title_override_moves_the_texts(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        result = app.mcp_call("layout_set", {
            "id": "pill.title", "rect": {"x": 120, "y": 26, "width": 360, "height": 32}})
        assert result["rect"] == [120.0, 26.0, 360.0, 32.0]
        _tick(app, ctx, 2)
        px, py, _, _ = sl_views.pill_rect(1280, 800)
        title = [n for n in _nodes(buf, TextNode) if n.text == "Lithium"]
        artist = [n for n in _nodes(buf, TextNode) if n.text == "Nirvana"]
        assert title and (title[0].x, title[0].y) == (px + 120, py + 26)
        assert artist and (artist[0].x, artist[0].y) == (px + 120, py + 40)

    def test_idle_texts_ride_the_column_too(self, app_ctx):
        app, ctx, buf = app_ctx
        app.authenticated = True
        app.mcp_call("layout_set", {
            "id": "pill.title", "rect": {"x": 124, "y": 24, "width": 360, "height": 32}})
        _tick(app, ctx, 2)
        px, py, _, _ = sl_views.pill_rect(1280, 800)
        nothing = [n for n in _nodes(buf, TextNode) if n.text == "Nothing playing"]
        hint = [n for n in _nodes(buf, TextNode) if n.text.startswith("Pick a device")]
        assert nothing and (nothing[0].x, nothing[0].y) == (px + 124, py + 24)
        assert hint and hint[0].y == py + 24 + 19


# ---------------------------------------------------------------------------
# Round 38 (Alec, SL-23): the plate grows right until the play button is
# its geometric center (PILL_W 520 → 572, right edge pinned); the transport
# centers on the PILL so centering holds by construction at any width;
# nav_more's persisted entry becomes a RELATIONSHIP (multi-axis align +
# keep="size") riding the pill's left edge at 12pt — retiring the last
# window-anchor form.
# ---------------------------------------------------------------------------

class TestAlignKeepSizeAndMultiAxis:
    """SL-23 extend the round-37 align rule in two ways: keep="size" turns
    an edge rule into a POSITION move (the named edge meets the reference
    line, the extent holds) instead of an extent change, and an align spec
    may carry up to two rules — one per axis — so a component can ride a
    reference in x and y at once."""

    def test_keep_size_moves_the_edge_without_resizing(self):
        ov = sl_layout.LayoutOverrides()
        ov.set("pill.art", {"align": {
            "edge": "right", "to": "pill.title", "ref_edge": "left",
            "offset": -6, "keep": "size"}})
        nats = _interior_naturals()
        got = ov.resolve("pill.art", nats["pill.art"], width=520, height=108,
                         naturals=nats)
        assert got == (20.0, 12.0, 84.0, 84.0), \
            "right edge at 110 - 6 = 104, size held → x = 104 - 84; default would grow (12, 92)"

    def test_two_axis_rules_resolve_both_axes(self):
        ov = sl_layout.LayoutOverrides()
        ov.set("pill.art", {"align": [
            {"edge": "right", "to": "pill", "ref_edge": "right",
             "offset": -12, "keep": "size"},
            {"edge": "center_y", "to": "pill", "ref_edge": "center_y"},
        ]})
        nats = _interior_naturals()
        got = ov.resolve("pill.art", nats["pill.art"], width=520, height=108,
                         naturals=nats)
        assert got == (520.0 - 12 - 84, 54.0 - 42, 84.0, 84.0)

    def test_two_rules_on_the_same_axis_are_rejected(self):
        ov = sl_layout.LayoutOverrides()
        with pytest.raises(sl_layout.LayoutError):
            ov.set("pill.art", {"align": [
                {"edge": "left", "to": "pill.title"},
                {"edge": "right", "to": "pill.title"},
            ]})
        with pytest.raises(sl_layout.LayoutError):
            ov.set("pill.art", {"align": [
                {"edge": "left", "to": "pill.title"},
                {"edge": "center_x", "to": "pill.title"},
            ]})
        with pytest.raises(sl_layout.LayoutError):
            ov.set("pill.art", {"align": []})
        assert len(ov) == 0

    def test_keep_is_only_meaningful_on_edge_rules(self):
        ov = sl_layout.LayoutOverrides()
        with pytest.raises(sl_layout.LayoutError):
            ov.set("pill.art", {"align": {
                "edge": "center_x", "to": "pill.title", "keep": "size"}})
        with pytest.raises(sl_layout.LayoutError):
            ov.set("pill.art", {"align": {
                "edge": "left", "to": "pill.title", "keep": "banana"}})
        assert len(ov) == 0

    def test_multi_axis_cycles_are_rejected(self):
        ov = sl_layout.LayoutOverrides()
        ov.set("pill.art", {"align": [
            {"edge": "right", "to": "pill.transport", "keep": "size"},
            {"edge": "center_y", "to": "pill.transport"},
        ]})
        with pytest.raises(sl_layout.LayoutError) as exc:
            ov.set("pill.transport", {"align": {"edge": "left", "to": "pill.art"}})
        assert "cycle" in str(exc.value)

    def test_layout_align_tool_upserts_one_rule_per_axis(self, app_ctx):
        """Each call pins one edge; a second call on the OTHER axis adds to
        the relationship instead of replacing it. Same-axis re-calls
        replace their rule."""
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        app.mcp_call("layout_clear", {"id": "nav_more"})  # the fixture ships the SL-23 relationship; build it from scratch here
        r1 = app.mcp_call("layout_align", {
            "id": "nav_more", "edge": "right", "to": "pill",
            "ref_edge": "left", "offset": -12, "keep": "size"})
        assert r1["rect"] == [636.0, 730.0, 44.0, 44.0], \
            "x rides the pill's left edge; y untouched until a y rule exists"
        r2 = app.mcp_call("layout_align", {
            "id": "nav_more", "edge": "center_y", "to": "pill",
            "ref_edge": "center_y"})
        assert r2["rect"] == [636.0, 48.0, 44.0, 44.0], \
            "the SL-23 target: 12pt left of the pill, pill-centered"
        spec = app.layout_overrides.specs()["nav_more"]["align"]
        assert isinstance(spec, list) and len(spec) == 2, \
            "two axis rules persist as one relationship"
        r3 = app.mcp_call("layout_align", {
            "id": "nav_more", "edge": "right", "to": "pill",
            "ref_edge": "left", "offset": -20, "keep": "size"})
        assert r3["rect"][0] == 692.0 - 20 - 44, "the same-axis rule replaced, not stacked"
        assert len(app.layout_overrides.specs()["nav_more"]["align"]) == 2

    def test_multi_axis_persists_as_an_array_of_tables(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        app.mcp_call("layout_align", {
            "id": "nav_more", "edge": "right", "to": "pill",
            "ref_edge": "left", "offset": -12, "keep": "size"})
        app.mcp_call("layout_align", {
            "id": "nav_more", "edge": "center_y", "to": "pill", "ref_edge": "center_y"})
        text = sl_layout.default_path().read_text()
        assert text.count('[["nav_more".align]]') == 2, \
            "each axis rule is one array-of-tables entry"
        assert 'keep = "size"' in text
        app.init(ctx)  # reboot: the relationship reloads
        _with_track(app, ctx)
        overflow = next(r for r in app._hits if r.action == "open_devices")
        assert (overflow.x, overflow.y) == (636.0, 48.0)


class TestPlayCenteredPillGeometry:
    """The SL-23 plate: PILL_W = 2 × 286 (the transport center on the
    round-32 plate: column-left 110 + half the SL-21 strip 176), right edge
    pinned at PILL_FLOAT, so all growth lands leftward; the transport
    centers on the PILL — play == plate center by construction."""

    def test_pill_rect_is_572_wide_right_edge_pinned(self):
        assert sl_views.PILL_W == 572.0
        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        assert (px, py, pw, ph) == (692.0, 16.0, 572.0, 108.0)
        assert px + pw == 1280.0 - sl_views.PILL_FLOAT, "right edge pinned"
        for w in (1100.0, 940.0):
            px2, _, pw2, _ = sl_views.pill_rect(w, 800)
            assert pw2 == 572.0 and px2 + pw2 == w - sl_views.PILL_FLOAT

    def test_transport_centers_on_the_pill_not_the_column(self):
        tx, ty, tw, th = sl_views.pill_transport_local(572.0, 108.0)
        assert (tx + tw / 2, ty + th / 2) == (286.0, 87.0), \
            "the play button sits at the plate's geometric center"
        tx2, _, tw2, _ = sl_views.pill_transport_local(400.0, 108.0)
        assert tx2 + tw2 / 2 == 200.0, "centering holds at any pill width"

    def test_shipped_nav_more_is_a_relationship_riding_the_pill(self):
        """The last window-anchor form retires: nav_more persists as TWO
        align rules (right → pill.left −12 keep-size, center_y →
        pill.center_y) and resolves to (636, 48, 44, 44) at 1280x800."""
        import tomllib
        data = tomllib.loads(Path(sl_layout.APP_LAYOUT_FILE).read_text())
        rules = data["nav_more"]["align"]
        assert isinstance(rules, list) and len(rules) == 2
        by_edge = {rule["edge"]: rule for rule in rules}
        assert by_edge["right"] == {"edge": "right", "to": "pill",
                                    "ref_edge": "left", "offset": -12.0, "keep": "size"}
        assert by_edge["center_y"] == {"edge": "center_y", "to": "pill",
                                       "ref_edge": "center_y", "offset": 0.0}
        ov = sl_layout.LayoutOverrides()
        for cid, spec in data.items():
            ov.set(cid, spec)
        nats = sl_views.window_naturals(1280.0, 800.0)
        rect = ov.resolve("nav_more", nats["nav_more"], width=1280, height=800,
                          naturals=nats)
        assert rect == (636.0, 48.0, 44.0, 44.0)
        pill = sl_views.pill_rect(1280, 800)
        assert pill[0] - (rect[0] + rect[2]) == 12.0, "12pt left of the pill"
        assert rect[1] + rect[3] / 2 == pill[1] + pill[3] / 2, "vertically centered"

    def test_nav_more_relationship_rides_window_resizes(self, app_ctx):
        app, ctx, buf = app_ctx
        _with_track(app, ctx)  # shipped entry is active from the fixture's file copy
        for w in (1280.0, 1100.0, 940.0):
            ctx.logical_width_px = w
            app.invalidate()
            _tick(app, ctx, 2)
            px, _, _, _ = sl_views.pill_rect(w, 800)
            overflow = next(r for r in app._hits if r.action == "open_devices")
            assert (overflow.x, overflow.y) == (px - 12 - 44, 48.0), \
                f"the circle rides the pill's left edge at width {w}"

    def test_a_degenerate_one_point_circle_never_crashes(self, app_ctx):
        """Probe-found bug (round 38): an override collapsing nav_more to
        1pt crashed the glass plate draw (radius-derived rects went
        non-positive). Degenerate geometry must render, not raise."""
        app, ctx, buf = app_ctx
        _with_track(app, ctx)
        app.mcp_call("layout_set", {
            "id": "nav_more", "rect": {"x": 1200, "y": 730, "width": 1, "height": 1}})
        _tick(app, ctx, 2)  # must not raise
        overflow = next(r for r in app._hits if r.action == "open_devices")
        assert (overflow.x, overflow.y) == (1200.0, 730.0)
