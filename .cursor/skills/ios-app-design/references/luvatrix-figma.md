# Expressing iOS design in luvatrix Figma JSON

Read this before editing `examples/nomic_ios/assemble_capture.py` or any Figma document that luvatrix renders on iOS. Code references are to the repository as of November 4, 2026.

## How a screen becomes pixels

1. `examples/nomic_ios/assemble_capture.py` turns captured web frames into `design/figma_file.json`. It shifts content down by `STATUS_CLEAR_PT` and appends a tab bar from `build_tab_bar_node` as the last child of each screen.
2. `luvatrix_ui/figma/document.py` loads the document and resolves prototype interactions, overlays, and transitions.
3. `luvatrix_ui/figma/render.py` rasterizes nodes. `luvatrix_ui/figma/app.py` (`FigmaApp`) composes screens, scrolls them, and runs transitions.
4. On iOS, the Metal presenter letterboxes the app's fixed `native_width×native_height` matrix into the device drawable (scale = the smaller of the two axis ratios) and fills the leftover bars with `[display] bar_color_rgba` from `app.toml`.

Fix design problems in the **builder** (`assemble_capture.py`), then regenerate the JSON. Hand edits to `figma_file.json` are lost on the next assembly.

## JSON patterns

**Screen frame**
- One top-level `FRAME` per screen, with `absoluteBoundingBox` width equal to the viewport width (393 today).
- `app.toml` `[display] native_width/native_height` sets the viewport (393×852 today). This is the iPhone 16 point size [S-LAYOUT-ARCHIVE], not the iPhone 17 size of 402×874 pt.
- Content taller than the viewport needs `overflowDirection: "VERTICAL_SCROLLING"`. `FigmaApp._screen` only treats a frame as scrolling when its scaled height exceeds the matrix height.

**Fixed bars (tab bar, top toolbar, floating buttons)**
- Fixed children are the frame's **last N children**, where N is `numberOfFixedChildren`. Put bars at the end of `children`.
- Position fixed children in frame coordinates for the viewport, for example the tab bar at `y = VIEWPORT_H - bar height`.

**Safe areas in a 393×852 frame** (iPhone 16 insets [T-SAFEAREA])
- Top: keep text and controls below 59 pt. `STATUS_CLEAR_PT = 59.0` does this.
- Bottom: keep labels and tap targets above 818 pt (852 − 34). Only the bar's background should extend into the home-indicator zone.
- If the frame moves to 402×874 for iPhone 17, the insets become 62 pt top and 34 pt bottom [T-SAFEAREA], so the bottom limit becomes 840 pt.

**Approximating a Liquid Glass tab bar**

The renderer has no Liquid Glass material. The closest honest approximation of the floating tab bar [S-TABBARS] is:
- A capsule `FRAME`, inset from the screen edges, with `cornerRadius` equal to half its height. Capsule is one of Apple's three concentric shape types [S-WWDC25-356].
- A translucent `SOLID` fill (`opacity` below 1), so scrolled content shows through. Pick the opacity by testing label legibility over the busiest content, because people can push iOS 27 glass toward ultra-clear [S-NEWSROOM-WWDC26].
- Icons and labels above the home-indicator zone.
- Inner selection highlights with a concentric radius: the bar radius minus the padding [S-WWDC25-356].
- Monochrome icons and labels, or one accent for the selected tab [S-COLOR].
- Content extending to the bottom of the frame, under the bar [S-LAYOUT].

Apple publishes no point dimensions for the floating tab bar (height, side inset, or bottom offset). Take them from the iOS 27 Figma kit [S-DESIGNKITS] and record the source in the builder.

## Renderer capabilities and limits

