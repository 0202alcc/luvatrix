# Sources

All pages were fetched on **November 4, 2026**.

HIG pages were read through their Markdown form: append `.md` to the page URL, for example `https://developer.apple.com/design/human-interface-guidelines/materials.md`.

"Apple rev." is the latest entry in the page's own change log at fetch time.

## Tier 1: Apple primary sources

| Tag | URL | Apple rev. | Used for |
|---|---|---|---|
| S-MATERIALS | https://developer.apple.com/design/human-interface-guidelines/materials | Sep 9, 2025 | Liquid Glass layer rules, regular vs clear variants, the 35% dimming layer, standard materials |
| S-TABBARS | https://developer.apple.com/design/human-interface-guidelines/tab-bars | Jun 8, 2026 | Floating glass tab bar, labels, filled symbols, More overflow, minimize behavior, search tab, five or fewer default tabs (iPadOS) |
| S-TOOLBARS | https://developer.apple.com/design/human-interface-guidelines/toolbars | Dec 16, 2025 | Navigation bars (merged into toolbars), titles under 15 characters, `.prominent` primary action, concentric item corners, no more than three groups, large titles |
| S-SCROLLVIEWS | https://developer.apple.com/design/human-interface-guidelines/scroll-views | Jun 8, 2026 | Scroll edge effects: automatic, soft, and hard styles; not decorative; one per view |
| S-SEARCH | https://developer.apple.com/design/human-interface-guidelines/search-fields | Jun 8, 2026 | Search as a tab (standard tab vs button appearance), search in a toolbar, inline search |
| S-LAYOUT | https://developer.apple.com/design/human-interface-guidelines/layout | Sep 9, 2026 | Separating controls from content, extending backgrounds under bars, size classes, safe areas. This revision no longer has device tables. |
| S-LAYOUT-ARCHIVE | http://web.archive.org/web/20260616160055/https://developer.apple.com/tutorials/data/design/human-interface-guidelines/layout.json | Sep 9, 2025 content, archived Jun 16, 2026 | Apple's last published device point table (iPhone 17 family and earlier) and size classes |
| S-HIG-DUO | https://developer.apple.com/design/human-interface-guidelines/designing-for-iphone-duo | Sep 9, 2026 (new page) | iPhone Duo anatomy, poses, reserved regions, vertical controls, arrangement views |
| S-DUO-PREPARE | https://developer.apple.com/iphone-duo/prepare/ | n/a | Behavior per SDK version (iOS 26, 27, and 27.1), no `UIScreen.main`, no orientation or idiom checks, testing tools |
| S-DUO-TECH | https://developer.apple.com/documentation/technologyoverviews/preparing-your-app-for-iphone-duo | n/a | When bars go vertical (sheets, split views, inspectors), item icon and title rules, reserved region APIs |
| S-DUO-SPECS | https://www.apple.com/iphone-duo/specs/ | n/a | Display pixels and density: inner 1878×2670 px at 430 ppi, outer 1398×2034 px at 460 ppi |
| S-NEWSROOM-DUO | https://www.apple.com/newsroom/2026/09/apple-unveils-iphone-duo/ | Sep 9, 2026 | Announcement, iOS 27.1, side controls, vertical Dynamic Island, corner status bar, availability Oct 23, 2026 |
| S-NEWSROOM-WWDC26 | https://www.apple.com/newsroom/2026/06/apple-unveils-next-generation-of-apple-intelligence-siri-ai-and-more/ | Jun 8, 2026 | iOS 27 Liquid Glass personalization slider (ultra-clear to fully tinted), sharper app icons |
| S-DESIGNKITS | https://developer.apple.com/news/?id=e2lxw9l1 | Jun 23, 2026 | iOS 27 Figma and Sketch kits (Liquid Glass updates). The kit page list on S-WHATSNEW shows the Sep 17, 2026 kit and Sep 18, 2026 iPhone Duo bezels. |
| S-WHATSNEW | https://developer.apple.com/design/whats-new/ | Oct 28, 2026 | Index of HIG revisions, Icon Composer 2 and SF Symbols 8 (Jun 8, 2026) |
| S-TYPOGRAPHY | https://developer.apple.com/design/human-interface-guidelines/typography | Dec 16, 2025 | SF Pro and NY, 17 pt default and 11 pt minimum, Dynamic Type tables |
| S-ACCESSIBILITY | https://developer.apple.com/design/human-interface-guidelines/accessibility | Jun 9, 2025 | Control sizes (44×44 pt default, 28×28 pt minimum), 12 pt and 24 pt padding, contrast table, 200% text enlargement |
| S-BUTTONS | https://developer.apple.com/design/human-interface-guidelines/buttons | Dec 16, 2025 | 44×44 pt hit region |
| S-COLOR | https://developer.apple.com/design/human-interface-guidelines/color | Dec 16, 2025 | Liquid Glass color (monochrome bars, tint backgrounds rather than labels, legible resting state) |
| S-DARKMODE | https://developer.apple.com/design/human-interface-guidelines/dark-mode | Aug 6, 2024 | Both appearances, 4.5:1 minimum and 7:1 target contrast, base and elevated backgrounds |
| S-APPICONS | https://developer.apple.com/design/human-interface-guidelines/app-icons | Oct 28, 2026 | Icon Composer vs bitmap formats, 1024×1024 px canvas, six appearances, color spaces |
| S-SHEETS | https://developer.apple.com/design/human-interface-guidelines/sheets | Mar 24, 2026 | Detents, grabber, Cancel and Done placement |
| S-SFSYMBOLS | https://developer.apple.com/design/human-interface-guidelines/sf-symbols | Jul 28, 2025 | Rendering modes |
| S-WWDC25-219 | https://developer.apple.com/videos/play/wwdc2025/219/ ("Meet Liquid Glass") | Jun 2025 | No glass on glass; how Reduce Transparency, Increase Contrast, and Reduce Motion change glass; scroll edge dimming |
| S-WWDC25-356 | https://developer.apple.com/videos/play/wwdc2025/356/ ("Get to know the new design system") | Jun 2025 | Concentricity: fixed, capsule, and concentric shapes; search tab; tinted primary action |
| S-IPHONE17-SPECS | https://www.apple.com/iphone-17/specs/ | n/a | 2622×1206 px at 460 ppi |

