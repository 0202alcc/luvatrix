---
name: ios-app-design
description: Design or review iOS apps to Apple's current Human Interface Guidelines — Liquid Glass (iOS 26, refined in iOS 27), floating tab bars and toolbars, safe areas, Dynamic Island, iPhone 17 family and the foldable iPhone Duo, Dynamic Type, SF Symbols, Dark Mode, accessibility, and layered Icon Composer app icons — and express that design in luvatrix Figma JSON (examples/nomic_ios, luvatrix_ui/figma). Use when designing, building, assembling, or reviewing an iOS screen, tab bar, navigation bar, sheet, or app icon; when auditing ios-tour simulator screenshots; or when someone mentions Liquid Glass, HIG, iPhone Duo, foldable iPhone, or "make it look native on iOS".
---

# iOS app design (Liquid Glass era)

This skill covers two things:

1. Apple's current iOS design rules, as of iOS 27 and iPhone Duo.
2. How to express them in the Figma documents that luvatrix renders on iOS.

The guidance comes from Apple's Human Interface Guidelines (HIG), Apple Newsroom, and WWDC session pages, all fetched on **November 4, 2026**. Every numeric spec carries a source tag. Look up the full URLs, Apple's own revision dates, and the reliability tier of each source in [`references/sources.md`](references/sources.md).

**Never invent a point size.** If no source below gives a number, say that it isn't published. Measure it from Apple's iOS 27 Figma kit or a simulator screenshot, and record where the number came from.

## Workflow

