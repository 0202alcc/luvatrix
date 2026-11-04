# Devices, safe areas, and iPhone Duo

Fetched November 4, 2026. [`sources.md`](sources.md) has the source tags and tiers.

## Current iPhone point sizes (Apple-authored)

Apple's HIG Layout page published this table every September from 2022 to 2025. Its September 9, 2026 revision removed it. The rows below come from Apple's own table in an archived copy of the page [S-LAYOUT-ARCHIVE].

| Model | Portrait | Pixels | Landscape size classes |
|---|---|---|---|
| iPhone 17 Pro Max | 440×956 pt | 1320×2868 @3x | regular width, compact height |
| iPhone Air | 420×912 pt | 1260×2736 @3x | regular width, compact height |
| iPhone 17 Pro | 402×874 pt | 1206×2622 @3x | compact width, compact height |
| iPhone 17 | 402×874 pt | 1206×2622 @3x | compact width, compact height |
| iPhone 16 Pro | 402×874 pt | 1206×2622 @3x | compact width, compact height |
| iPhone 16 | 393×852 pt | 1179×2556 @3x | compact width, compact height |
| iPhone 16e | 390×844 pt | 1170×2532 @3x | compact width, compact height |
| iPhone 15 / 15 Pro / 14 Pro | 393×852 pt | 1179×2556 @3x | compact width, compact height |

Every iPhone listed is compact width and regular height in portrait [S-LAYOUT-ARCHIVE]. Apple's current iPhone 17 spec page confirms 2622×1206 px at 460 ppi [S-IPHONE17-SPECS].

**iPhone 18 models.** Apple announced them in September 2026, and the design resources got iPhone 18 bezels on September 18, 2026 [S-WHATSNEW]. No Apple-authored point table for them was found. Don't assume their sizes; measure them from the iOS 27 Figma kit or the simulator.

## Safe areas, Dynamic Island, home indicator

Apple defines the safe area conceptually but doesn't publish per-device inset values [S-LAYOUT]. These are third-party simulator measurements [T-SAFEAREA], taken on iOS 27.0 with SDK 27.1:

| Device (portrait) | Top inset | Bottom inset | Screen corner radius | Dynamic Island (width × height, top offset) |
|---|---|---|---|---|
| iPhone 17 | 62 pt | 34 pt | 62 pt | 125.33×36.67 pt, 14 pt from top |
| iPhone 16 | 59 pt | 34 pt | 55 pt | 125×36.67 pt, 11.33 pt from top |

iPhone 17 in landscape [T-SAFEAREA]: 62 pt left and right insets, 0 pt top, 20 pt bottom.

How to use these:

- Put text and controls inside the safe area. Let backgrounds and scrolling content run to every edge, underneath the bars [S-LAYOUT].
- The bottom inset belongs to the home indicator. Bar *backgrounds* extend into it; bar *items* sit above it.

## iPhone Duo

**What it is.** iPhone Duo is Apple's first foldable iPhone. It was announced on September 9, 2026, pre-orders opened October 16, and it went on sale October 23, 2026. It ships with iOS 27.1 [S-NEWSROOM-DUO].

**Displays** [S-DUO-SPECS]:

| | Inner | Outer |
|---|---|---|
| Diagonal | 7.6 in (7.58 in as a rectangle) | 5.4 in (5.36 in as a rectangle) |
| Pixels | 1878×2670 | 1398×2034 |
| Density | 430 ppi | 460 ppi |

- Both displays have the same aspect ratio, so content scales proportionally between them [S-NEWSROOM-DUO].
- Both have a Dynamic Island, ProMotion up to 120 Hz, and Always-On [S-DUO-SPECS].

**Points: not published by Apple.** The HIG, the "Prepare" page, and the technology overview give no point dimensions or scale factor. Third-party measurements [T-SAFEAREA-DUO], from the Xcode 27.1 simulator:

| | Outer, closed, portrait | Inner, fully open, landscape | Inner, fully open, portrait |
|---|---|---|---|
| Window | 466×678 pt | 951×669 pt | 669×951 pt |
| Insets (top / bottom / left / right) | 0 / 34 / 0 / 84 | 0 / 34 / 0 / 84 | 82 / 34 / 0 / 0 |
| Size class (width / height) | compact / regular | regular / regular | regular / regular |

These are **unverified**. The same source reports the inner display as 2853×2007 px at 460 ppi, which contradicts Apple's 1878×2670 px at 430 ppi. Confirm against Apple's iOS 27 Figma kit (iPhone Duo frames) or your own simulator run before you design to them.

**Behavior** (all from Apple) [S-HIG-DUO], [S-DUO-PREPARE], [S-DUO-TECH], [S-NEWSROOM-DUO]:

- **Vertical controls.**
  - On the outer display, and on the inner display in landscape, the system moves these to the trailing side: the Dynamic Island, the status bar (a circular cluster in the corner), the toolbar with navigation buttons, and the tab bar.
  - The inner display in portrait keeps horizontal bars.
  - In Split View, each app puts its controls on its outer edge.
  - Vertical controls don't flip for right-to-left languages.
- **Bar item order on the side.**
  - At the top: navigation (Back or Close), then the prominent action (Done).
  - Overflow works from bottom to top. Set priorities with `ToolbarItemVisibilityPriority` (SwiftUI) or `UIBarButtonItemVisibilityPriority` (UIKit).
  - Give every item both a symbol and a title. Items with only a title, or with a custom view, aren't shown vertically.
- **When space is short:**
  - Navigation-focused views push toolbar items into the overflow menu.
  - Task-focused views minimize the tab bar instead.
- **Reserved regions:**
  - The outer camera is always reserved.
  - The inner camera is reserved only while active.
  - The fold is reserved only when the device is partially open.
  - Use `ReservedRegion` (SwiftUI or UIKit). Arrangement views come in split and overlay styles.
  - Prefer an even number of grid columns. Avoid big layout jumps as the device folds.
- **Size classes:**
  - The outer display gets your iPhone (compact) layout, and the inner display your iPad-like (regular) layout.
  - Keep the same functionality and state on both displays.
- **SDK behavior:**
  - **iOS 26 SDK:** the app is centered with empty space on the inner display, and sits left of the status bar and camera on the outer display.
  - **iOS 27 SDK:** the app fills most of the display, avoiding the trailing status bar.
  - **iOS 27.1 SDK:** the app uses the full display, with vertical bars.
- **Don't base layout on device facts.** Never use `UIScreen.main`, orientation, idiom checks, or hard-coded sizes.
- **Test with Apple's tools:** Device Hub, the iPhone Duo simulator in Xcode 27.1, or iPhone Mirroring on macOS 27.

### iPhone Duo and luvatrix today

A luvatrix iOS app sets `UIRequiresFullScreen`, supports portrait only, and draws its own bars into a fixed `native_width×native_height` matrix that is letterboxed into the drawable. So on iPhone Duo:

- **No vertical bars.** It won't get system vertical bars. Those come only from standard UIKit or SwiftUI bars.
- **No resizing between displays.** The matrix size comes from `app.toml`, so the app can't follow the inner and outer display sizes.
- **Wasted space.** It renders with large letterbox or pillarbox margins, especially on the inner display, whose shape differs most from 393×852.

Real iPhone Duo support needs runtime work:

- Read the window size at runtime and re-layout when it changes.
- Supply Figma frames for compact and regular width.
- Optionally, add a side-bar variant of the tab bar.

Treat that as a separate feature. Don't fake it with device checks.
