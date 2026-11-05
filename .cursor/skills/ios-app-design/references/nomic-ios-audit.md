# examples/nomic_ios: known deviations

Audit date: **November 4, 2026**, against the generated `examples/nomic_ios/design/figma_file.json`, `assemble_capture.py`, `app.toml`, and `ios/project.yml`. Nothing here has been changed in the app; these are recorded deviations to fix in later work. Fix them in `assemble_capture.py` (`build_tab_bar_node`, `assemble_screen`, and the constants at the top), not in the generated JSON.

## Status after the visual polish pass

Later the same day, a polish pass driven by headless 3x renders of every screen in both appearances fixed five more defects:

- **Dark-mode icons were invisible.** The dark capture themed text and gray icons (gray-500 to gray-400, gray-700 to gray-100) but left 75 `currentColor` svg glyphs pure black on the gray-900 canvas — the wordmark measured 1.1:1, and the sidebar toggle, composer `+`/chevrons, share, copy/thumbs, Drive toolbar, and Profile nav icons all vanished (icon regions measured within noise of the background). `recolor_dark_icons` in the assembler now maps near-black vector fills to gray-100, skipping glyphs on colorful surfaces: the six glyphs on the teal Dictate/Search/Upload/New-project buttons stay black, as on the real site.
- **sr-only text leaked as ink.** The "Toggle Sidebar" `span.sr-only` rendered clipped inside its 28 pt button, painting three stray dots under the sidebar icon on every screen in both appearances. `drop_sr_only_texts` removes them (5 per variant).
- **The selected tab now uses the product accent, not a gray pill.** Apple's tab bars carry selection with a single accent tint on the symbol and label [S-TABBARS], [S-COLOR]; the pill read as Material. The light accent is teal-600 (oklch(55.8% 0.068 169) = 73,129,109, the token the product uses for its active sidebar item): 4.3:1 on gray-50, on par with Apple's own system-blue labels. The dark accent is teal-400 (122,167,151): 6.3:1 on the gray-900 glass. Unselected tabs keep gray-500/gray-400; the selected label keeps its heavier weight.
- **Conversation keeps the Assistant tab selected.** It is a detail flow, not a tab destination; `ACTIVE_TAB_OVERRIDES` records the mapping.
- **The pinned composer no longer touches the tab bar.** It hovers `COMPOSER_BAR_GAP_PT` (10 pt) above the capsule; before, its bottom met the bar's top edge exactly.

The committed design documents are regenerated without a capture session via `python examples/nomic_ios/assemble_capture.py --refresh examples/nomic_ios/design`, which re-applies the builder's authored chrome (tab bars, artifact drops, dark recolor, composer gap) to the assembled JSON.

Deviations 8 (SF Pro and Dynamic Type), 9 (layered icon), and 10 (iPhone Duo) below remain open. Bar metrics remain chosen, not measured, pending the iOS 27 Figma kit [S-DESIGNKITS].

## Status after the Dark Mode change

Later the same day, the app gained a real second appearance. Deviation 7 below is fixed:

- All five screens were recaptured in both appearances at 402×874@3 (`figma capture --color-scheme dark` drives next-themes via `prefers-color-scheme` emulation). The assembler emits `design/figma_file.json` (light) and `design/figma_file.dark.json`; frame ids are stable across appearances, so navigation maps 1:1.
- The tab bar keeps the glass-branch geometry in both appearances, with authored colors derived from the Nomic palette (drive-next `apps/drive-next/src/app/globals.css`): light tint gray-50 (250, 250, 249) at 72% with gray-700/gray-500 symbols, dark tint gray-900 (25, 29, 26) at 66% with gray-100/gray-400 symbols, and a white selection wash at 14% in dark. The grays lean teal (hue ~153) and neither canvas is pure black or white. The bar stays monochrome [S-COLOR]; the teal accent is deliberately unused in it. Opacities and metrics remain chosen, not measured, pending the iOS 27 Figma kit [S-DESIGNKITS].
- `FigmaApp` holds light and dark design variants and switches on `set_appearance`, the `LUVATRIX_APPEARANCE` override, or the iOS `UITraitCollection.userInterfaceStyle` trait (bridged through the runner; the Swift shell forwards `traitCollectionDidChange`). The current screen, back history, and scroll position carry over by frame name.
- `Info.plist` and `project.yml` no longer pin `UIUserInterfaceStyle: Light`; the status bar uses `UIStatusBarStyleDefault`, so it draws light content in Dark Mode and dark content in Light Mode automatically. The category is still productivity.
- `bar_color_rgba` stays white: the 402×874 design maps 1:1 to iPhone 17 points, so there are no letterbox bars in either appearance. Revisit if the design size ever differs from the device.

