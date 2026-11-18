"""Per-glyph font fallback (round 9).

Live Mac bug (Alec's library): playlist names with emoji/special chars render
as empty boxes — "[][]shamu[][]" — because the PIL/FreeType text paths load
ONE font file and FreeType draws .notdef for anything outside its coverage.
The fix is a font-file cascade (the PIL equivalent of a Core Text cascade
list): pick the first font that actually covers each glyph, and only render
.notdef when NO font in the chain covers it.
"""
from __future__ import annotations

import os

import pytest

from luvatrix_core.core import font_fallback as ff

DEJAVU_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
WQY_CJK = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
NOTO_EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"

needs_dejavu = pytest.mark.skipif(not os.path.exists(DEJAVU_MONO), reason="DejaVuSansMono missing")
needs_wqy = pytest.mark.skipif(not os.path.exists(WQY_CJK), reason="wqy-microhei missing")
needs_noto_emoji = pytest.mark.skipif(not os.path.exists(NOTO_EMOJI), reason="NotoColorEmoji missing")


DEJAVU_SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
needs_dejavu_sans = pytest.mark.skipif(not os.path.exists(DEJAVU_SANS), reason="DejaVuSans missing")


class TestFamilyResolution:
    """Round 15 (found via measure_text on Linux): `_resolve_system_font_path`
    ran a legacy all-mono fallback chain for ANY unmatched family, so a
    proportional request like Helvetica Neue resolved to
    DejaVuSansMono-BoldOblique — every string measured and rendered at a
    fixed advance, and in a display face at that."""

    @needs_dejavu_sans
    def test_proportional_family_never_resolves_to_mono(self):
        from luvatrix_core.core.ui_frame_renderer import _resolve_system_font_path

        path = _resolve_system_font_path("Helvetica Neue")
        name = os.path.basename(path).lower()
        assert "mono" not in name, f"proportional request resolved to a mono font: {path}"
        assert "bold" not in name and "oblique" not in name and "italic" not in name, \
            f"regular face must be preferred over display variants: {path}"

    @needs_dejavu
    def test_mono_family_still_resolves_to_mono_regular(self):
        from luvatrix_core.core.ui_frame_renderer import _resolve_system_font_path

        path = _resolve_system_font_path("Menlo")
        name = os.path.basename(path).lower()
        assert "mono" in name or "comic" in name, f"mono request lost its mono fallback: {path}"
        assert "bold" not in name and "oblique" not in name and "italic" not in name, \
            f"regular face must be preferred over display variants: {path}"

    @needs_dejavu
    def test_empty_family_keeps_legacy_mono_default(self):
        from luvatrix_core.core.ui_frame_renderer import _resolve_system_font_path

        name = os.path.basename(_resolve_system_font_path("")).lower()
        assert "mono" in name or "comic" in name, f"default family drifted off mono: {name}"


@needs_dejavu
@needs_wqy
class TestFontChainSelection:
    def _chain(self, size: float = 26.0) -> ff.FontChain:
        primary = ff._load_chain_font(DEJAVU_MONO, size)
        cjk = ff._load_chain_font(WQY_CJK, size)
        assert primary is not None and cjk is not None
        return ff.FontChain(primary, [cjk])

    def test_primary_wins_for_covered_ascii(self):
        chain = self._chain()
        assert chain.font_for("A") is chain.primary
        assert chain.font_for(" ") is chain.primary  # whitespace never falls back

    def test_cjk_char_falls_back_to_covering_font(self):
        """The '[][]shamu[][]' case: DejaVuSansMono has no CJK, wqy does."""
        chain = self._chain()
        pick = chain.font_for("中")
        assert pick is not chain.primary
        assert pick.getlength("中") > 0

    def test_notdef_policy_when_nothing_covers(self):
        """A char no font in the chain covers renders the PRIMARY's .notdef —
        a visible tofu box beats a silent gap (and matches the old behavior
        as a last resort)."""
        chain = self._chain()
        assert chain.font_for("\U0010FFFE") is chain.primary

    def test_split_runs_groups_consecutive_chars_by_font(self):
        chain = self._chain()
        runs = ff.split_runs(chain, "ab中cd")
        assert [text for _, text in runs] == ["ab", "中", "cd"]
        assert runs[0][0] is chain.primary and runs[2][0] is chain.primary
        assert runs[1][0] is not chain.primary

    def test_default_ignorables_are_dropped_not_tofu(self):
        """Alec's live library on ae7fcc2: "🌶️[]beepboop" — the box after the
        pepper is U+FE0F VARIATION SELECTOR-16. Default-ignorable format
        chars (category Cf + variation selectors) have no visible glyph in
        any chain font, so the .notdef policy drew a box. They must render
        INVISIBLE (zero-width), never tofu."""
        chain = self._chain()
        runs = ff.split_runs(chain, "ab\ufe0fcd")
        assert [text for _, text in runs] == ["abcd"], "VS16 drops out of the runs"
        runs_zwj = ff.split_runs(chain, "a\u200db")
        assert [text for _, text in runs_zwj] == ["ab"], "ZWJ drops out of the runs"
        width_with = sum(font.getlength(text) for font, text in runs)
        width_without = chain.primary.getlength("abcd")
        assert width_with == width_without, "dropped chars contribute zero advance"

    def test_raster_ignores_variation_selectors(self):
        from luvatrix_core.core.scene_graph import TextNode
        from luvatrix_core.platform.macos import metal_scene_target as mst

        plain = TextNode("中", x=0, y=0, font_family="DejaVu Sans Mono",
                         font_size_px=26, color_rgba=(255, 255, 255, 255))
        with_vs = TextNode("中\ufe0f", x=0, y=0, font_family="DejaVu Sans Mono",
                           font_size_px=26, color_rgba=(255, 255, 255, 255))
        img_plain = mst._rasterize_text_node(plain, scale=1.0)
        img_vs = mst._rasterize_text_node(with_vs, scale=1.0)
        assert img_plain is not None and img_vs is not None
        assert img_vs.tobytes() == img_plain.tobytes(), \
            "a trailing variation selector must not add a tofu box"


