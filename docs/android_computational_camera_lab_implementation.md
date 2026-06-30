# Android Computational Camera Lab Implementation Guide

This guide is the step-by-step implementation companion to `docs/android_computational_camera_lab_plan.md`. It assumes the current Android camera architecture:

- App/HUD: `examples/camera/app_main.py`
- Android view bridge: `android/app/src/main/java/com/luvatrix/app/LuvatrixVulkanView.kt`
- Camera2 bridge: `android/app/src/main/java/com/luvatrix/app/CameraBridge.kt`
- Native preview renderer: `android/app/src/main/cpp/luvatrix_vulkan_renderer.cpp`
- Python boot/runtime bridge: `android/app/src/main/python/luvatrix_android_boot.py`
- Android sensor adapter: `luvatrix_core/platform/android/sensors.py`
- Upload/sync path: `luvatrix_core/platform/android/runner.py`

The first implementation milestone is deliberately narrow:

```text
Manual 10-frame YUV burst
  -> saved BurstPackage artifact
  -> every frame has metadata
  -> offline v0 processor chooses a reference frame
  -> app HUD displays latest burst ID and output path
```

Do this before RAW merge, brand styles, semantic masks, or Vulkan compute. The goal is to prove the capture artifact and feedback loop.

## Non-Negotiable Boundaries

Keep these boundaries intact in every patch:

```text
Preview path:
Camera2 -> PRIVATE HardwareBuffer -> Vulkan preview -> Python HUD

Still-quality path:
Camera2 burst/RAW/YUV -> artifact package -> processing backend -> output image
```

Rules:

1. Do not make preview frames the source of final quality unless explicitly running a debug YUV burst mode.
2. Do not add heavy processing to the preview callback.
3. Do not let preview quality modes silently change still capture quality.
4. Do not make Python HUD parse vague strings when Kotlin can emit structured telemetry.
5. Do not require Vulkan compute for the first burst artifact.

## Implementation Sequence

Build in these work packets:

```text
Packet 1: CameraCapabilityProfile telemetry
Packet 2: Telemetry normalization in Python
Packet 3: BurstPackage data model and writer
Packet 4: Manual YUV burst capture controller
Packet 5: Python HUD burst controls and status
Packet 6: Offline burst processor v0
Packet 7: App result feedback loop
Packet 8: RAW burst extension
Packet 9: Reconstruction backend interface
Packet 10: Style profile scaffold
```

Each packet should be small enough to test and upload independently. Work test-first:

```text
1. Red: add or update tests/source-contract checks that fail.
2. Green: implement the smallest change that makes those tests pass.
3. Refactor: clean up names, helpers, and telemetry shape without changing behavior.
4. Device behavior: upload to the USB-connected phone, watch logs, and verify the expected app behavior.
5. Iterate: if the phone fails, classify the error, add/adjust a focused test, fix, and re-upload.
```

For Kotlin-heavy work, the red test will often be a source-contract test in `tests/test_android_packaging.py` plus Python telemetry/HUD tests. For Python tools and artifact contracts, the red test should be a normal executable unit test with synthetic fixtures.

Local tests are necessary but not sufficient. A packet is not done until the app has been uploaded to the connected phone and the relevant behavior has been observed in the running app. Use `docs/android_camera_on_device_iteration_guide.md` as the operational runbook for upload, logcat, failure classification, and retry loops.

## On-Device Behavior Gate

Run this gate after every packet that changes Android/Kotlin, Python boot code, camera telemetry, HUD behavior, or capture behavior.

Preflight:

```bash
adb devices
git status --short --branch
```

Upload:

```bash
adb logcat -c
uv run python main.py run-app examples/camera --render android-device --native-project android
```

Watch logs:

```bash
adb logcat -s Luvatrix python stderr AndroidRuntime
```

Minimum healthy launch criteria:

- APK build succeeds.
- Install reports `Success`.
- `MainActivity` starts.
- No uncaught Python exception appears in logcat.
- No Android runtime crash appears in logcat.
- The camera lab HUD appears on the phone.
- The app remains alive for at least 30 seconds.

If the packet changes camera preview or capture behavior, also verify:

- Camera permission is granted or prompt appears.
- Preview is visible, or HUD reports a structured unavailable/fallback reason.
- HUD telemetry updates after launch.
- Touch/key controls still update action status.

If the phone fails, do not continue to the next packet. Add or adjust a local test that captures the failure class when possible, implement the smallest fix, rerun local tests, and re-upload.

## Packet 1: CameraCapabilityProfile Telemetry

Purpose: stop guessing camera capability from scattered telemetry.

### Red Test First

Before adding Kotlin implementation, update tests so they fail:

1. In `tests/test_android_packaging.py`, assert the Android source contains `CameraCapabilityProfile`, `capability_profile`, `camera.capabilities.raw`, `camera.capabilities.private_preview`, and `REQUEST_MAX_NUM_OUTPUT_STREAMS`.
2. In `tests/test_camera_example.py`, add a telemetry-formatting test with dotted capability keys and expect a line like `cap: FULL raw=yes private=yes burst=8`.
3. Run `uv run pytest tests/test_android_packaging.py tests/test_camera_example.py` and confirm the new assertions fail for the expected missing symbols/line.

### Green Implementation

Implement the smallest Kotlin and Python changes needed to satisfy those tests.

### Step 1.1: Add Kotlin data classes

Edit `android/app/src/main/java/com/luvatrix/app/CameraBridge.kt`.

Add these data classes near the existing private data classes in `CameraBridge`:

```kotlin
private data class CameraCapabilityProfile(
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
    val colorInfo: ColorInfo,
)

private data class StreamCombo(
    val id: String,
    val outputs: List<StreamOutput>,
    val expectedUse: String,
)

private data class StreamOutput(
    val format: String,
    val width: Int,
    val height: Int,
)

private data class SensorInfo(
    val orientationDegrees: Int,
    val pixelArrayWidth: Int,
    val pixelArrayHeight: Int,
    val activeArrayWidth: Int,
    val activeArrayHeight: Int,
)

private data class LensInfo(
    val facing: String,
    val focalLengthsMm: List<Float>,
    val apertures: List<Float>,
    val minFocusDistanceDiopters: Float?,
)

private data class ColorInfo(
    val colorFilterArrangement: String,
    val whiteLevel: Int?,
    val blackLevelPattern: List<Int>,
)
```

Keep these private until the contract stabilizes.

### Step 1.2: Add profile construction helpers

In `CameraBridge`, add:

```kotlin
private fun capabilityProfile(cameraId: String): CameraCapabilityProfile
private fun capabilityProfileJson(profile: CameraCapabilityProfile): JSONObject
private fun sizeListJson(sizes: List<Size>): JSONArray
private fun hardwareLevelName(value: Int?): String
private fun lensFacingName(value: Int?): String
```