Deviations 8 (SF Pro and Dynamic Type), 9 (layered icon), and 10 (iPhone Duo) remain open. The dark bar metrics are chosen, not measured; replace them with iOS 27 Figma kit values.

## Status after the floating glass tab bar change

Later the same day, the app was recaptured at 402×874@3 and rebuilt. Deviations 1–6, 11, and 12 below are fixed:

- The tab bar is a floating capsule: 370×62 pt at y = 778, 16 pt side insets, radius 31. It uses real background blur (the renderer now blurs scrolled content under fixed layers), a 72% light tint, a hairline edge, a top highlight, and a soft shadow.
- Labels are 11 pt and the whole bar ends at 840 pt, above the home indicator. Tab slots are 90.5×54 pt.
- Icons are filled glyphs. Symbols and labels are monochrome (selected 24, unselected 102 gray), and the selected tab gets a concentric radius-27 pill.
- The frame is 402×874, so there's no letterbox. The Conversation composer is pinned above the bar, and a top scroll edge fade keeps scrolled content out from under the status bar.
- `Info.plist` pins dark status bar content and the Light appearance (superseded by the Dark Mode change above: the pin is gone and the status bar follows the trait), and the category is productivity with the game-mode keys removed.

Deviations 7 (Dark Mode), 8 (SF Pro and Dynamic Type), 9 (layered icon), and 10 (iPhone Duo) remain open. The bar metrics are chosen, not measured; replace them with iOS 27 Figma kit values. (Deviation 7 was fixed by the Dark Mode change above.)

The original audit follows unchanged.

Where a finding depends on what the simulator shows rather than on the JSON, it says "verify in a screenshot."

## The design as built

- Five screens: Assistant, Conversation, Drive, Projects, and Profile. Each is a 393×991 `FRAME` with `overflowDirection: "VERTICAL_SCROLLING"` and `numberOfFixedChildren: 1`.
- The viewport is 393×852 (`FRAME_W`, `VIEWPORT_H`, and `app.toml` `native_width/native_height`).
- Content is shifted down by `STATUS_CLEAR_PT = 59.0`.
- The fixed child is `tab:bar`: a 393×80 frame at y = 772 with an opaque black `SOLID` fill, no `cornerRadius`, and no effects. It has four 98.25×80 tab slots (Assistant, Drive, Projects, Profile), each with a 24 pt outline vector icon at y + 16 and an Inter 10 pt label at y + 50.
- Screen backgrounds are white, so the app is light content over a black bar.
- `app.toml` sets `bar_color_rgba = [0, 0, 0, 255]`.

## Deviations, highest impact first

1. **The tab bar is an opaque full-width slab, not a floating glass control.** The iOS tab bar floats above content on Liquid Glass [S-TABBARS], content should extend under it [S-LAYOUT], and controls should be separated from content with a scroll edge effect rather than a solid background [S-LAYOUT]. Ours is edge-to-edge, square-cornered, fully opaque, and hides everything under it. Fix direction: an inset capsule (`cornerRadius` = height / 2) with a translucent fill; see `luvatrix-figma.md`.

2. **Tab labels are 10 pt, below the 11 pt iOS minimum** [S-TYPOGRAPHY]. All 20 label nodes (4 per screen) use `fontSize: 10`.

3. **Tab labels sit in the home-indicator zone.** Labels span y = 822–834. The bottom 34 pt (818–852) on a 393×852 frame is the home-indicator safe area [T-SAFEAREA]. Icons (788–812) are clear of it. Only the bar's background should reach into that zone.

4. **The design frame is iPhone 16, but CI runs iPhone 17.** 393×852 pt is the iPhone 16 size; iPhone 17 is 402×874 pt [S-LAYOUT-ARCHIVE]. The Metal presenter scales by about 1.023 and leaves about 1.25 pt of black letterbox at the top and bottom over white content. The content top lands at about 61.6 device pt, close to iPhone 17's 62 pt top inset [T-SAFEAREA], so the status-bar clearance is roughly right by accident. Verify in a screenshot that the thin black bands at the top and bottom edges aren't visible against white content.

