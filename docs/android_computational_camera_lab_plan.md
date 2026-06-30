# Android Computational Camera Lab Plan

This plan evolves the Android camera example from a custom preview and capture app into a computational camera lab. The central architectural shift is to keep the live preview fast and predictable while building a separate still-photo pipeline for final image quality.

```text
Live path:
Camera2 -> PRIVATE HardwareBuffer -> Vulkan preview -> Python HUD

Quality still path:
Camera2 burst/RAW/YUV -> native processing queue -> alignment/fusion/rendering -> styled output
```

The live preview path should never become responsible for final image quality. Preview is for framing, controls, telemetry, and confidence. Still capture is for quality, burst depth, metadata, reconstruction, and style rendering.

## Architectural Rule

Keep three layers cleanly separated:

```text
1. Capture
   Camera2, sessions, ImageReaders, frame storage, capture metadata

2. Reconstruction
   frame scoring, alignment, merge, denoise, demosaic/YUV conversion, neutral HDR image

3. Rendering
   tone mapping, color style, local contrast, semantic adjustments, JPEG/HEIF output
```

This separation is what keeps the project from turning into a tangled camera-port clone. Camera2 quirks stay in capture. Image math stays in reconstruction. Brand looks and creative controls stay in rendering.

## Current Baseline

The current Android camera app is already strong for layer 1 and live diagnostics:

- `CameraBridge.kt` manages Camera2 preview, RAW still capture, session fallback attempts, camera inventory, and telemetry.
- `ImageFormat.PRIVATE` plus `HardwareBuffer` feeds native Vulkan preview when supported.
- YUV preview remains as a fallback path.
- `examples/camera/app_main.py` provides a Python HUD/control surface for preview quality, target mode, sharpness, white balance, pipeline mode, refresh hint, RAW capture, and manual exposure controls.
- Native telemetry exposes GPU import/draw timing, cache behavior, frame delivery, and fallback status.

The next major milestone is:

```text
Capture a 10-frame RAW/YUV burst,
save every frame plus metadata,
process it offline into one visibly better image,
then display the result back in the app.
```

That is the point where the project becomes a real computational camera.

## Phase 1: Stabilize The Camera Core

Goal: make the camera subsystem predictable and stop making the Python HUD infer capabilities from partial runtime state.

Add a first-class Kotlin capability profile:

```kotlin
data class CameraCapabilityProfile(
    val cameraId: String,
    val hardwareLevel: String,
    val supportsRaw: Boolean,
    val supportsYuvReprocess: Boolean,
    val supportsPrivatePreview: Boolean,
    val rawSizes: List<Size>,
    val yuvSizes: List<Size>,
    val privateSizes: List<Size>,
    val maxBurstTargets: Int,
    val streamCombinations: List<StreamCombo>,
    val sensorInfo: SensorInfo,
    val lensInfo: LensInfo,
    val colorInfo: ColorInfo
)
```

Suggested related data classes:

```kotlin
data class StreamCombo(
    val name: String,
    val outputs: List<StreamOutput>,
    val supportsRaw: Boolean,
    val supportsPrivatePreview: Boolean,
    val supportsYuvCache: Boolean,
    val expectedUse: String,
)

data class StreamOutput(
    val format: String,
    val width: Int,
    val height: Int,
    val maxFps: Double? = null,
)
```

Expose stable telemetry keys:

```json
{
  "camera.capabilities.raw": true,
  "camera.capabilities.private_preview": true,
  "camera.capabilities.max_burst": 8,
  "camera.capabilities.hardware_level": "FULL"
}
```

Also expose the full profile under a structured field such as:

```json
{
  "capability_profile": {
    "camera_id": "0",
    "hardware_level": "FULL",
    "supports_raw": true,
    "supports_private_preview": true,
    "raw_sizes": [{"width": 4080, "height": 3060}],
    "yuv_sizes": [{"width": 1920, "height": 1080}],
    "private_sizes": [{"width": 2560, "height": 1440}]
  }
}
```