Implementation details:

- Get characteristics with `cameraManager.getCameraCharacteristics(cameraId)`.
- Read `CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP`.
- `yuvSizes = map.getOutputSizes(ImageFormat.YUV_420_888)?.toList().orEmpty()`.
- `rawSizes = map.getOutputSizes(ImageFormat.RAW_SENSOR)?.toList().orEmpty()`.
- `privateSizes = map.getOutputSizes(ImageFormat.PRIVATE)?.toList().orEmpty()`.
- `supportsRaw` should require both RAW capability and at least one RAW size.
- `supportsPrivatePreview` should require API >= Q and at least one PRIVATE size.
- `maxBurstTargets` can start as `REQUEST_MAX_NUM_OUTPUT_STREAMS_PROC + REQUEST_MAX_NUM_OUTPUT_STREAMS_RAW`, falling back to a conservative value when keys are absent.
- `supportsYuvReprocess` should check `REQUEST_AVAILABLE_CAPABILITIES_YUV_REPROCESSING`.

### Step 1.3: Add profile cache

Add a cache field:

```kotlin
private val capabilityProfiles = LinkedHashMap<String, CameraCapabilityProfile>()
```

Add:

```kotlin
private fun profileFor(cameraId: String): CameraCapabilityProfile {
    return capabilityProfiles.getOrPut(cameraId) { capabilityProfile(cameraId) }
}
```

Use `profileFor(cameraId)` anywhere preview/session selection currently recalculates basic size/capability facts.

### Step 1.4: Expose profile in inventory

In `inventoryJson()`, each camera object should include:

```json
{
  "capability_profile": {...},
  "capabilities": {
    "raw": true,
    "private_preview": true,
    "max_burst": 8,
    "hardware_level": "FULL"
  }
}
```

Keep existing fields for compatibility. Add new fields; do not rename current fields yet.

### Step 1.5: Expose active profile in telemetry

In `telemetryJson()`, add:

```kotlin
.put("active_capability_profile", primaryCameraId?.let { capabilityProfileJson(profileFor(it)) } ?: JSONObject.NULL)
.put("camera.capabilities.raw", primaryCameraId?.let { profileFor(it).supportsRaw } ?: false)
.put("camera.capabilities.private_preview", primaryCameraId?.let { profileFor(it).supportsPrivatePreview } ?: false)
.put("camera.capabilities.max_burst", primaryCameraId?.let { profileFor(it).maxBurstTargets } ?: 0)
.put("camera.capabilities.hardware_level", primaryCameraId?.let { profileFor(it).hardwareLevel } ?: "UNKNOWN")
```

Yes, the dotted keys are JSON keys. They make the HUD and logs easy to grep.

### Step 1.6: Expand coverage before refactor

Update `tests/test_android_packaging.py` to assert the source contains:

- `CameraCapabilityProfile`
- `capability_profile`
- `camera.capabilities.raw`
- `camera.capabilities.private_preview`
- `REQUEST_MAX_NUM_OUTPUT_STREAMS`

Update `tests/test_camera_example.py` with a formatting test for a sample containing:

```python
{
    "camera.capabilities.raw": True,
    "camera.capabilities.private_preview": True,
    "camera.capabilities.max_burst": 8,
    "camera.capabilities.hardware_level": "FULL",
}
```

Expected HUD debug text should include something like:

```text
cap: FULL raw=yes private=yes burst=8
```

### Step 1.7: Verify

Run:

```bash
uv run pytest tests/test_android_packaging.py tests/test_camera_example.py tests/test_android_sensors.py
```

Then upload:

```bash
uv run python main.py run-app examples/camera --render android-device --native-project android
```

On the device, debug HUD should show capability summary without needing to start RAW capture first.

### On-Device Behavior

After upload, open/toggle the debug HUD and verify:

- Capability line appears for the active camera.
- Hardware level is not `UNKNOWN` when Camera2 exposes it.
- RAW/private/burst fields are populated from structured telemetry.
- Logcat has no `luvatrix run_app_vulkan failed` traceback.

### Refactor Gate

Only after the tests pass, deduplicate size JSON helpers and rename telemetry fields if needed. Re-run the same focused tests after refactoring.

## Packet 2: Telemetry Normalization In Python

Purpose: isolate HUD formatting from raw Android telemetry shape.

### Red Test First

Before adding normalizer code, write failing tests in `tests/test_camera_example.py` for:

1. Dotted top-level keys.
2. Nested `capabilities`.
3. Nested `active_capability_profile`.
4. Missing fields falling back to `UNKNOWN`, `False`, and `0`.

Run:

```bash
uv run pytest tests/test_camera_example.py -k capability
```

Confirm the tests fail because `camera_capability_summary` or the expected HUD line does not exist yet.

### Green Implementation

Add only enough helper code and HUD formatting to make the red tests pass.

### Step 2.1: Add normalizer helpers

Edit `examples/camera/app_main.py`.

Add:

```python
@dataclass(frozen=True)
class CameraCapabilitySummary:
    hardware_level: str
    supports_raw: bool
    supports_private_preview: bool
    max_burst: int


def camera_capability_summary(camera: dict[str, object]) -> CameraCapabilitySummary:
    ...
```

Lookup order:

1. Dotted top-level telemetry keys.
2. `camera["capabilities"]`.
3. `camera["active_capability_profile"]`.
4. Default values.

### Step 2.2: Use summary in HUD lines

In `_preview_diagnostic_lines()` or a new `_capability_lines()` helper, add one compact line:

```text
cap: FULL raw=yes private=yes burst=8
```

In collapsed/compact HUD, only show capability if camera telemetry exists and the line can fit.

### Step 2.3: Confirm coverage

Confirm the red tests cover all three input shapes:

- dotted top-level keys
- nested `capabilities`
- nested `active_capability_profile`

Run:

```bash
uv run pytest tests/test_camera_example.py
```

### On-Device Behavior

Upload and verify:

- HUD still appears.
- Capability line renders in the expected HUD mode.
- Missing capability fields do not crash the HUD.
- Logcat is clean for at least 30 seconds.

## Packet 3: BurstPackage Data Model And Writer

Purpose: define the artifact before building complex capture logic.

### Red Test First

Start by adding failing tests/checks:

1. In `tests/test_android_packaging.py`, assert source contains `BurstPackageWriter`, `burst_manifest.json`, `burst_capture`, and `writeYuvFrame`.
2. In `tests/test_camera_example.py`, add burst telemetry formatting tests for idle, capturing, saved, and error states.
3. Run `uv run pytest tests/test_android_packaging.py tests/test_camera_example.py` and confirm failures are for missing burst source symbols and missing HUD lines.

### Green Implementation

Add the writer, telemetry fields, and HUD formatting with the smallest possible behavior. Do not implement capture yet.

### Step 3.1: Choose storage location

