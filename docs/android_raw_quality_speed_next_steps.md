# Android RAW Quality/Speed Next Steps Implementation Plan

This plan continues from `docs/android_computational_camera_lab_implementation.md` and the current RAW path:

```text
tap raw burst
  -> RAW_SENSOR burst
  -> DNG + raw16 + metadata
  -> native selected-frame RAW processor
  -> 1600x1200 RGBA/JPEG
  -> MediaStore gallery save
```

The current fast path is intentionally simple. It gets a RAW-derived JPEG into the phone gallery quickly, but it trades quality for speed in these places:

```text
4000x3000 RAW -> 1600x1200 Bayer-area reduction
single selected RAW frame
bilinear demosaic
basic color matrix/gains
simple global tone map
nearest-neighbor preview scale
```

The next milestone is not "maximum quality at any cost." It is a controllable camera lab pipeline where the user can choose speed, balanced quality, or full quality and where every choice is measurable on-device.

## Packet 25: Verify Threaded RAW Hot Path

Purpose: finish acceptance for the already-implemented native row parallelism.

### Step 25.1: Red/Guard Tests

In `tests/test_android_packaging.py`, assert the native source contains:

```text
parallel_for_rows
std::thread::hardware_concurrency
downsample_raw_bayer_area
render_reduced_bayer_to_rgba_fused
raw_load_mode
native_timing_ms
```

Run:

```bash
uv run pytest tests/test_android_packaging.py
```

### Step 25.2: On-Device Timing Gate

With the phone connected:

```bash
adb devices
adb logcat -c
uv run python main.py run-app examples/camera --render android-device --native-project android
```

On the phone:

```text
tap raw burst
wait for processing done
```

Inspect:

```bash
adb shell run-as com.luvatrix.app find files/computational_camera/processed -maxdepth 3 -type f
adb shell run-as com.luvatrix.app cat files/computational_camera/processed/<raw_burst_id>/processing_manifest.json
```

Acceptance:

- `raw_load_mode` is `mmap` or a structured fallback of `read`.
- `native_timing_ms.downsample` and `native_timing_ms.render` are present.
- Processed JPEG appears in `Pictures/Luvatrix Camera`.
- Final JPEG decodes locally.
- No `AndroidRuntime`, native crash, or Python exception appears in filtered logcat.

### Step 25.3: Decide Whether Threading Stays

Keep native row parallelism only if it improves real-device total time or does not regress it meaningfully.

Acceptance rule:

```text
keep if native total improves by >= 10%
keep if native total is flat but render/downsample improves and no thermal/crash risk appears
revert/refine if native total regresses by > 10%
```

## Packet 26: Add Explicit RAW Quality Modes

Purpose: stop hiding quality/speed tradeoffs inside constants.

### Step 26.1: Red Tests

Add source/HUD tests for:

```text
RawProcessingQuality
fast_1600
balanced_2400
full_res
raw_quality_mode
render_max_edge
```

Run:

```bash
uv run pytest tests/test_android_packaging.py tests/test_camera_example.py
```

### Step 26.2: Native Quality Mode Contract

Add a quality mode parameter to the native RAW path:

```kotlin
external fun processRawBurst(
    manifestPath: String,
    outputRgbaPath: String,
    previewRgbaPath: String,
    previewMaxEdge: Int,
    qualityMode: String,
): String
```

Native mode mapping:

```text
fast_1600:
  render_max_edge = 1600
  selected frame only
  current Bayer-area downsample

balanced_2400:
  render_max_edge = 2400
  selected frame only
  higher output detail, slower render/JPEG

full_res:
  render_max_edge = max(raw_width, raw_height)
  selected frame only
  no pre-demosaic downsample
```

Telemetry:

```json
{
  "raw_quality_mode": "fast_1600",
  "render_max_edge": 1600,
  "raw_width": 4000,
  "raw_height": 3000,
  "width": 1600,
  "height": 1200
}
```

### Step 26.3: Kotlin/HUD Control

Add a small Android bridge setting:

```kotlin
fun setRawQualityMode(mode: String): String
```

Add Python wrapper:

```python
def set_raw_quality_mode(mode: str) -> str:
    ...
```

HUD control:

```text
raw quality: fast | balanced | full
```

Do not expose `full` as the default. Default remains `fast_1600`.

### Step 26.4: On-Device Acceptance

For each mode, capture one RAW burst and verify:

```text
fast_1600 -> 1600x1200 JPEG
balanced_2400 -> approx 2400x1800 JPEG
full_res -> approx 4000x3000 JPEG
```

Each mode must publish to Gallery and report timing. If `full_res` exceeds memory or time limits, return a structured HUD error instead of crashing.

## Packet 27: Improve Demosaic Quality

Purpose: improve detail/color quality at the same output size before chasing full-res rendering.

### Step 27.1: Red Tests

Add source-contract tests for:

```text
raw_demosaic_mode
bilinear
malvar
edge_aware_green
```

Add HUD formatting tests for:

```text
demosaic: bilinear
demosaic: malvar
```

### Step 27.2: Implement Demosaic Modes

Keep current mode:

```text
bilinear_fast
```

Add a second mode:

```text
malvar_approx
```

Implementation scope:

- Apply a small convolution-style correction around each Bayer pixel.
- Start with green reconstruction improvements first.
- Keep borders on the existing bilinear path.
- Use float math, row-parallelized where useful.
- Telemetry must report mode and timing separately.

Do not remove bilinear. It remains the fallback and speed baseline.

### Step 27.3: Quality Comparison Artifact

For one RAW burst, process the same selected frame twice:

```text
IMG_<burst_id>_bilinear.jpg
IMG_<burst_id>_malvar.jpg
```

Store comparison metadata:

```json
{
  "burst_id": "...",
  "reference_frame": 0,
  "mode_a": "bilinear_fast",
  "mode_b": "malvar_approx",
  "timing_a_ms": 900.0,
  "timing_b_ms": 1300.0
}
```

Acceptance:

- Both JPEGs decode.
- `malvar_approx` does not produce strong green/purple artifacts.
- Timing delta is visible in telemetry.

## Packet 28: Replace Nearest Preview Scaling

Purpose: improve preview JPEG quality without touching final output quality.

### Step 28.1: Red Tests

Assert native source contains:

```text
downscale_rgba_bilinear
preview_scale_mode
```

### Step 28.2: Implement Bilinear Preview Downscale

Replace preview-only nearest scaling with bilinear scaling:

```text
native_output.rgba remains unchanged
native_preview.rgba uses bilinear downscale
```

Telemetry:

```json
{
  "preview_scale_mode": "bilinear"
}
```

Acceptance:

- Main JPEG dimensions and pixels are unaffected.
- Preview JPEG looks less blocky.
- Preview generation remains below roughly `250ms` on the current phone.

## Packet 29: Add Same-Exposure RAW Average

Purpose: first real computational-photo quality gain.

### Step 29.1: Red Tests

Add tests for:

```text
raw_average_no_alignment
merge_count
exposure_consistent
raw_merge_mode
```

### Step 29.2: Capture Contract

Before RAW burst capture:

- Lock AE where supported.
- Lock AWB where supported.
- Prefer stable ISO/shutter across the burst.
- Record per-frame ISO, exposure time, frame duration, timestamp, AE lock, and AWB lock.

Manifest fields:

```json
{
  "exposure_strategy": "locked_same_exposure",
  "ae_locked": true,
  "awb_locked": true,
  "raw_merge_candidate": true
}
```

### Step 29.3: Native Average Mode

Add:

```text
raw_average_no_alignment
```

Algorithm:

```text
load N processable raw16 frames
reject dimension/CFA mismatch
reject exposure mismatch unless normalized exposure support is enabled
normalize black/white level
average Bayer values pixel by pixel
demosaic averaged Bayer
render using selected quality mode
```

Telemetry:

```json
{
  "mode": "raw_average_no_alignment",
  "used_frames": 5,
  "rejected_frames": 0,
  "merge_count": 5,
  "raw_merge_mode": "average_no_alignment"
}
```

Acceptance:

- Static scenes show lower noise than single-frame RAW.
- Moving scenes may ghost; this is expected and must be documented in HUD/debug notes.

## Packet 30: Add Global Alignment Prototype

Purpose: make RAW averaging usable handheld.

### Step 30.1: Red Tests

Assert:

```text
raw_average_global_aligned
alignment_offsets
alignment_failures
green_alignment_proxy
```

### Step 30.2: Alignment Proxy

For each RAW frame:

```text
green channel proxy
downsample to small luma plane
normalize exposure
```

### Step 30.3: Translation Search

Implement:

```text
reference frame = sharpest frame
search +/- 24 px at proxy scale
score with SAD or MSE
choose best dx/dy
reject frame if score too poor
```

