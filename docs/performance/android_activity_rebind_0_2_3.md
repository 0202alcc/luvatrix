# Android Activity Rebind Performance: Luvatrix 0.2.3

Luvatrix 0.2.3 introduced process-scoped Android runtime reuse, retained-frame replay, first-presentation background-work gating, and direct Chaquopy bytecode loading. This record compares the same schedule app feature set on Luvatrix 0.2.2 and 0.2.3 using one Realme 12 5G. The 0.2.3 candidate explicitly enabled `startup_ready=ctx.has_presented_frame` for its existing background prewarm scheduler.

## Result

| Measurement | 0.2.2 median | 0.2.3 median | Improvement |
| --- | ---: | ---: | ---: |
| Cold launch | 5.480 s | 4.435 s | 19.08% |
| Activity recreation | 5.454 s | 1.011 s | 81.46% |

The Android bridge logged the Python runtime reattachment in 34 ms. Each 0.2.3 recreation was visible on the first screenshot sample, so the approximately one-second visual result is substantially constrained by ADB screenshot latency.

## Method

- Device: Realme 12 5G, model RMX3999, 1080x2400 at 120 Hz.
- Android `always_finish_activities` was enabled to deterministically destroy `MainActivity` when backgrounded while retaining the process.
- Each version received three cold-launch and three Activity-recreation trials.
- Cold trials used `am force-stop`, `am start`, then repeated `screencap` sampling.
- Recreation trials rendered the app, sent `KEYCODE_HOME`, waited one second, used `am start --activity-reorder-to-front`, then repeated the same sampling.
- A frame counted as visible when it contained both the app's cream background signature and dark-red hour-line signature. This avoids counting Android's bootstrap surface as an app frame.
- Both versions used the same calendar feature set, native dimensions, detection thresholds, ADB path, and connected device. The candidate included the documented first-presentation scheduler integration described above.

The machine-readable raw trials and summary are in [`data/android_activity_rebind_0_2_3.json`](data/android_activity_rebind_0_2_3.json). `tests/test_android_startup_evidence.py` recomputes the medians and percentage improvements from those raw values.

## Interpretation

The 19% cold-launch improvement is consistent with avoiding source reconstruction and preventing bulk preparation from competing with first presentation. The larger recreation improvement comes from retaining one Python runtime per process and rebinding the replacement Android view instead of starting a second app runtime.

This is a single-device application benchmark, not a universal platform claim. Future releases should append comparable records rather than replacing this evidence.