5. **Tab icons are custom outline strokes, not filled SF Symbol-style glyphs.** Apple prefers filled SF Symbols in tab bars [S-TABBARS]. Ours are 1.8-weight strokes on a 24-unit grid.

6. **Selected-tab color is not monochrome.** The active tab uses the accent (94, 92, 230) for the icon and white for the label; inactive tabs use gray (152, 152, 159). Apple's default for bar symbols and text is monochrome, with color applied sparingly [S-COLOR]. A single distinct accent for the selection is defensible, but mixing accent icons with white labels is two colors for one state.

7. **Light appearance only; no Dark Mode.** Apps should support both appearances [S-DARKMODE]. The document has one white-background appearance, and the renderer can't switch appearances. `Info.plist` sets neither `UIUserInterfaceStyle` nor `UIStatusBarStyle`, so when the simulator is in Dark Mode the system status bar may draw white text over our white content. Verify in a screenshot with the simulator in each appearance.

8. **Fonts aren't SF Pro, and there's no Dynamic Type.** The JSON uses `switzer` (69 text nodes) and `Inter` (20). Only Inter is bundled (`luvatrix_ui/figma/fonts`), and unknown families fall back to Inter, so switzer text almost certainly renders as Inter on iOS. Verify in a screenshot. Sizes are fixed (10, 12, 13, 14, 16, 18, and 24 pt; 14 pt is the most common, on 42 nodes) and don't follow the Dynamic Type Large sizes, where body text is 17 pt [S-TYPOGRAPHY]. Apple asks apps to support text enlargement to at least 200% [S-ACCESSIBILITY]; the renderer can't.

9. **The app icon is one opaque 1024×1024 bitmap.** `AppIcon` has a single universal `icon.png`. A bitmap is allowed, but the preferred format is a layered Icon Composer file, and without supplied variants the system generates the dark, clear, and tinted appearances and tries to segment the bitmap itself [S-APPICONS]. Check that the icon has no baked-in rounded corners, shadows, or text.

10. **No iPhone Duo support.** The app is portrait-only with `UIRequiresFullScreen: true`, renders a fixed 393×852 matrix, and draws its own tab bar instead of a system `UITabBar`. Vertical bars on iPhone Duo come only from standard system components built with the iOS 27.1 SDK [S-HIG-DUO], [S-DUO-PREPARE], so this app would keep a horizontal bar and letterbox on both iPhone Duo displays. Apple also says not to lay out from fixed screen sizes [S-DUO-PREPARE]. This is a renderer-architecture limit, not a quick fix.

11. **Adding `BACKGROUND_BLUR` to the bar would do nothing today.** All five screens scroll, and fixed children of scrolling frames render into a separate transparent overlay (`luvatrix_ui/figma/app.py` `_screen`), so a background blur on `tab:bar` has nothing to blur. A translucent fill would still show content.

12. **Minor: the App Store category is games.** `ios/project.yml` sets `LSApplicationCategoryType: public.app-category.games`, which doesn't match a productivity app. This isn't a HIG rule.

## What already conforms

- **Touch targets.** Each tab slot is 98.25×80 pt, well above 44×44 pt [S-BUTTONS].
- **Tab count.** Four tabs, so there's no More overflow; Apple's guidance aims for five or fewer by default [S-TABBARS].
- **Tab labels** are single words [S-TABBARS].
- **Bar contrast.** Computed with the WCAG relative-luminance formula against the black bar: inactive gray is about 7.2:1, the active white label 21:1, and the accent icon about 4.1:1. Labels meet 4.5:1 [S-ACCESSIBILITY]. The accent icon would fail 4.5:1 if used for small text; for icons it clears WCAG's 3:1 non-text contrast criterion (WCAG 2.1, 1.4.11, https://www.w3.org/TR/WCAG21/#non-text-contrast), which is a WCAG rule rather than a HIG number.
- **Top clearance.** 59 pt matches the iPhone 16 top inset [T-SAFEAREA], and with the letterbox it lands near iPhone 17's 62 pt.