Use app-private files first:

```text
context.filesDir/computational_camera/bursts/{burst_id}/
```

Do not use public gallery storage for raw intermediate frames yet.

### Step 3.2: Add Kotlin manifest classes

In `CameraBridge.kt`, add:

```kotlin
private data class BurstFrameRecord(
    val index: Int,
    val framePath: String,
    val metadataPath: String,
    val timestampNs: Long,
    val format: String,
    val width: Int,
    val height: Int,
)

private data class BurstManifest(
    val burstId: String,
    val cameraId: String,
    val format: String,
    val frameCount: Int,
    val requestedFrameCount: Int,
    val exposureStrategy: String,
    val iso: Int?,
    val exposureTimeNs: Long?,
    val awbLocked: Boolean,
    val aeLocked: Boolean,
    val afLocked: Boolean,
    val gyroAvailable: Boolean,
    val frames: List<BurstFrameRecord>,
)
```

### Step 3.3: Add BurstPackageWriter

Add a private class inside `CameraBridge.kt` first. Later, move it to its own file if it grows.

```kotlin
private class BurstPackageWriter(
    private val rootDir: File,
    private val burstId: String,
    private val cameraId: String,
    private val format: String,
    private val requestedFrameCount: Int,
)
```

Methods:

```kotlin
fun burstDir(): File
fun writeYuvFrame(index: Int, image: Image, metadata: JSONObject): BurstFrameRecord
fun writeRawFrame(index: Int, image: Image, result: TotalCaptureResult, chars: CameraCharacteristics): BurstFrameRecord
fun writeManifest(manifest: BurstManifest): File
```

For YUV v1, write a simple raw planar file:

```text
frame_000.yuv
```

And metadata:

```text
metadata_000.json
```

YUV metadata must include:

```json
{
  "format": "YUV_420_888",
  "width": 1920,
  "height": 1080,
  "timestamp_ns": 123,
  "planes": [
    {"name": "Y", "row_stride": 1920, "pixel_stride": 1, "byte_count": 2073600},
    {"name": "U", "row_stride": 960, "pixel_stride": 2, "byte_count": 1036800},
    {"name": "V", "row_stride": 960, "pixel_stride": 2, "byte_count": 1036800}
  ]
}
```

### Step 3.4: Add telemetry state

Add fields:

```kotlin
private var burstStatus: String = "idle"
private var burstLastError: String = ""
private var burstLastId: String = ""
private var burstLastPath: String = ""
private var burstRequestedFrames: Int = 0
private var burstCapturedFrames: Int = 0
private var burstLastManifestPath: String = ""
```

Add:

```kotlin
private fun burstTelemetryJson(): JSONObject
```

Return:

```json
{
  "status": "idle|capturing|saved|error",
  "last_error": "",
  "last_burst_id": "",
  "last_path": "",
  "requested_frames": 10,
  "captured_frames": 10,
  "manifest_path": ""
}
```

Add `.put("burst_capture", burstTelemetryJson())` to `telemetryJson()`.

### Step 3.5: Expand coverage before refactor

Packaging test should assert:

- `BurstPackageWriter`
- `burst_manifest.json`
- `burst_capture`
- `writeYuvFrame`

Python HUD tests should format:

```text
burst: idle
burst: saved 10/10
burst error: ...
```

Run:

```bash
uv run pytest tests/test_android_packaging.py tests/test_camera_example.py
```

### On-Device Behavior

Upload and verify:

- App launches with the new `burst_capture` telemetry present.
- HUD can display idle burst state.
- No capture action is required yet.
- Existing preview and RAW single-capture controls still work as before.

## Packet 4: Manual YUV Burst Capture Controller

Purpose: capture repeatable burst artifacts without touching final reconstruction yet.

### Red Test First

Add failing checks before touching capture logic:

1. In `tests/test_android_packaging.py`, assert source contains `captureYuvBurst`, `PendingYuvBurst`, `writeManifest`, and `handler.postDelayed`.
2. In `tests/test_camera_example.py`, add expected bridge helper names if Packet 5 is being done in the same branch.
3. Run focused tests and confirm failures are about missing burst capture entrypoints.

### Green Implementation

Add the smallest YUV burst path that collects existing YUV preview frames into a package. Do not add RAW burst or background processing in this packet.

### Step 4.1: Add bridge entrypoint

In `CameraBridge.kt`, add:

```kotlin
fun captureYuvBurst(frameCount: Int): String
```

Rules:

- Clamp `frameCount` to `1..maxBurstTargets`, with a temporary hard cap of `10` until profiles are trusted.
- Require primary preview stream to be running.
- Require a YUV reader to be available.
- Return `burstTelemetryJson().toString()`.

### Step 4.2: Add view method

In `LuvatrixVulkanView.kt`, add:

```kotlin
fun captureYuvBurst(frameCount: Int): String {
    return cameraBridge.captureYuvBurst(frameCount)
}
```

### Step 4.3: Add Python boot bridge method

In both:

- `android/app/src/main/python/luvatrix_android_boot.py`
- `luvatrix_core/templates/native/android/app/src/main/python/luvatrix_android_boot.py`

Add:

```python
def capture_yuv_burst(frame_count: int = 10) -> str:
    return _call_view_raw_control("captureYuvBurst", "capture_yuv_burst", int(frame_count))
```

### Step 4.4: Implement v1 burst strategy

Inside `CameraStream`, add a burst mode that uses the existing YUV preview callback.

Start simple:

- Set `burstStatus = "capturing"`.
- Create a `BurstPackageWriter`.
- Set a pending YUV burst object on the primary stream.
- In `handleImage(image)`, after existing preview handling succeeds, copy the same image into burst package while capture is active.
- Stop collecting after N frames.
- Write manifest.
- Set `burstStatus = "saved"`.

This means v1 burst quality is bounded by the YUV cache stream, but it proves artifact and UI. Later, add dedicated still/burst capture sessions.

Pending burst state sketch:

```kotlin
private data class PendingYuvBurst(
    val burstId: String,
    val writer: BurstPackageWriter,
    val requestedFrames: Int,
    val startedAtNs: Long,
    val records: MutableList<BurstFrameRecord>,
)
```

### Step 4.5: Add timeout

When capture starts, post a handler timeout:

```kotlin
handler.postDelayed({ fail if still capturing }, 5_000L)
```

On timeout:

- Write partial manifest if any frames exist.
- Set status `error` or `partial`.
- Include captured/requested count.

### Step 4.6: Avoid blocking preview too much

The first implementation may write on the camera handler, but immediately add telemetry:

```json
{
  "burst_capture": {
    "write_mode": "camera_handler_sync",
    "last_write_ms": 12.4
  }
}
```

If `last_write_ms` is high, next packet moves file writes to a background queue.

### Step 4.7: Confirm source checks