## Tier 2: secondary reporting (needs confirmation before you rely on it)

| Tag | URL | Used for |
|---|---|---|
| S-MACRUMORS-IOS27 | https://www.macrumors.com/2026/06/10/how-liquid-glass-is-changing-in-ios-27/ | iOS 27 glass tuning: more diffusion, darkened edge, brighter specular highlights, uniform top toolbar over scrolled content |

## Tier 3: third-party simulator measurements (not Apple-authored)

| Tag | URL | Used for |
|---|---|---|
| T-SAFEAREA | https://safearea.info/iphone-17.md, https://safearea.info/iphone-16.md | Measured on iOS 27.0 with SDK 27.1. iPhone 17 portrait: top 62 pt, bottom 34 pt, corner radius 62 pt. iPhone 16 portrait: top 59 pt, bottom 34 pt, corner radius 55 pt. |
| T-SAFEAREA-DUO | https://safearea.info/iphone-duo.md, https://randyventures.com/blog/iphone-duo-screen-sizes-and-layout-notes-for-developers/ | Measured with the Xcode 27.1 simulator. Outer display 466×678 pt; inner display 951×669 pt (landscape) or 669×951 pt (portrait); 84 pt trailing inset in closed portrait and open landscape; 34 pt bottom inset. |

**Conflict to note.** T-SAFEAREA-DUO reports the inner display as 2853×2007 px at 460 ppi. Apple's spec page (S-DUO-SPECS) says 1878×2670 px at 430 ppi. Apple has published no point dimensions or scale factor for either iPhone Duo display. So:

- Treat every iPhone Duo point value as unverified.
- Measure from Apple's iOS 27 Figma kit (iPhone Duo frames), or from the Xcode 27.1 iPhone Duo simulator, before you commit to a design frame.