@needs_noto_emoji
class TestBitmapStrikeFonts:
    def test_color_emoji_font_loads_at_native_strike_scaled_down(self):
        """NotoColorEmoji only offers a 109px strike — loading it at 13px
        raises 'invalid pixel size'. The chain must load the native strike
        and scale renders down, or emoji stay tofu on macOS too (Apple Color
        Emoji is likewise bitmap-only)."""
        cfont = ff._load_chain_font(NOTO_EMOJI, 13.0)
        assert cfont is not None
        assert cfont.scale_down > 1.0, "expected a strike-size font marked for downscaling"
        assert cfont.covers("\U0001F525")
        length = cfont.getlength("\U0001F525")
        assert 8.0 <= length <= 30.0, f"advance should be in requested-px units, got {length}"

    def test_bitmap_font_getmetrics_in_requested_units(self):
        cfont = ff._load_chain_font(NOTO_EMOJI, 13.0)
        assert cfont is not None
        ascent, descent = cfont.getmetrics()
        assert ascent <= 30.0, f"metrics must be scaled to requested px, got {ascent}"


@needs_dejavu
@needs_wqy
class TestRasterIntegration:
    """Integration through the real render paths (family resolution → chain →
    pixels). Pre-fix these render the sentinel's .notdef box for every char."""

    def test_metal_text_raster_uses_fallback_ink_for_cjk(self):
        from luvatrix_core.core.scene_graph import TextNode
        from luvatrix_core.platform.macos import metal_scene_target as mst

        node = TextNode("中", x=0, y=0, font_family="DejaVu Sans Mono",
                        font_size_px=26, color_rgba=(255, 255, 255, 255))
        tofu = TextNode("\uFFFE", x=0, y=0, font_family="DejaVu Sans Mono",
                        font_size_px=26, color_rgba=(255, 255, 255, 255))
        img = mst._rasterize_text_node(node, scale=1.0)
        box = mst._rasterize_text_node(tofu, scale=1.0)
        assert img is not None and box is not None
        assert img[:, :, 3].sum() > 0, "CJK glyph should have ink"
        assert img.tobytes() != box.tobytes(), "CJK glyph must not render as the .notdef box"

    def test_headless_rasterizer_uses_fallback_ink_for_cjk(self):
        from luvatrix_core.core.scene_graph import TextNode
        from luvatrix_core.core.scene_rasterizer import _text_mask_for_node

        node = TextNode("中", x=0, y=0, font_family="DejaVu Sans Mono",
                        font_size_px=26, color_rgba=(255, 255, 255, 255))
        tofu = TextNode("\uFFFE", x=0, y=0, font_family="DejaVu Sans Mono",
                        font_size_px=26, color_rgba=(255, 255, 255, 255))
        mode, mask, _, _ = _text_mask_for_node(node, 1.0, 1.0)
        t_mode, t_mask, _, _ = _text_mask_for_node(tofu, 1.0, 1.0)
        assert mode == "blend" and t_mode == "blend"
        assert mask.sum() > 0
        assert mask.tobytes() != t_mask.tobytes()


@needs_dejavu
@needs_noto_emoji
class TestEmojiRasterIntegration:
    def test_metal_text_raster_renders_emoji_not_tofu(self):
        from luvatrix_core.core.scene_graph import TextNode
        from luvatrix_core.platform.macos import metal_scene_target as mst

        node = TextNode("\U0001F525", x=0, y=0, font_family="DejaVu Sans Mono",
                        font_size_px=26, color_rgba=(255, 255, 255, 255))
        tofu = TextNode("\uFFFE", x=0, y=0, font_family="DejaVu Sans Mono",
                        font_size_px=26, color_rgba=(255, 255, 255, 255))
        img = mst._rasterize_text_node(node, scale=1.0)
        box = mst._rasterize_text_node(tofu, scale=1.0)
        assert img is not None and box is not None
        assert img[:, :, 3].sum() > 0, "emoji glyph should have ink"
        assert img.tobytes() != box.tobytes(), "emoji must not render as the .notdef box"