In `tests/test_android_packaging.py`, assert:

- `captureYuvBurst`
- `PendingYuvBurst`
- `writeManifest`
- `handler.postDelayed`

Run:

```bash
uv run pytest tests/test_android_packaging.py
```

### Step 4.8: On-device test

Upload:

```bash
uv run python main.py run-app examples/camera --render android-device --native-project android
```

Use HUD/button/keyboard after Packet 5. Before Packet 5, test via a temporary Python call or Android instrumentation if convenient.

Pull files:

```bash
adb shell run-as com.luvatrix.app ls files/computational_camera/bursts
adb exec-out run-as com.luvatrix.app tar cf - files/computational_camera/bursts > /tmp/luvatrix_bursts.tar
```

Behavior required before closing Packet 4:

- Starting a YUV burst changes telemetry to `capturing`.
- Captured frame count increases.
- Completion changes telemetry to `saved`, `partial`, or a structured `error`.
- Preview recovers after burst attempt.
- Logcat contains no uncaught exception.

## Packet 5: Python HUD Burst Controls And Status

Purpose: make burst capture usable from the camera lab UI.

### Red Test First

Write failing tests in `tests/test_camera_example.py` first:

1. Key `b` calls `_android_capture_yuv_burst(10)`.
2. Key `n` cycles burst depth.
3. Touch button action routes to the burst helper.
4. Burst telemetry renders idle/capturing/saved/error states.

Run:

```bash
uv run pytest tests/test_camera_example.py -k burst
```

Confirm these tests fail before implementation.

### Green Implementation

Add only the HUD state, button/key routing, bridge helper, and formatting required by the tests.

### Step 5.1: Add app state

In `CameraLabApp.__init__`, add:

```python
self._burst_frame_count = 10
```

### Step 5.2: Add action methods

Add:

```python
def _capture_yuv_burst(self) -> None:
    self._last_action_status = f"capturing YUV burst x{self._burst_frame_count}"
    _android_capture_yuv_burst(self._burst_frame_count)

def _cycle_burst_depth(self) -> None:
    order = (3, 5, 10, 12)
    ...
```

Add bridge helper:

```python
def _android_capture_yuv_burst(frame_count: int) -> None:
    try:
        import luvatrix_android_boot
        luvatrix_android_boot.capture_yuv_burst(int(frame_count))
    except Exception:
        return
```

### Step 5.3: Add buttons/keys

Suggested keys:

```text
b: capture YUV burst
n: cycle burst depth
```

Suggested buttons:

```text
burst
depth
```

Update `_handle_camera_key`, `_handle_touch_action`, and `_control_buttons`.

### Step 5.4: Format burst telemetry

Add:

```python
def _burst_capture_lines(camera: dict[str, object]) -> list[str]:
    ...
```

Expected lines:

```text
burst: idle
burst: capturing 4/10
burst: saved 10/10 2026-06-04T...
burst path: .../burst_manifest.json
burst error: ...
```

Add to compact and debug HUD modes.

### Step 5.5: Confirm tests

Update `tests/test_camera_example.py`:

- key `b` routes to `_android_capture_yuv_burst(10)`
- key `n` cycles burst depth
- button action routes to burst call
- formatting handles idle/capturing/saved/error

Run:

```bash
uv run pytest tests/test_camera_example.py
```

### On-Device Behavior

Upload and verify:

- `b` or the burst button triggers a burst.
- `n` or the depth button changes burst depth.
- HUD shows `capturing` and then `saved`, `partial`, or structured `error`.
- Touch controls remain responsive after burst.
- Pulling app-private files shows a burst package when capture succeeds.

## Packet 6: Offline Burst Processor v0

Purpose: prove the artifact can produce an output image before building native processing.

### Red Test First

Create the test before the tool:

1. Add `tests/test_camera_burst_processing.py`.
2. Build a synthetic temp burst with two tiny Y-plane frames.
3. Assert the future processor selects the higher-contrast frame.
4. Assert it writes `processing_manifest.json`.
5. Run `uv run pytest tests/test_camera_burst_processing.py` and confirm it fails because the tool/module does not exist.

### Green Implementation

Create the smallest processor that loads manifest JSON, scores Y luma, picks a reference frame, and writes a processing manifest.

### Step 6.1: Add tool file

Create:

```text
tools/camera/process_burst.py
```

Command:

```bash
uv run python tools/camera/process_burst.py BURST_DIR --out OUT_DIR --mode sharpest
```

### Step 6.2: Implement manifest loader

Use standard library JSON and pathlib. Avoid adding dependencies.

Functions:

```python
def load_manifest(burst_dir: Path) -> dict[str, object]
def load_frame_metadata(burst_dir: Path, frame_record: dict[str, object]) -> dict[str, object]
```

### Step 6.3: Implement YUV luma sharpness score

For `YUV_420_888`, read only the Y plane bytes using metadata. Compute a simple score:

```text
mean absolute difference between neighboring luma samples
```

No numpy required for v0. Use bytes and loops over a downsampled grid.

### Step 6.4: Write processor output manifest

Output:

```text
OUT_DIR/
  processing_manifest.json
```

Manifest:

```json
{
  "burst_id": "...",
  "mode": "sharpest",
  "reference_frame": 3,
  "scores": [
    {"index": 0, "sharpness": 12.4},
    {"index": 1, "sharpness": 15.1}
  ],
  "output_path": "",
  "preview_path": ""
}
```

If image export is not implemented yet, leave `output_path` empty and still make scoring work.

### Step 6.5: Keep fixtures synthetic

Create tiny synthetic burst fixture in a test temp directory rather than checking binary frames into the repo.

Add:

```text
tests/test_camera_burst_processing.py
```

Test:

- two fake Y-plane frames
- one blurred/flat
- one high-contrast
- processor selects high-contrast frame

Run:

```bash
uv run pytest tests/test_camera_burst_processing.py
```

### On-Device Behavior

This packet is mostly offline, but still verify the full loop with a real pulled package when Packet 4/5 exists:

```bash
adb shell run-as com.luvatrix.app find files/computational_camera -maxdepth 5 -type f
adb exec-out run-as com.luvatrix.app tar cf - files/computational_camera > /tmp/luvatrix_camera_artifacts.tar
mkdir -p /tmp/luvatrix_camera_artifacts
tar xf /tmp/luvatrix_camera_artifacts.tar -C /tmp/luvatrix_camera_artifacts
```

Then run the processor against a real burst directory and confirm it writes `processing_manifest.json`.

## Packet 7: App Result Feedback Loop

Purpose: return processing results to the app without building a full gallery.

### Red Test First

Add failing tests/checks:

1. In `tests/test_android_packaging.py`, assert source contains `registerProcessedOutput` and `processingTelemetryJson`.
2. In `tests/test_camera_example.py`, assert processing telemetry formats idle, success, and error states.
3. Run focused tests and confirm they fail on missing processing symbols/lines.