1. **Know the target.** iOS 27 is current. iPhone 17 is our CI simulator, at 402×874 pt [S-LAYOUT-ARCHIVE]. iPhone Duo is a real shipping device, so decide up front whether you support it. See [Devices](#devices-and-safe-areas).
2. **Split the screen into two layers.** The *content layer* holds lists, cards, media, and backgrounds. The *control layer* holds the tab bar, toolbars, and floating buttons. Only the control layer gets Liquid Glass.
3. **Lay out content edge to edge.** Content runs under both bars. Inset only text and controls, using the safe area.
4. **Use system patterns before custom ones.** That means a tab bar for top-level sections, a toolbar or navigation bar for actions and titles, and sheets for scoped tasks.
5. **Express the design in Figma JSON.** Follow [`references/luvatrix-figma.md`](references/luvatrix-figma.md), and respect what the renderer can't do.
6. **Verify on the simulator.** Run `ios-tour` and work through the [screenshot checklist](#screenshot-review-checklist).

## Liquid Glass principles

Liquid Glass is the material Apple introduced in iOS 26 and refined in iOS 27. It is a dynamic glass layer for controls and navigation that floats above content. Content scrolls and peeks through underneath, and the glass stays legible [S-MATERIALS].

**Controls layer vs content layer**
- **Use glass for controls and navigation only.** Tab bars, toolbars, sidebars, and floating buttons qualify. Don't put Liquid Glass in the content layer, such as app backgrounds, table views, or cards. Use the standard materials there instead: ultra-thin, thin, regular, and thick [S-MATERIALS], [S-WWDC25-219].
  - The one exception is a transient interactive control in content, such as a slider or toggle. It takes on glass only while someone is using it [S-MATERIALS].
- **Use glass sparingly.** Apply it only to the most important functional elements. Overuse distracts from the content [S-MATERIALS].
- **Don't put glass on glass.** For elements that sit on a glass surface, use fills, transparency, and vibrancy instead [S-WWDC25-219].

**Bars float; content goes underneath**
- **The iOS tab bar floats** above content at the bottom of the screen, on a Liquid Glass background [S-TABBARS].
- **Extend full-screen backgrounds** underneath sidebars, toolbars, and tab bars so they fill the whole screen [S-LAYOUT].
- **Separate controls from content with a scroll edge effect,** not a solid or semi-opaque background color under the controls [S-LAYOUT].
  - A scroll edge effect is a blur and fade of content at the bar edge.
  - It isn't decorative. Use it only where a scroll view sits behind floating UI, and use one per view [S-SCROLLVIEWS].
- **Keep toolbar backgrounds and tinted controls to a minimum.** Let the content layer inform the bar's color [S-TOOLBARS].

**Variants and color**
- **Regular glass** blurs content and adjusts its luminosity. Most system components use it. Use it where text sits on the glass [S-MATERIALS].
- **Clear glass** is highly translucent. Use it only over visually rich media such as photos and video.
  - If the content behind clear glass is bright, consider a **dark dimming layer at 35% opacity** [S-MATERIALS].
- **Glass has no color of its own.** On tab bars and toolbars, symbols and text are monochrome by default: darker over light content, lighter over dark content [S-COLOR].
  - Apply color sparingly. To emphasize a primary action, tint the control's background, not its symbol or text, as the Done button does.
  - Don't tint the backgrounds of several controls [S-COLOR].
- **Avoid tab or toolbar label colors that match the content background.** If content is colorful, prefer monochrome bars [S-TABBARS], [S-TOOLBARS].
- **Keep the resting state legible.** At the top of a scroll view, before anything scrolls, nothing colorful should sit under the controls [S-COLOR].

**Shape: concentric corners**
- **Nest shapes concentrically.** Align radii and margins around a shared center so shapes fit inside each other [S-WWDC25-356]. There are three shape types:
  - **Fixed:** a constant radius.
  - **Capsule:** a radius of half the container's height.
  - **Concentric:** the parent's radius minus the padding between them.
- **Make custom components inside bars concentric.** Their corner radius must match the bar's corners [S-TOOLBARS].
- App icons follow the same logic. The system masks them so their corners match the device bezel and other rounded UI elements [S-APPICONS].

**Legibility and accessibility**
- **Glass adapts to accessibility settings automatically** [S-WWDC25-219]:
  - Reduce Transparency makes glass frostier and hides more of the content behind it.
  - Increase Contrast makes elements predominantly black or white, with a contrasting border.
  - Reduce Motion tones down effects and disables the material's elastic behavior.
- **People can tune glass themselves.** iOS 27 adds a Settings slider that ranges from "ultra-clear" to "fully tinted" [S-NEWSROOM-WWDC26]. Never depend on a specific translucency level for legibility.
- **Test both appearances.** Check Light and Dark Mode, each with Increase Contrast and Reduce Transparency on, separately and together [S-DARKMODE].

**iOS 27 changes** [S-NEWSROOM-WWDC26]:
- The Liquid Glass personalization slider described above.
- Sharper, more defined app icons.
- Updated scroll edge effect guidance (June 8, 2026) [S-SCROLLVIEWS].
- Secondary reporting [S-MACRUMORS-IOS27] adds that glass diffuses complex content more, has a darkened edge and brighter specular highlights, and puts a uniform top toolbar over scrolled content. Treat these as unverified until confirmed in the iOS 27 Figma kit or the simulator.

## Devices and safe areas

[`references/devices.md`](references/devices.md) has the full tables and source tiers. Key facts:

| Device | Points (portrait) | Source |
|---|---|---|
| iPhone 17, iPhone 17 Pro (our design frame) | 402×874 pt (1206×2622 px @3x) | [S-LAYOUT-ARCHIVE] |
| iPhone Air | 420×912 pt | [S-LAYOUT-ARCHIVE] |
| iPhone 17 Pro Max | 440×956 pt | [S-LAYOUT-ARCHIVE] |
| iPhone 16 / 15 / 15 Pro / 14 Pro | 393×852 pt | [S-LAYOUT-ARCHIVE] |
| iPhone Duo outer display | Apple: 1398×2034 px at 460 ppi; points not published by Apple | [S-DUO-SPECS] |
| iPhone Duo inner display | Apple: 1878×2670 px at 430 ppi; points not published by Apple | [S-DUO-SPECS] |

**The HIG no longer lists device sizes.** Apple's September 9, 2026 Layout revision removed the device table. The 402×874 figures above come from Apple's own table in an archived copy of the page (snapshot of June 16, 2026).

**Safe areas**
- **Respect the safe area.** It keeps the Dynamic Island, the status bar, and system bars from covering content and controls [S-LAYOUT].
- **Apple doesn't publish iPhone inset values.** Third-party simulator measurements [T-SAFEAREA]:
  - iPhone 17 (portrait): top 62 pt, bottom 34 pt (the home indicator).
  - iPhone 16 (portrait): top 59 pt, bottom 34 pt.
- Use these for Figma frames, and re-measure from an `ios-tour` screenshot when it matters.

**Touch targets and spacing**
- **Hit regions:** at least 44×44 pt [S-BUTTONS]. Default control size is 44×44 pt, and the minimum is 28×28 pt [S-ACCESSIBILITY].
- **Padding:** about 12 pt around bezeled elements, and about 24 pt around elements without a bezel [S-ACCESSIBILITY].
- **Margins:** Apple publishes no iPhone margin value in points. Apple points to Apple Design Resources (the iOS 27 Figma kit) for margins and safe areas [S-HIG-DUO], [S-DESIGNKITS]. Read them from the kit.

**iPhone Duo (real device, shipped October 23, 2026)**

iPhone Duo is Apple's first foldable iPhone. It has a 5.4-inch outer display and a 7.6-inch inner display with the same aspect ratio, and it runs iOS 27.1 [S-NEWSROOM-DUO]. What it changes [S-HIG-DUO], [S-DUO-PREPARE]:
- **Bars move to the side.** On the outer display, and on the inner display in landscape, the system moves toolbars, tab bars, and navigation controls to the **side** of the screen.
  - It also places the Dynamic Island and the status bar vertically on the trailing edge.
  - The inner display in portrait keeps horizontal bars.
  - Apps built with the iOS 27.1 SDK get vertical bars automatically, but only from **standard system components**.
- **Reserved regions:**
  - The outer camera is always present.
  - The inner camera is reserved only while it's active.
  - The folding region applies when the device is partially open.
  - Use `ReservedRegion` and arrangement views. In grids, prefer an even number of columns so the fold splits them cleanly.
- **Size classes, not device checks:**
  - Use a compact-width layout for the outer display and a regular-width (iPad-like) layout for the inner display.
  - Never base layout on `UIScreen.main`, orientation, idiom, or hard-coded screen sizes.
- **Older SDKs get letterboxed.** Apps built with the iOS 26 SDK or earlier run centered on the inner display with empty space around them. On the outer display, their content sits to the left of the status bar and camera.

Third-party simulator measurements report 466×678 pt (outer) and 951×669 pt (inner, landscape), with an 84 pt trailing safe-area column [T-SAFEAREA-DUO]. Their pixel counts disagree with Apple's published specs, so treat them as **unverified**.

## Navigation

- **Tab bars** [S-TABBARS]:
  - **For navigation, not actions.** Use a toolbar for actions.
  - **Always visible** except under a modal. Never hide or disable tabs.
  - **Few tabs.** Avoid overflow: the trailing tab turns into **More** when space runs out. Apple's iPadOS customization guidance says to aim for a default of five or fewer tabs.
  - **Labeled.** One word per label where possible.
  - **SF Symbols, preferably filled.**
  - **Badges** only for critical information.
  - **Search tab.** A search tab can sit at the trailing end, either as a standard tab with a search landing page, or with the button appearance, which focuses the field right away [S-SEARCH].
  - **Minimize on scroll.** A tab bar with an attached accessory, like Music's MiniPlayer, can shrink when someone scrolls down. It restores when they tap a tab or scroll back to the top.
- **Navigation bars and toolbars** [S-TOOLBARS]:
  - **Titles:** under 15 characters, and never the app name.
  - **Large titles** shrink to a standard title on scroll.
  - **Back and Close** use the standard symbols, not text labels.
  - **One prominent primary action** (Done or Submit, `.prominent` style) on the trailing side.
  - **Symbols** without borders.
  - **Up to three groups,** and keep text-labeled actions separate from symbols.
- **Sheets** [S-SHEETS]:
  - **Show one sheet at a time.**
  - **Detents:** large is full height, medium is about half. Show a grabber when the sheet is resizable.
  - **Buttons:** Cancel goes on the leading edge of the top toolbar, and Done on the trailing edge.
  - **Pair Done with Cancel** or Back, and never show all three.
- **Modals:** use them for scoped tasks. A modal is the only acceptable thing to cover the tab bar [S-TABBARS].

## Typography

- **System font:** SF Pro on iOS, and apps may use New York (NY) [S-TYPOGRAPHY].
  - The HIG tells apps not to embed system fonts.
  - luvatrix rasterizes text from bundled font files, so it uses Inter as its stand-in (see [`references/luvatrix-figma.md`](references/luvatrix-figma.md)).
- **Text size:** default 17 pt, minimum 11 pt on iOS [S-TYPOGRAPHY], [S-ACCESSIBILITY].
- **Dynamic Type, Large (default) size** — style, size/leading in pt, weight [S-TYPOGRAPHY]:
  - Large Title 34/41 Regular
  - Title 1 28/34
  - Title 2 22/28
  - Title 3 20/25
  - Headline 17/22 Semibold
  - Body 17/22
  - Callout 16/21
  - Subhead 15/20
  - Footnote 13/18
  - Caption 1 12/16
  - Caption 2 11/13
  - The other sizes are tabulated on the page. Support enlarging text to at least 200% [S-ACCESSIBILITY].
- **Contrast:** at least 4.5:1 for text up to 17 pt, and 3:1 for 18 pt and up or bold text (WCAG AA) [S-ACCESSIBILITY]. Aim for 7:1 for small text on custom colors [S-DARKMODE].

## Color and Dark Mode

- **Support both appearances,** including Auto switching [S-DARKMODE].
- **Use system label and background colors.** Dark Mode uses *base* backgrounds, plus *elevated* ones for sheets and popovers [S-DARKMODE].
- **Use brand color carefully.** Your brand color can be the accent color when content is mostly monochrome. If content is colorful, keep the bars monochrome [S-COLOR].

## App icons (current format)

- **Format:** iOS takes either a **layered Icon Composer file** (preferred) or a nonlayered bitmap such as PNG [S-APPICONS].
  - Apple revised the icon-format guidance on October 28, 2026.
  - Icon Composer 2 shipped at WWDC26 [S-WHATSNEW].
- **How the system treats a bitmap:** it tries to split it into two layers. Liquid Glass goes only on large simple shapes, not on text or thin lines [S-APPICONS].
- **Canvas:** a square, unmasked 1024×1024 px canvas. The system masks the corners [S-APPICONS].
- **Appearances:** default, dark, clear light, clear dark, tinted light, and tinted dark. The system generates any you don't supply [S-APPICONS].
- **Color space:** sRGB, Gray Gamma 2.2, or Display P3.
- **Design:**
  - Use opaque full-bleed backgrounds and crisp edges on foreground layers.
  - Avoid text.
  - Don't bake in highlights, shadows, or blurs.

## Luvatrix specifics (summary)

[`references/luvatrix-figma.md`](references/luvatrix-figma.md) has the details: JSON shapes, renderer limits, and the verification loop.

- **Frames:**
  - Each screen is one top-level `FRAME` sized to the logical viewport. `app.toml` `[display] native_width/native_height` must match it.
  - Content taller than the viewport sets `overflowDirection: "VERTICAL_SCROLLING"`.
  - Bars are the frame's **last N children**, with `numberOfFixedChildren: N`.
- **Glass approximation:**
  - Use a translucent `fills` color with a `cornerRadius` capsule and a `BACKGROUND_BLUR` effect.
  - On a **scrolling** frame, `FigmaApp` blurs the scrolled content under each fixed `BACKGROUND_BLUR` shape every time the scroll offset changes, then composites the bar's fill over it. On non-scrolling frames and in-flow nodes the renderer blurs what is drawn beneath the node.
  - There is no refraction, specular motion, or luminosity adaptation; it is a blur plus a tint.
- **Letterboxing:** the iOS presenter letterboxes the fixed `native_width×native_height` matrix into the device drawable, filling the bars with `bar_color_rgba`.
  - A design sized to the device (402×874 on iPhone 17) has no bars. A 393×852 design on iPhone 17 gets thin ones.
  - There is no dynamic resizing, so iPhone Duo layout adaptation isn't possible today.
- **Verify** with `uv run python main.py figma ios-tour <app> --tour <app>/tour.json --out <dir> --simulator "iPhone 17" --native-project <app>/ios`, or by pushing a `feature/**` branch. The `iOS Simulator Tour` workflow uploads the `ios-tour-<slug>-<run_id>` artifact.

## Screenshot review checklist

Run this against every `NN_<capture>.png` in the `ios-tour` artifact. The screenshots are iPhone 17 at 3x, 1206×2622 px, so divide by 3 to get points.

Layout and safe area
- [ ] No text or control sits under the status bar or Dynamic Island. The top safe area is about 62 pt on iPhone 17 [T-SAFEAREA].
- [ ] No tappable element or label sits in the bottom 34 pt home-indicator zone, except the bar's own background [T-SAFEAREA].
- [ ] Letterbox bars (from a design not sized 402×874) are invisible, or blend in. Check that the `bar_color_rgba` color matches the adjacent content.
- [ ] Content reaches the screen edges behind the bars. There's no hard band where the content stops above the tab bar.
- [ ] Every tappable element is at least 44×44 pt, measured as a 132×132 px hit area in the screenshot [S-BUTTONS].

Liquid Glass and bars
- [ ] The tab bar reads as a floating control layer over content, not as an opaque slab glued to the bottom edge [S-TABBARS].
- [ ] Glass appears only on controls and navigation. There's no glass on cards, lists, or backgrounds, and no glass on glass [S-MATERIALS].
- [ ] Bar symbols and labels are monochrome, or use a single clearly distinct accent for the selected tab. Their color isn't similar to the content behind them [S-COLOR].
- [ ] Corner radii nest concentrically: the radius of anything inside a bar equals the bar radius minus the padding [S-WWDC25-356].
- [ ] Content scrolled under the bar keeps the bar's labels legible. If not, the design needs a scroll edge effect, a more opaque fill, or dimming [S-SCROLLVIEWS].

Navigation
- [ ] The tab bar is visible on every top-level screen, and the selected tab is obvious. There are few tabs, with no More overflow [S-TABBARS].
- [ ] Tab icons are SF Symbol-style, preferably filled, with single-word labels [S-TABBARS].
- [ ] Back and Close use symbols. Titles are under 15 characters and aren't the app name [S-TOOLBARS].

Type, color, icon
- [ ] No text uses a font size below 11 pt; body text is about 17 pt [S-TYPOGRAPHY]. Screenshots can't show font size exactly, so check the `fontSize` values in the design JSON.
- [ ] Text contrast is at least 4.5:1, or 3:1 for text 18 pt and up or bold [S-ACCESSIBILITY].
- [ ] The status bar text is legible against the app's top color in the simulator's current appearance.
- [ ] If the tour captures the Home Screen, the icon has no baked-in rounded corners or shadow, and it reads at small sizes [S-APPICONS].

Report each failed item with the screenshot name, the point coordinates, and the rule's source tag.

## Known deviations in examples/nomic_ios

[`references/nomic-ios-audit.md`](references/nomic-ios-audit.md) audits the current app (as of November 4, 2026) against this checklist. Read it before changing `assemble_capture.py` so fixes land in the builder, not in the generated JSON.