Telemetry:

```json
{
  "alignment_offsets": [
    {"index": 0, "dx": 0, "dy": 0, "score": 0.0}
  ],
  "alignment_failures": 1
}
```

Acceptance:

- Handheld static scenes improve over no-alignment average.
- Strong subject motion may still ghost.
- Bad alignments are rejected, not silently merged.

## Packet 31: Add Style Layer After Neutral RAW

Purpose: start brand-style rendering without contaminating capture/reconstruction.

### Step 31.1: Red Tests

Add tests for:

```text
RenderStyleProfile
Neutral
Google
Apple
Samsung
Xiaomi
style_profile
```

### Step 31.2: Style Contract

Style applies after neutral RAW reconstruction:

```text
neutral linear/render RGB
  -> tone curve
  -> saturation/color bias
  -> local contrast placeholder
  -> sharpening/noise texture placeholder
  -> JPEG
```

Initial presets:

```text
Neutral:
  restrained tone map, saturation 1.0

Google:
  stronger HDR feel, restrained saturation

Apple:
  smoother highlight rolloff, warm skin bias placeholder

Samsung:
  punchier saturation and local contrast

Xiaomi:
  vibrant/high contrast preset
```

Do not add semantic masks yet. Style v1 is global only.

### Step 31.3: Output Naming

When style is not neutral:

```text
IMG_<burst_id>_<style>.jpg
```

Telemetry:

```json
{
  "style_profile": "Samsung",
  "render_layer": "global_style_v1"
}
```

Acceptance:

- Neutral remains the default.
- Style changes are visible but not destructive.
- Capture and RAW merge telemetry do not change when only style changes.

## Recommended Build Order

Implement in this order:

```text
1. Packet 25: verify threaded timing on-device
2. Packet 26: explicit RAW quality modes
3. Packet 28: bilinear preview scale
4. Packet 27: improved demosaic mode
5. Packet 29: same-exposure RAW average
6. Packet 30: global alignment
7. Packet 31: style layer
```

Reasoning:

- First confirm the current speed work is real.
- Then make quality/speed a user-visible choice.
- Improve cheap quality issues before expensive multi-frame work.
- Only then add true computational merge.
- Styles come after neutral reconstruction is stable.

## Standard Test Command

Run after each packet:

```bash
uv run pytest tests/test_android_packaging.py tests/test_camera_example.py tests/test_camera_burst_processing.py tests/test_camera_processing_contract.py
```

For Android/native changes, also run:

```bash
uv run python main.py run-app examples/camera --render android-device --native-project android
```

## Standard On-Device Acceptance Loop

```bash
adb devices
adb logcat -c
uv run python main.py run-app examples/camera --render android-device --native-project android
```

On phone:

```text
tap raw burst
wait for processing done
```

Inspect:

```bash
adb shell run-as com.luvatrix.app find files/computational_camera -maxdepth 5 -type f
adb shell run-as com.luvatrix.app cat files/computational_camera/processed/<raw_burst_id>/processing_manifest.json
adb shell content query --uri content://media/external/images/media --projection _id:_display_name:relative_path:date_added
adb logcat -d -t 500 AndroidRuntime:E Python:E Luvatrix:E com.luvatrix.app:E '*:S'
```

Pull and decode:

```bash
adb exec-out run-as com.luvatrix.app cat files/computational_camera/processed/<raw_burst_id>/IMG_<raw_burst_id>.jpg > /private/tmp/luvatrix_raw_check.jpg
uv run python -c "from PIL import Image; im=Image.open('/private/tmp/luvatrix_raw_check.jpg'); im.verify(); print('ok', im.format, im.size)"
```

## Expected Outcome

After Packets 25-28:

```text
RAW output remains fast, has explicit quality modes, and previews look better.
```

After Packets 29-30:

```text
RAW bursts become genuinely computational: static/handheld scenes can use multiple frames for lower noise.
```

After Packet 31:

```text
The app can produce neutral RAW results plus early Google/Apple/Samsung/Xiaomi-style renders without mixing style into capture or reconstruction.
```

## Big Rule

Keep this separation intact:

```text
Capture:
  Camera2 sessions, RAW/YUV frames, metadata

Reconstruction:
  sharpness, alignment, averaging, demosaic, neutral image

Rendering:
  tone, color, style, JPEG/HEIF/gallery export
```

Any patch that makes style decisions during capture or preview decisions during final RAW reconstruction should be rejected.