### Green Implementation

Add minimal processing telemetry and manual result registration. Do not implement an on-device processing queue yet.

### Step 7.1: Add processing telemetry fields

In `CameraBridge.kt`, add:

```kotlin
private var processingStatus: String = "idle"
private var processingCurrentStage: String = ""
private var processingLastOutputPath: String = ""
private var processingLastPreviewPath: String = ""
private var processingLastError: String = ""
```

Add:

```kotlin
private fun processingTelemetryJson(): JSONObject
```

Telemetry:

```json
{
  "status": "idle",
  "stage": "",
  "last_output_path": "",
  "last_preview_path": "",
  "last_error": ""
}
```

Add `.put("processing", processingTelemetryJson())` to `telemetryJson()`.

### Step 7.2: Add manual result registration

Add Kotlin view/bridge method:

```kotlin
fun registerProcessedOutput(outputPath: String, previewPath: String): String
```

Add boot method:

```python
def register_processed_output(output_path: str, preview_path: str = "") -> str:
    return _call_view_raw_control("registerProcessedOutput", "register_processed_output", str(output_path), str(preview_path))
```

This lets the external/offline processor report an output path for the HUD before on-device processing exists.

### Step 7.3: HUD formatting

Add processing lines:

```text
processing: idle
processing: sharpest done
output: IMG_...
```

Confirm tests in `tests/test_camera_example.py` pass before moving on.

### On-Device Behavior

Upload and verify:

- Registering or producing a processed output changes `processing` telemetry.
- HUD displays processing status and output path.
- App does not need to restart to show the latest result.

## Packet 8: RAW Burst Extension

Purpose: graduate from YUV debug burst to RAW capture packages.

Prerequisites:

- Packet 1 profile identifies RAW support.
- Packet 3 writer supports DNG frames.
- Packet 4 burst state works for N frames.

### Red Test First

Add failing tests/checks:

1. In `tests/test_android_packaging.py`, assert source contains `captureRawBurst`, `pendingRawImagesByTimestamp`, `SENSOR_TIMESTAMP`, and `DngCreator`.
2. In `tests/test_camera_example.py`, assert RAW burst is unavailable when capability profile says RAW is false, and routes to the boot helper when RAW is true.
3. Run focused tests and confirm failures are the expected missing symbols/routes.

### Green Implementation

Implement only timestamp-paired RAW burst capture and artifact writing. Do not add RAW fusion yet.

### Step 8.1: Add capture entrypoint

```kotlin
fun captureRawBurst(frameCount: Int): String
```

Rules:

- Require `profile.supportsRaw`.
- Require active session includes RAW, or create a temporary RAW burst session.
- Start with locked AE/AWB/AF.

### Step 8.2: Request sequence

Create N still capture requests using `CameraDevice.TEMPLATE_STILL_CAPTURE`.

For each request:

- add RAW target
- set manual controls if raw mode is manual
- set AE/AWB/AF lock if requested
- attach capture callback

### Step 8.3: Pair images and metadata

Use timestamp matching:

```text
Image.timestamp == CaptureResult.SENSOR_TIMESTAMP
```

Store pending maps:

```kotlin
pendingRawImagesByTimestamp
pendingRawResultsByTimestamp
```

When both arrive, write frame and metadata.

### Step 8.4: RAW manifest additions

Add per-frame:

```json
{
  "sensor_sensitivity_iso": 400,
  "sensor_exposure_time_ns": 8333333,
  "sensor_frame_duration_ns": 16666666,
  "lens_focal_length_mm": 5.4,
  "lens_focus_distance_diopters": 0.5,
  "color_filter_arrangement": "RGGB",
  "black_level_pattern": [64, 64, 64, 64],
  "white_level": 1023
}
```

### Step 8.5: Confirm coverage

Source-level packaging tests:

- `captureRawBurst`
- `pendingRawImagesByTimestamp`
- `SENSOR_TIMESTAMP`
- `DngCreator`

Python HUD tests:

- RAW burst unavailable when capability profile says no RAW.
- RAW burst button routes to boot helper when supported.

### On-Device Behavior

Upload and verify on a RAW-capable phone:

- HUD reports RAW capability.
- RAW burst command starts capture or reports a structured unsupported/session error.
- If capture succeeds, app-private files include DNG frames, metadata JSON files, and `burst_manifest.json`.
- Preview resumes after RAW burst success, timeout, or failure.

## Packet 9: Reconstruction Backend Interface

Purpose: stop the processing path from becoming one giant script.

### Red Test First

Add `tests/test_camera_processing_contract.py` before adding the module:

1. Request JSON roundtrip.
2. Result JSON roundtrip.
3. Unknown mode rejected with a readable error.
4. Missing required fields rejected.

Run:

```bash
uv run pytest tests/test_camera_processing_contract.py
```

Confirm the test fails because the contract module does not exist.

### Green Implementation

Add the smallest dataclasses and JSON helpers needed to pass the contract tests.

### Step 9.1: Define request/result JSON first

Use JSON contracts before C++ structs.

Request:

```json
{
  "burst_id": "...",
  "burst_manifest_path": "...",
  "mode": "sharpest|average_aligned|raw_linear",
  "style": "neutral",
  "quality": "draft|standard|best"
}
```

Result:

```json
{
  "burst_id": "...",
  "status": "ok",
  "output_path": "...",
  "preview_path": "...",
  "telemetry": {
    "reference_frame": 3,
    "used_frames": 8,
    "rejected_frames": 2
  }
}
```

### Step 9.2: Add Python protocol module

Create:

```text
luvatrix_core/platform/android/camera_processing_contract.py
```

Include dataclasses:

```python
ProcessingRequest
ProcessingResult
ProcessingTelemetry
```

Add JSON load/dump helpers.

### Step 9.3: Make offline processor use the contract

Update `tools/camera/process_burst.py` to emit `ProcessingResult`.

### Step 9.4: Confirm tests

Confirm the red tests cover:

- request JSON roundtrip
- result JSON roundtrip
- unknown mode rejected with readable error

Run:

```bash
uv run pytest tests/test_camera_processing_contract.py tests/test_camera_burst_processing.py
```

### On-Device Behavior

Upload only if Android/Python boot or HUD code changed. Verify:

- App launch remains healthy.
- Processing request/result telemetry still formats correctly in HUD.
- If using a pulled burst, processor output can be registered back into the app through the bridge.

## Packet 10: Style Profile Scaffold

Purpose: create rendering-layer contracts before implementing brand looks.

### Red Test First

Add `tests/test_camera_style_profiles.py` first:

1. Assert all planned style JSON files exist.
2. Assert all checked-in styles validate.
3. Assert invalid saturation fails.
4. Assert missing `name` fails.

Run:

```bash
uv run pytest tests/test_camera_style_profiles.py
```

Confirm it fails because profiles/loader do not exist.

### Green Implementation

Add minimal profile JSON files and a strict loader/validator. Do not implement actual style rendering in this packet.

### Step 10.1: Add style profile directory

Create:

```text
assets/camera_styles/
  neutral.json
  samsung_pop.json
  apple_natural.json
  google_hdr.json
  xiaomi_vibrant.json
```

If repo-level assets are not desired yet, start under:

```text
examples/camera/styles/
```

### Step 10.2: Define minimal schema

Fields:

```json
{
  "name": "Neutral",
  "version": 1,
  "shadow_lift": 0.0,
  "highlight_rolloff": 0.5,
  "global_saturation": 1.0,
  "local_contrast": 1.0,
  "sharpening": 1.0,
  "skin_smoothing": 0.0,
  "sky_saturation": 1.0,
  "foliage_saturation": 1.0,
  "white_balance_bias": "neutral"
}
```

### Step 10.3: Add loader

Create:

```text
luvatrix_core/platform/android/camera_style.py
```

Functions:

```python
def load_style_profile(path: Path) -> dict[str, object]
def validate_style_profile(profile: dict[str, object]) -> None
```

Keep validation strict:

- numeric values must be finite
- saturation ranges `0.0..3.0`
- sharpening range `0.0..3.0`
- known white balance bias strings only

### Step 10.4: Confirm tests

Keep the red test file:

```text
tests/test_camera_style_profiles.py
```

Verify:

- all checked-in styles validate
- invalid saturation fails
- missing name fails

### On-Device Behavior

Upload if style choices are exposed in HUD. Verify:

- Style selector displays available profiles.
- Selecting a style changes only rendering/processing telemetry, not preview session mode.
- Missing/invalid style profile reports a structured error rather than crashing Python.

## On-Device Debugging Workflow

Use this loop for Android runtime issues:

```bash
uv run python main.py run-app examples/camera --render android-device --native-project android
adb logcat -s Luvatrix python stderr AndroidRuntime
```

If app launches but Python runtime errors:

1. Check `android/app/src/main/python/luvatrix_launch_config.json`.
2. Check `android/app/src/main/python/examples/camera/_luvatrix_bundle.py` exists.
3. Re-run upload.
4. Watch logcat for `luvatrix run_app_vulkan failed`.

If camera permission errors:

```bash
adb shell appops get com.luvatrix.app CAMERA
adb shell pm grant com.luvatrix.app android.permission.CAMERA
```

If files need to be pulled:

```bash
adb shell run-as com.luvatrix.app find files/computational_camera -maxdepth 4 -type f
adb exec-out run-as com.luvatrix.app tar cf - files/computational_camera > /tmp/luvatrix_camera_artifacts.tar
```

## Verification Matrix

Run focused Python tests after each packet:

```bash
uv run pytest tests/test_android_packaging.py
uv run pytest tests/test_camera_example.py
uv run pytest tests/test_android_sensors.py
uv run pytest tests/test_android_runner.py
uv run pytest tests/test_android_scene_target.py
```

The first command in a packet should be the new focused test command, and it should fail before implementation. If it passes before code changes, the test is not proving the new behavior.

Run on-device behavior checks after local tests:

```bash
adb devices
adb logcat -c
uv run python main.py run-app examples/camera --render android-device --native-project android
adb logcat -s Luvatrix python stderr AndroidRuntime
```

For any packet that adds capture artifacts, pull and inspect app-private files:

```bash
adb shell run-as com.luvatrix.app find files/computational_camera -maxdepth 5 -type f
adb exec-out run-as com.luvatrix.app tar cf - files/computational_camera > /tmp/luvatrix_camera_artifacts.tar
```

A packet is complete only when both are true:

- Focused local tests are green.
- The expected behavior works on the connected phone without uncaught runtime errors.

Run upload smoke after any Android/Kotlin/Python boot change:

```bash
uv run python main.py run-app examples/camera --render android-device --native-project android
```

Optional import-only probe:

```bash
uv run python main.py run-app examples/camera --render android-device --native-project android --android-import-probe
```

## Telemetry Contract Checklist

Before adding a HUD display, make sure telemetry exists in this shape:

```json
{
  "active_capability_profile": {},
  "camera.capabilities.raw": true,
  "preview": {},
  "raw_capture": {},
  "burst_capture": {},
  "processing": {},
  "gpu_preview": {}
}
```

Avoid adding new HUD parsing against:

- `last_error` string fragments
- human-readable diagnostic text
- implicit size availability
- active session target guesses

## Commit Boundaries

Recommended commit breakdown:

1. `android: add camera capability profile telemetry`
2. `camera example: normalize capability telemetry in HUD`
3. `android: add burst package writer telemetry`
4. `android: capture manual YUV burst packages`
5. `camera example: add burst controls and HUD status`
6. `tools: add offline burst sharpest-frame processor`
7. `android: surface processing result telemetry`
8. `android: add RAW burst package capture`
9. `camera: add processing request/result contract`
10. `camera: add style profile schema and presets`

Keep generated capture artifacts out of commits. If adding fixtures, synthesize them in tests.

## First Milestone Exit Criteria

Stop and evaluate when all of these are true:

- App uploads without importing `luvatrix_plot` or requiring `torch` for the camera example.
- Debug HUD shows camera capability summary.
- Button/key can trigger a 10-frame YUV burst.
- Device stores a burst directory with `burst_manifest.json`, frame files, and metadata files.
- `tools/camera/process_burst.py` can score the burst and write `processing_manifest.json`.
- HUD shows latest burst ID and processing output path.
- Preview still uses PRIVATE HardwareBuffer when available and remains responsive after capture.

## Next Milestone: On-Device Burst Processing To Gallery

This milestone extends the first burst artifact loop into a visible phone result:

```text
Tap burst
  -> capture YUV BurstPackage
  -> native C++ processor selects sharpest frame
  -> Kotlin exports app-private JPEG + preview JPEG
  -> Kotlin publishes final JPEG to Android MediaStore
  -> Python HUD shows processed result/gallery status
```

Keep the live preview path separate. This is still not HDR merge, RAW processing, or Vulkan compute.

## Packet 11: Native Sharpest-Frame Backend

Purpose: process a saved YUV burst on-device without Android Python image dependencies.

Test first:

```bash
uv run pytest tests/test_android_packaging.py
```

Implementation:

- Add `NativeCameraProcessor.kt` beside `NativeVulkan.kt`.
- Load the existing `luvatrix_vulkan_renderer` library.
- Add `processYuvBurst(manifestPath, outputRgbaPath, previewRgbaPath, previewMaxEdge): String`.
- Add JNI function `Java_com_luvatrix_app_NativeCameraProcessor_processYuvBurst`.
- Native behavior:
  - read `burst_manifest.json`,
  - require `format == "YUV_420_888"`,
  - read each frame sidecar,
  - score luma sharpness from Y plane bytes,
  - select the highest-scoring frame,
  - convert selected YUV to RGBA,
  - write full-size and preview-size RGBA files,
  - return JSON with `sharpest_native`, `reference_frame`, `used_frames`, and `rejected_frames`.