| Feature | Status | Where |
|---|---|---|
| `SOLID` fills with `opacity` | Supported | `render.py` |
| Linear, radial, angular, and diamond gradients; `IMAGE` paints | Supported | `luvatrix_ui/figma/paint.py` |
| `cornerRadius`, per-corner `rectangleCornerRadii` | Supported | `render.py` `corner_radii` |
| `DROP_SHADOW`, `INNER_SHADOW`, `LAYER_BLUR` | Supported | `render.py` |
| `BACKGROUND_BLUR` on in-flow nodes, or fixed nodes on non-scrolling frames | Supported: blurs what is already drawn beneath the node, before its fill | `render.py` `_draw_self` |
| `BACKGROUND_BLUR` on a fixed child of a **scrolling** frame | **Doesn't work.** See below. | `app.py` `_screen` |
| Node and paint `blendMode` | Supported | `render.py` |
| Prototype transitions: `DISSOLVE`, `SMART_ANIMATE`, `SCROLL_ANIMATE`, `PUSH`, `MOVE_IN`, `MOVE_OUT`, `SLIDE_IN`, `SLIDE_OUT` | Supported | `transitions.py`, `smart_animate.py` |
| Overlays (`overlayPositionType`, `overlayBackground`, close on click outside) | Supported, through `FigmaApp.open_overlay` | `document.py`, `app.py` |
| Specular highlights, refraction, live glass, scroll edge effect | **Not supported** | — |
| SF Pro, SF Symbols | **Not available.** See Fonts. | — |
| Dark Mode or Dynamic Type switching | **Not supported.** The document has one fixed appearance and fixed sizes. | — |
| Resizing to the device (iPhone 17, iPhone Duo) | **Not supported.** The matrix is fixed and letterboxed. | `app.toml`, Metal presenter |

**Why `BACKGROUND_BLUR` fails on scrolling bars.** For a scrolling frame, `FigmaApp._screen` renders the content with the fixed children skipped, then renders the fixed children alone (`only_ids=fixed, transparent=True`) into a separate overlay. `_compose` pastes that overlay over the scrolled content. When the bar's blur runs, the overlay canvas beneath it is empty, so there's nothing to blur. A translucent fill still composites correctly over the content. Real blur behind a scrolling bar needs a renderer change that blurs the composed content inside the overlay window each frame.

**Fonts.** `luvatrix_ui/figma/text.py` resolves a family from `LUVATRIX_FONT_DIRS`, then the bundled `luvatrix_ui/figma/fonts` (Inter Regular, Medium, SemiBold, and Bold), then system font directories. An unknown family falls back to Inter. Apple tells apps not to embed system fonts [S-TYPOGRAPHY], so use Inter as the SF Pro stand-in. Use the Dynamic Type Large sizes from SKILL.md, and draw icons as vector paths in the style of SF Symbols (filled for tab bars [S-TABBARS]).

**Sheets and modals.** Model a sheet as a full-width overlay frame anchored with `overlayPositionType: "BOTTOM_LEFT"`, plus an `overlayBackground` dim and `overlayBackgroundInteraction: "CLOSE_ON_CLICK_OUTSIDE"`. `FigmaApp._overlay_origin` only knows `TOP_LEFT`, `TOP_RIGHT`, `BOTTOM_LEFT`, and `BOTTOM_RIGHT`; anything else, including `BOTTOM_CENTER`, is centered. Draw the grabber when the sheet is resizable, and put Cancel on the leading edge and Done on the trailing edge [S-SHEETS]. There are no detents or drag-to-resize gestures; a sheet is one fixed height.

## Verification loop

1. Regenerate the document: `uv run python examples/nomic_ios/assemble_capture.py --captures <name>=<capture-dir> ... --out examples/nomic_ios/design`, adding `--renders` and `--click-map` as needed.
2. Validate the app: `uv run python main.py validate-app examples/nomic_ios --render ios-simulator`.
3. Run the simulator tour on macOS with Xcode:

   ```bash
   uv run python main.py figma ios-tour examples/nomic_ios \
     --tour examples/nomic_ios/tour.json \
     --out /tmp/ios-tour \
     --simulator "iPhone 17" \
     --native-project examples/nomic_ios/ios
   ```

   On Linux, push a `feature/**` or `dev-alec/**` branch instead. The `iOS Simulator Tour` workflow (`.github/workflows/ios-sim-tour.yml`) runs the same command on a macOS runner and uploads the artifact `ios-tour-<slug>-<run_id>`. Download it with `gh run download <run_id>`.
4. Read the output: `NN_<capture>.png` screenshots, `summary.json`, `console.log`, and `app_log.txt`.
5. Screenshots are 1206×2622 px on iPhone 17 at 3x [S-IPHONE17-SPECS]. Divide pixel coordinates by 3 to get points, then run the checklist in SKILL.md.
6. Remember the letterbox: a 393×852 matrix scales by about 1.023 into 402×874, leaving about 1.25 pt of `bar_color_rgba` at the top and bottom. Design coordinates map to device points as `device = design × 1.023 + 1.25` on the y axis.