Acceptance criteria:

- Every camera ID has a profile before preview starts.
- Python HUD reads capability booleans from profile telemetry, not from heuristics.
- Preview session selection logs the exact stream combo selected.
- Failed combo attempts reference profile combo IDs, sizes, and reason.

## Phase 2: Separate Preview Mode From Capture Mode

Goal: make session responsibilities explicit so preview and still quality stop competing.

Introduce separate session/controller concepts:

```text
PreviewSession
StillCaptureSession
BurstCaptureSession
RawCaptureSession
CalibrationSession
```

Preview session optimizes for:

```text
low latency
stable FPS
low memory pressure
gesture-safe UI
PRIVATE HardwareBuffer if possible
YUV fallback if necessary
fast restart after camera switch
```

Still and burst sessions optimize for:

```text
high quality
burst depth
metadata completeness
RAW/YUV availability
exposure control
frame consistency
repeatable output artifacts
```

Implementation direction:

- Keep `CameraBridge.startPreview` focused on the live path.
- Add a capture controller that can temporarily pause, supplement, or reconfigure preview only when a still or burst requires it.
- Represent capture state separately in telemetry: `preview.status`, `capture.status`, `burst.status`, and `processing.status`.
- Avoid letting live preview tuning control final still reconstruction parameters.

Acceptance criteria:

- Toggling preview quality does not silently change still capture quality.
- Manual capture controls are reported separately from preview pipeline mode.
- RAW capture errors distinguish session-not-ready, RAW-not-supported, and RAW-not-in-active-session.

## Phase 3: Add Burst Capture As A First-Class Feature

Goal: turn a single RAW capture into a reusable burst artifact.

Create:

```kotlin
class BurstCaptureController
```

Responsibilities:

```text
lock AE/AWB/AF when needed
choose exposure/ISO
capture N frames
collect per-frame metadata
store frames in native-accessible buffers or files
emit burst package ID
resume preview cleanly
```

Artifact layout:

```text
BurstPackage/
  frame_000.yuv or frame_000.dng
  frame_001.yuv or frame_001.dng
  ...
  metadata_000.json
  metadata_001.json
  burst_manifest.json
```

Manifest example:

```json
{
  "burst_id": "2026-06-04T15-24-02.123Z",
  "camera_id": "0",
  "format": "RAW_SENSOR",
  "frame_count": 12,
  "exposure_strategy": "locked_short_exposure",
  "iso": 400,
  "exposure_time_ns": 8333333,
  "awb_locked": true,
  "ae_locked": true,
  "af_locked": true,
  "gyro_available": true
}
```

Suggested burst modes:

- `single_reference`: capture N frames with locked exposure for denoise and sharpness.
- `bracket_hdr`: capture short, medium, and long exposures for HDR.
- `low_light`: capture more frames at shorter exposure to reduce hand-motion blur.
- `raw_debug`: capture RAW plus dense metadata for offline analysis.
- `yuv_fast`: capture YUV burst for quick prototype processing.

Acceptance criteria:

- Manual button captures a configurable N-frame burst.
- Every frame has metadata.
- Burst package is discoverable from telemetry and logs.
- Preview resumes after success, failure, and timeout.
- Burst package can be pulled from device and processed offline.

## Phase 4: Build The Neutral Reconstruction Pipeline

Goal: create a truth-image pipeline before style rendering.

Pipeline:

```text
BurstPackage
  -> frame scoring
  -> reference frame selection
  -> alignment
  -> motion mask
  -> merge/fusion
  -> denoise
  -> demosaic / YUV conversion
  -> neutral linear image
```

Versioned implementation path:

```text
v0: choose sharpest frame
v1: average aligned frames
v2: tile-based alignment
v3: motion-aware merge
v4: RAW linear merge
v5: GPU/Vulkan compute acceleration
```

Do not start with the final version. Start by making the artifact format and debugging viewer excellent.

Recommended early telemetry:

```json
{
  "processing.stage": "alignment",
  "processing.reference_frame": 3,
  "processing.alignment_score": 0.82,
  "processing.used_frames": 8,
  "processing.rejected_frames": 2,
  "processing.motion_risk": 0.31
}
```

Acceptance criteria:

- Offline script can load a burst package and produce an output image.
- v0 sharpest-frame output works before merge work starts.
- v1 aligned average shows visible denoise improvement on static scenes.
- Debug output includes per-frame score, chosen reference, and reject reasons.

## Phase 5: Add A Processing Backend Interface

Goal: let processing evolve from Python prototype to native CPU to Vulkan compute without changing capture or UI contracts.

Common interface:

```cpp
struct ProcessingRequest {
    std::string burst_id;
    ProcessingMode mode;
    RenderStyle style;
    QualityLevel quality;
};

struct ProcessingResult {
    std::string output_path;
    std::string preview_path;
    ProcessingTelemetry telemetry;
};
```

Backends:

```text
Native CPU backend
Native Vulkan compute backend
Python prototype backend
External desktop/server backend
```

Initial routing:

- Python prototype backend reads burst packages from disk and writes debug outputs.
- Native CPU backend handles simple merge/denoise once the algorithm stabilizes.
- Vulkan compute backend handles high-throughput alignment, merge, tone map, and denoise later.
- External backend is useful for desktop experiments and expensive model-based prototypes.

Acceptance criteria:

- Capture layer only submits `ProcessingRequest`.
- HUD reads `ProcessingResult` and processing telemetry without caring which backend ran.
- Backends write the same output manifest shape.

## Phase 6: Add Brand-Style Rendering Modes

Goal: keep the reconstruction neutral, then render multiple looks from the same neutral image.

Style modes:

```text
Neutral
Google
Apple
Samsung
Xiaomi Authentic
Xiaomi Vibrant
Custom
```

Rendering pipeline:

```text
neutral HDR image
  -> style profile
  -> tone map
  -> color transform / LUT
  -> local contrast
  -> skin/sky/foliage handling
  -> sharpening/noise texture
  -> JPEG/HEIF output
```

Style profile example:

```json
{
  "name": "Samsung Pop",
  "shadow_lift": 0.45,
  "highlight_rolloff": 0.65,
  "global_saturation": 1.22,
  "local_contrast": 1.2,
  "sharpening": 1.25,
  "skin_smoothing": 0.2,
  "sky_saturation": 1.3,
  "foliage_saturation": 1.2,
  "white_balance_bias": "slightly_warm"
}
```

Important constraint: these profiles should mostly affect the rendering layer, not the burst fusion layer. If a style needs different exposure weighting, make that explicit as a reconstruction option rather than hiding it in a look preset.

Acceptance criteria:

- One neutral reconstruction can render multiple style outputs.
- Style changes do not require recapturing the burst.
- Output manifest records neutral source, style profile name, style parameters, and render backend.

## Phase 7: Add Semantic-Aware Rendering

Goal: make styles scene-aware without corrupting the capture/reconstruction layers.

Target masks:

```text
face
skin
sky
foliage
food
text
night lights
shadow regions
highlight regions
```

Style behavior examples:

```text
Samsung:
  boost sky and foliage
  brighten faces
  stronger local contrast

Apple:
  protect skin warmth
  smoother face tone
  softer highlight rolloff

Google:
  neutral skin
  strong HDR
  restrained saturation
```

Version path:

- v1: use simple heuristics such as luminance, chroma, hue ranges, face rectangles if available, and highlight/shadow masks.
- v2: add a lightweight segmentation model.
- v3: cache semantic masks in the burst/output artifact for debugging and style comparison.

Acceptance criteria:

- Semantic masks are inspectable as grayscale/debug overlays.
- Style output records which masks were used.
- Rendering can fall back to non-semantic style if segmentation is unavailable.

## Phase 8: Add Calibration Mode