Acceptance:

- CMake/Gradle build succeeds.
- App launches without `UnsatisfiedLinkError`.
- Native failures return structured JSON instead of crashing the app.

## Packet 12: JPEG Export And MediaStore Save

Purpose: turn native RGBA output into visible JPEGs.

Test first:

```bash
uv run pytest tests/test_android_packaging.py
```

Implementation:

- Add processing result state to `CameraBridge.kt`.
- Add `processYuvBurstPackageAsync(burstId, manifestPath)`.
- Compress native RGBA outputs to:

```text
files/computational_camera/processed/<burst_id>/IMG_<burst_id>.jpg
files/computational_camera/processed/<burst_id>/IMG_<burst_id>_preview.jpg
```

- Write `processing_manifest.json` beside the JPEGs.
- Publish the final JPEG to MediaStore:

```text
Pictures/Luvatrix Camera/IMG_<burst_id>.jpg
```

Telemetry must include:

```json
{
  "status": "queued|processing|exporting|done|error",
  "stage": "sharpest_native|jpeg_export|gallery_export",
  "burst_id": "burst_...",
  "last_output_path": "...jpg",
  "last_preview_path": "..._preview.jpg",
  "last_gallery_uri": "content://...",
  "reference_frame": 2,
  "used_frames": 5,
  "rejected_frames": 0,
  "last_error": ""
}
```

Acceptance:

- JPEG compression failures become HUD errors.
- MediaStore insert/copy failures become HUD errors.
- No processing error is app-fatal.

## Packet 13: Auto-Process After YUV Burst

Purpose: one tap completes the still-photo loop.

Implementation:

- In the YUV burst completion path, call `processYuvBurstPackageAsync(...)` only after `writeManifest(...)` succeeds.
- Do not auto-process RAW bursts.
- Add `processLastYuvBurst()` for retry/debug.
- Add Python boot wrapper `process_last_yuv_burst()`.
- Update the HUD to display:

```text
processing: sharpest_native processing
processing: gallery_export done
output: IMG_burst_....jpg
gallery: ...
reference: frame N used=M rejected=K
```

Acceptance:

```bash
uv run pytest tests/test_android_packaging.py tests/test_camera_example.py tests/test_camera_burst_processing.py tests/test_camera_processing_contract.py
```

## Packet 14: On-Device Gallery Acceptance Loop

Upload:

```bash
adb devices
adb logcat -c
uv run python main.py run-app examples/camera --render android-device --native-project android
```

On the phone:

```text
tap burst
wait for processing: gallery_export done
```

Inspect app-private files:

```bash
adb shell run-as com.luvatrix.app find files/computational_camera -maxdepth 4 -type f
```

Expected:

```text
files/computational_camera/bursts/<burst_id>/burst_manifest.json
files/computational_camera/bursts/<burst_id>/frame_000.yuv
files/computational_camera/processed/<burst_id>/IMG_<burst_id>.jpg
files/computational_camera/processed/<burst_id>/IMG_<burst_id>_preview.jpg
files/computational_camera/processed/<burst_id>/processing_manifest.json
```

Check MediaStore:

```bash
adb shell content query --uri content://media/external/images/media --projection _id,display_name,relative_path,date_added
```

Expected:

```text
display_name=IMG_<burst_id>.jpg
relative_path=Pictures/Luvatrix Camera/
```

Logcat gate:

```bash
adb logcat -d -t 500 AndroidRuntime:E Python:E Luvatrix:E com.luvatrix.app:E '*:S'
```

## Packet 15: Troubleshooting Guardrails

Classify failures before continuing:

- `UnsatisfiedLinkError`: Kotlin/JNI name or library load mismatch.
- native `SIGSEGV`/`SIGABRT`: C++ parsing or buffer bounds bug.
- missing `burst_manifest.json`: YUV burst completion failed before processing.
- unsupported RAW burst processing: expected for this milestone.
- JPEG compression failure: RGBA file missing, too small, or bad dimensions.
- MediaStore insert/copy failure: gallery export issue; app-private JPEG may still exist.
- gallery not refreshing immediately: verify MediaStore query before assuming export failed.
- empty/corrupt JPEG: pull app-private JPEG and decode locally.

Exit criteria:

- One burst tap creates a processed JPEG on the phone.
- App-private final and preview JPEGs exist.
- Final JPEG appears in Android gallery/Photos via MediaStore.
- HUD shows output, gallery, and reference-frame telemetry.
- Filtered logcat has no uncaught Java/Kotlin, native, or Python crash.

## RAW Milestone: RAW Burst Processing To Gallery

This milestone extends the YUV burst-to-gallery loop into a RAW-capable still path:

```text
RAW_SENSOR burst
  -> DNG + raw16 + metadata package
  -> native RAW processor
  -> single selected RAW frame render
  -> app-private JPEG + preview JPEG
  -> MediaStore gallery save
  -> HUD shows RAW processing status
```

The first RAW output is intentionally a single selected RAW frame. Do not start with HDR merge.

## Packet 16: RAW Artifact Upgrade

Purpose: make RAW burst packages native-processable without parsing DNG.

Implementation:

- Keep writing `frame_000.dng`.
- Add sibling `frame_000.raw16` using RAW image plane bytes.
- Expand each RAW metadata sidecar with:

```text
raw16_path
raw16_byte_count
row_stride
pixel_stride
bits_per_sample
black_level_pattern
white_level
color_filter_arrangement
color_correction_gains
color_correction_transform
lens_shading_available
```

Manifest compatibility:

- Keep `frame_path` pointing at the DNG.
- Add optional `raw16_path` and `artifact_role`.

Acceptance:

- RAW burst still saves DNG.
- RAW burst also saves raw16.
- YUV burst processing is unchanged.

## Packet 17: Native RAW Processor Entrypoint

Purpose: process RAW packages without disturbing the YUV backend.

Implementation:

- Add `NativeCameraProcessor.processRawBurst(...)`.
- Add JNI function `NativeCameraProcessor_processRawBurst`.
- Native function reads `burst_manifest.json`, requires `RAW_SENSOR`, loads frame sidecars, requires `raw16_path`, scores processable frames by green-channel sharpness, and selects one reference frame.

Return success telemetry:

```json
{
  "status": "ok",
  "mode": "raw_single_frame",
  "raw_reference_frame": 0,
  "reference_frame": 0,
  "used_frames": 1,
  "rejected_frames": 0
}
```

Return structured error JSON instead of crashing.

## Packet 18: Single-Frame RAW Render

Purpose: produce a recognizable JPEG from one RAW frame.

Native render steps:

```text
raw16 bytes
  -> black/white normalized Bayer
  -> bilinear demosaic for RGGB/GRBG/GBRG/BGGR
  -> Camera2 gains/matrix if available
  -> percentile exposure scale
  -> shoulder tone map
  -> gamma 1/2.2
  -> RGBA8
```

Output:

```text
native_output.rgba
native_preview.rgba
```

Acceptance:

- RAW render is visible and decodable.
- It may look plain, but should not be black, neon green, purple, or fully clipped.
- Unknown CFA returns `unsupported color_filter_arrangement` telemetry.

## Packet 19: Kotlin RAW Export And Gallery Save

Purpose: reuse the proven RGBA/JPEG/MediaStore export loop for RAW.

Implementation:

- Add `processRawBurstPackageAsync(burstId, manifestPath)`.
- On successful RAW burst manifest write, auto-process when any frame has `raw16_path`.
- Add `processLastRawBurst()` retry.
- Add view and Python boot wrappers.

Telemetry stages:

```text
raw_single_frame
raw_jpeg_export
raw_gallery_export
```

Output:

```text
files/computational_camera/processed/<raw_burst_id>/IMG_<raw_burst_id>.jpg
files/computational_camera/processed/<raw_burst_id>/IMG_<raw_burst_id>_preview.jpg
Pictures/Luvatrix Camera/IMG_<raw_burst_id>.jpg
```

## Packet 20: HUD And Controls

Purpose: make RAW output discoverable.

Implementation:

- Keep `burst` as the YUV button.
- Show `raw burst` when the active camera supports RAW.
- Display RAW processing telemetry:

```text
processing: raw_single_frame processing
processing: raw_gallery_export done
output: IMG_raw_burst_....jpg
gallery: ...
reference: frame N used=1 rejected=K
```

## Packet 21: On-Device RAW Acceptance

Upload:

```bash
adb devices
adb logcat -c
uv run python main.py run-app examples/camera --render android-device --native-project android
```

Phone behavior:

```text
tap raw burst
wait for raw_gallery_export done
```

Inspect artifacts:

```bash
adb shell run-as com.luvatrix.app find files/computational_camera -maxdepth 5 -type f
```

Expected:

```text
frame_000.dng
frame_000.raw16
metadata_000.json
burst_manifest.json
IMG_<raw_burst_id>.jpg
processing_manifest.json
```

Confirm gallery:

```bash
adb shell content query --uri content://media/external/images/media --projection _id:_display_name:relative_path:date_added
```

Pull and decode:

```bash
adb exec-out run-as com.luvatrix.app cat files/computational_camera/processed/<raw_burst_id>/IMG_<raw_burst_id>.jpg > /private/tmp/luvatrix_raw_processed.jpg
uv run python -c "from PIL import Image; im=Image.open('/private/tmp/luvatrix_raw_processed.jpg'); im.verify(); print('ok', im.format, im.size)"
```

Logcat gate:

```bash
adb logcat -d -t 500 AndroidRuntime:E Python:E Luvatrix:E com.luvatrix.app:E '*:S'
```

## Packet 22: Same-Exposure RAW Average

Status: implemented as `raw_average_no_alignment`.

Next implementation:

- Lock AE/AWB where supported before RAW burst.
- Add native mode `raw_average_no_alignment`.
- Normalize all processable raw16 frames.
- Reject dimension/CFA mismatches.
- Average Bayer values pixel-by-pixel.
- Demosaic and render through the same RAW renderer.

## Packet 23: RAW Alignment Prototype

Status: implemented as `raw_average_global_aligned`.

Next implementation:

- Build downsampled green-channel alignment images.
- Search global translation around reference frame.
- Add native mode `raw_average_global_aligned`.
- Emit `alignment_offsets` and `alignment_failures` telemetry.

## RAW Troubleshooting

- RAW not supported: camera capability profile reports `supports_raw=false`.
- RAW not in active session: active Camera2 session was not configured with RAW target.
- raw16 missing: RAW artifact writer failed before native processing.
- unknown CFA pattern: native render cannot demosaic safely.
- black/purple/green render: inspect CFA, black level, gains, and transform metadata.
- overexposed render: inspect white level and tone map percentile.
- native SIGSEGV/SIGABRT: check raw16 stride/bounds and JNI result path handling.
- JPEG export failure: RGBA output missing, too small, or dimensions invalid.
- gallery export failure: inspect MediaStore insert/copy errors; app-private JPEG may still exist.

## Packet 24: Host-Side Quality Comparison Harness

Status: implemented as `tools/camera/compare_outputs.py`.

Purpose: compare pulled app-private processed outputs without changing the live preview or capture pipeline.

### Step 24.1: Pull Processed Outputs

After capturing one or more YUV/RAW outputs on the phone:

```bash
adb exec-out run-as com.luvatrix.app tar -cf - files/computational_camera/processed > /private/tmp/luvatrix_processed.tar
mkdir -p /private/tmp/luvatrix_processed
tar -xf /private/tmp/luvatrix_processed.tar -C /private/tmp/luvatrix_processed
```

Each processed case should contain:

```text
IMG_<burst_id>.jpg
IMG_<burst_id>_preview.jpg
native_output.rgba
native_preview.rgba
processing_manifest.json
```

### Step 24.2: Generate A Comparison Report

Run the host-side harness against two or more processed output directories:

```bash
uv run python tools/camera/compare_outputs.py \
  /private/tmp/luvatrix_processed/files/computational_camera/processed/<case_a> \
  /private/tmp/luvatrix_processed/files/computational_camera/processed/<case_b> \
  --label raw-single \
  --label raw-aligned-google \
  --out /private/tmp/luvatrix_camera_comparison.json
```

The report records:

```text
decode_ok
width / height
file_size_bytes
mode
raw_quality_mode
raw_demosaic_mode
raw_merge_mode
style_profile
native_total_ms
tone_map_exposure
tone_map_p50/p95/p99
tone_map_highlight_rolloff
raw_color_gains_usable
raw_color_transform_usable
raw_color_matrix_mode
mean_luma
luma_stddev
p01/p50/p99 luma
shadow/highlight clipping ratios
mean_saturation
sharpness_luma
```

### Step 24.3: Use The Report For Tuning

Use the comparison report to decide whether a change is actually improving the still pipeline:

```text
RAW color changes should reduce clipping and improve believable luma/saturation.
Alignment changes should preserve or improve sharpness without obvious ghosting.
Style changes should move saturation/contrast intentionally, not accidentally.
Speed changes should show lower native_total_ms for the same quality mode.
```

This harness does not replace visual inspection. It gives every phone iteration a structured artifact so tuning can be repeated instead of guessed.