Goal: make the app adapt to the actual phone instead of behaving like a generic port.

Capture workflow:

```text
dark frames
flat-field frames
color chart if available
daylight scene
indoor tungsten scene
night scene
skin tone scene
```

Generated profiles:

```text
black level correction
noise profile
lens shading profile
color correction profile
style baseline
```

Storage:

```text
profiles/RMX3999/main_camera/profile.json
```

Profile sketch:

```json
{
  "device_model": "RMX3999",
  "camera_id": "0",
  "created_at": "2026-06-04T15:24:02Z",
  "black_level": [64, 64, 64, 64],
  "noise_model": {
    "iso_100": {"shot": 0.001, "read": 0.0002},
    "iso_800": {"shot": 0.006, "read": 0.0014}
  },
  "lens_shading_profile": "lens_shading_main_camera_v1.bin",
  "color_matrix": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
}
```

Acceptance criteria:

- Calibration captures are stored as structured packages.
- Processing backend can load device/camera profile.
- HUD shows whether the active camera has a calibration profile.

## Phase 9: Improve The HUD Into A Camera Lab UI

Goal: make the Python HUD a debugging instrument, not just a status overlay.

Suggested panels:

```text
Capture:
  RAW/YUV/PRIVATE status
  ISO
  exposure
  focus distance
  burst depth
  AE/AWB/AF lock

Processing:
  queue depth
  current stage
  alignment score
  dropped frames
  merge count
  render style

Quality:
  sharpness estimate
  motion risk
  noise estimate
  highlight clipping
  shadow clipping
```

Interaction model:

- Collapsed HUD: framing-safe essentials.
- Compact HUD: capture controls and current mode.
- Debug HUD: capability profile, stream combo, burst status, processing telemetry.
- Gallery/result panel: latest processed output, preview image, output path, and render style.

Acceptance criteria:

- HUD can show the active capture profile and active processing job.
- Capture button reports burst ID immediately.
- Processing queue updates without blocking preview.
- Latest output can be opened/displayed in-app.

## Phase 10: Recommended Implementation Order

Build in this order:

```text
1. CameraCapabilityProfile telemetry
2. BurstPackage artifact format
3. Manual burst capture button
4. Save RAW/YUV burst + metadata
5. Offline Python HDR prototype
6. Return processed JPEG to app gallery
7. Native CPU merge path
8. Style profile system
9. Google/Samsung/Apple/Xiaomi presets
10. Vulkan compute acceleration
11. Semantic masks
12. On-device full-quality pipeline
```

The first checkpoint should be intentionally modest:

```text
Manual 10-frame YUV burst
  -> saved package
  -> offline sharpest-frame output
  -> output path displayed in HUD
```

Then graduate to RAW, alignment, merge, and style.

## Near-Term Work Items

1. Add `CameraCapabilityProfile` and expose stable telemetry.
2. Add `BurstPackageWriter` for file layout, manifest writing, and metadata naming.
3. Add `BurstCaptureController` with a manual YUV burst mode first.
4. Add Python HUD fields for burst depth, capture state, latest burst ID, and latest output path.
5. Add `tools/camera/process_burst.py` for offline v0/v1 reconstruction.
6. Add a small gallery/result surface in the app for processed output previews.

## Risks And Guardrails

- Do not overload preview sessions with final-quality processing.
- Do not encode brand style choices into capture tuning unless explicitly part of the capture strategy.
- Do not make Vulkan compute a prerequisite for proving the artifact format.
- Do not rely on undocumented camera IDs without reporting confidence and fallback behavior.
- Keep every burst and processed output reproducible through manifests and telemetry.

## Definition Of The Next Milestone

The computational-camera milestone is complete when:

- The app captures a 10-frame RAW or YUV burst.
- Every frame has metadata.
- The burst package can be processed offline into one output image.
- The output is visibly better than the weakest single frame for at least one test scene.
- The app displays the latest processed result and processing telemetry.
- Preview remains responsive during normal framing and recovers after capture.
