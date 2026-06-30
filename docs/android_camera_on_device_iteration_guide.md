# Android Camera On-Device Iteration Guide

This guide extends `docs/android_computational_camera_lab_implementation.md` with the practical phone-connected workflow. It assumes:

- A physical Android phone is connected over USB.
- USB debugging is enabled.
- The current branch is `feature/android-camera`.
- The native Android project is the repo-local `android/` project.
- The target app is `examples/camera`.

The goal is not merely to build. The goal is to iterate until a working app is visible on the phone, camera preview is active, the Python HUD is responsive, and runtime errors are cleared.

## The Loop

Every on-device iteration follows this loop:

```text
1. Confirm device connection
2. Run focused local tests
3. Upload/install/launch app
4. Watch logs
5. Classify failure
6. Make smallest fix
7. Re-run focused tests
8. Re-upload
9. Repeat until app is working
```

Do not skip log inspection. A successful APK install only proves the package installed; it does not prove the Python runtime, Camera2 session, Vulkan surface, or camera preview path is healthy.

## Preflight

### 1. Confirm branch and worktree

```bash
git status --short --branch
```

Expected branch:

```text
## feature/android-camera
```

Do not clean or reset unrelated files. This repo may already contain work in progress.

### 2. Confirm device is visible

```bash
adb devices
```

Expected:

```text
List of devices attached
SERIAL	device
```

If the device says `unauthorized`, unlock the phone and accept the debugging prompt.

If multiple devices are attached, capture the serial:

```bash
adb devices
```

Then pass it to every upload command:

```bash
--android-device-id SERIAL
```

### 3. Confirm camera permission can be granted

After the first install, permission should be requested in-app. If debugging needs a manual grant:

```bash
adb shell pm grant com.luvatrix.app android.permission.CAMERA
```

If grant fails because the app is not installed yet, continue to upload first.

## Local Test Gate

Before uploading Android changes, run the smallest relevant local test set.

For upload/sync/runtime boot changes:

```bash
uv run pytest tests/test_android_runner.py tests/test_android_packaging.py tests/test_android_scene_target.py
```

For Python HUD changes:

```bash
uv run pytest tests/test_camera_example.py
```

For camera sensor telemetry changes:

```bash
uv run pytest tests/test_android_sensors.py tests/test_camera_example.py
```

For burst artifact processing tools:

```bash
uv run pytest tests/test_camera_burst_processing.py
```

Only upload after the focused tests are green, unless the failure can only be diagnosed on-device.

## Upload Command

Default physical phone upload:

```bash
uv run python main.py run-app examples/camera --render android-device --native-project android
```

With explicit device serial:

```bash
uv run python main.py run-app examples/camera --render android-device --native-project android --android-device-id SERIAL
```

Expected successful terminal tail:

```text
BUILD SUCCESSFUL
Performing Streamed Install
Success
Starting: Intent { cmp=com.luvatrix.app/.MainActivity }
[android] synced Python assets for .../examples/camera
```

Important: this still does not mean the app is healthy. Immediately inspect logs.

## Log Watching

Use a dedicated terminal for logs.

Clear logs before each launch:

```bash
adb logcat -c
```

Then watch focused logs:

```bash
adb logcat -s Luvatrix python stderr AndroidRuntime
```

If that is too quiet, broaden temporarily:

```bash
adb logcat | rg "Luvatrix|Chaquopy|Python|AndroidRuntime|Camera|Vulkan"
```

Stop logcat with `Ctrl-C`.

## Health Checks After Launch

After upload, confirm these in order:

1. App opens on phone.
2. No visible red/exception runtime overlay.
3. Python HUD appears.
4. Camera permission is granted or prompt appears.
5. Camera preview starts behind the HUD.
6. HUD reports camera telemetry instead of only `camera: waiting`.
7. Touch buttons respond.
8. Debug HUD can be toggled with `h` or HUD button.
9. Preview remains responsive after 10-20 seconds.

If any step fails, classify the failure below.

## Failure Classifier

### A. Device Not Found

Symptoms:

```text
No Android emulator/device is connected.
adb devices failed
```

Checks:

```bash
adb devices
```

Fixes:

- Replug USB.
- Unlock phone.
- Toggle USB debugging.
- Accept authorization prompt.
- Use `--android-device-id SERIAL` if multiple devices are attached.

Then retry upload.

### B. Native Project Not Found

Symptom:

```text
Android native project not found
```

Fix:

Always include:

```bash
--native-project android
```

Correct command:

```bash
uv run python main.py run-app examples/camera --render android-device --native-project android
```

### C. Host Python Optional Dependency Leak

Symptom:

```text
ModuleNotFoundError: No module named 'torch'
```

Cause:

The Android upload path imported an optional package such as `luvatrix_plot` on the host while syncing assets.

Expected fix:

- `sync_android_python_assets` must copy package source directories without importing optional packages.
- Camera app bundle should not include `luvatrix_plot` or `luvatrix_ui` unless the app imports them.

Checks:

```bash
test -d android/app/src/main/python/luvatrix_plot
test -d android/app/src/main/python/luvatrix_ui
```

For `examples/camera`, both commands should exit non-zero.

Run:

```bash
uv run pytest tests/test_android_runner.py
```

Then retry upload.

### D. Configured Android App Is Missing

Symptom on phone:

```text
configured Android app is missing
```

Cause:

Chaquopy may not expose bundled Python package files as normal filesystem paths. The boot layer needs an importable fallback bundle.

Required local files:

```bash
find android/app/src/main/python/examples -maxdepth 3 -type f -print
```

Expected:

```text
android/app/src/main/python/examples/__init__.py
android/app/src/main/python/examples/camera/__init__.py
android/app/src/main/python/examples/camera/_luvatrix_bundle.py
```

Also check:

```bash
cat android/app/src/main/python/luvatrix_launch_config.json
```

Expected fields:

```json
{
  "app_dir": "luvatrix_app",
  "source_app_dir": ".../examples/camera"
}
```

Fix:

- Ensure `sync_android_python_assets` writes `examples/camera/_luvatrix_bundle.py`.
- Re-upload so Chaquopy repackages Python sources.

Focused test:

```bash
uv run pytest tests/test_android_runner.py
```

### E. Unexpected Keyword Argument `target_present_time`

Symptom:

```text
unexpected keyword argument 'target_present_time'
```

Cause:

The shared scene runtime calls:

```python
present_scene(frame, target_present_time=...)
```

but the Android scene target had an older signature.

Fix:

`luvatrix_core/platform/android/scene_target.py` must accept:

```python
def present_scene(self, frame, target_present_time: float | None = None) -> None:
    _ = target_present_time
```

Focused test:

```bash
uv run pytest tests/test_android_scene_target.py
```

Then re-upload.

### F. Python Import Error On Phone

Symptoms:

```text
ModuleNotFoundError
ImportError
failed to load configured app module
luvatrix run_app_vulkan failed
```

Steps:

1. Read the full logcat traceback.
2. Identify the missing module.
3. Decide whether it is required by `examples/camera`.
4. If required, include it in Android sync.
5. If not required, remove the eager import.

Common places to inspect:

```bash
rg -n "import luvatrix_ui|import luvatrix_plot|import torch|from luvatrix_plot" \
  android/app/src/main/python \
  luvatrix_core \
  luvatrix \
  examples/camera
```

Focused tests:

```bash
uv run pytest tests/test_android_runner.py tests/test_camera_example.py
```

### G. App Opens But Camera Preview Is Black

Possible causes:

- Camera permission denied.
- Camera2 session failed.
- PRIVATE HardwareBuffer import failed and fallback did not engage.
- Surface was not ready when preview started.
- Camera is already in use by another app.

Checks:

```bash
adb shell pm grant com.luvatrix.app android.permission.CAMERA
adb logcat -s Luvatrix CameraService CameraManagerGlobal AndroidRuntime
```

Look for:

```text
startCameraPreview
CameraDevice error
session configure failed
PRIVATE delivery starved
native Vulkan HardwareBuffer import/render is unavailable
```

Expected behavior:

- PRIVATE preview is preferred.
- If PRIVATE fails, YUV fallback should start.
- HUD should report fallback reason.

Fix strategy:

1. Keep preview path simple.
2. Improve telemetry first.
3. Only then adjust session fallback logic.

Focused tests:

```bash
uv run pytest tests/test_android_packaging.py tests/test_camera_example.py
```

Then re-upload.

### H. App Opens, Preview Works, HUD Is Stale

Symptoms:

- HUD says `camera: waiting`.
- Buttons do nothing.
- Telemetry does not update.

Checks:

```bash
adb logcat -s Luvatrix python stderr
```

Look for Python exceptions in `ctx.read_sensor`, `cameraTelemetryJson`, or HUD formatting.

Local tests:

```bash
uv run pytest tests/test_android_sensors.py tests/test_camera_example.py
```

Likely fixes:

- Sensor adapter must tolerate missing/partial JSON.
- HUD formatting must default missing fields.
- Kotlin telemetry must emit structured fields consistently.

### I. Build Succeeds But Old Code Seems Installed

Symptoms:

- Same phone error persists after fix.
- Log lines do not match current code.

Steps:

Force-stop and reinstall through CLI:

```bash
uv run python main.py run-app examples/camera --render android-device --native-project android
```

If still stale, uninstall then upload:

```bash
adb uninstall com.luvatrix.app
uv run python main.py run-app examples/camera --render android-device --native-project android
```

Check generated Python source assets were rebuilt:

```bash
ls -lt android/app/build/generated/python
```

If needed, run Gradle clean from the Android project:

```bash
cd android
./gradlew clean
cd ..
uv run python main.py run-app examples/camera --render android-device --native-project android
```

Use clean sparingly because it slows iteration.

## Iteration Template

Use this exact rhythm for each fix:

```bash
# 1. Reproduce or confirm failing behavior.
adb logcat -c
uv run python main.py run-app examples/camera --render android-device --native-project android
adb logcat -s Luvatrix python stderr AndroidRuntime

# 2. Stop logcat after seeing the failure.

# 3. Add or update a focused failing test.
uv run pytest tests/test_RELEVANT.py -k relevant_name

# 4. Implement the smallest fix.

# 5. Run focused tests.
uv run pytest tests/test_RELEVANT.py -k relevant_name

# 6. Run adjacent Android tests.
uv run pytest tests/test_android_runner.py tests/test_android_packaging.py tests/test_camera_example.py

# 7. Re-upload and watch logs again.
adb logcat -c
uv run python main.py run-app examples/camera --render android-device --native-project android
adb logcat -s Luvatrix python stderr AndroidRuntime
```

Do not batch multiple speculative fixes before re-uploading. On-device Android camera bugs compound quickly.

## What Working Looks Like

A working app means all of this is true:

- CLI upload exits with `BUILD SUCCESSFUL`, install `Success`, and launch intent starts `MainActivity`.
- Logcat has no uncaught Python or Android runtime exception after launch.
- Phone shows the Luvatrix camera lab HUD.
- Camera permission is granted.
- Live camera preview is visible or HUD clearly reports a fallback/unavailable reason.
- HUD updates camera telemetry.
- Touch/key controls update HUD action status.
- Debug HUD shows preview/camera diagnostics.
- App stays alive for at least 60 seconds.

For the computational camera milestone, add:

- Burst button captures a package.
- `burst_manifest.json` exists on device.
- Frame and metadata files exist.
- Offline processor can process the pulled package.
- HUD can show latest burst/result path.

## Pulling Camera Artifacts

List app-private files:

```bash
adb shell run-as com.luvatrix.app find files -maxdepth 5 -type f
```

Pull computational camera artifacts:

```bash
adb exec-out run-as com.luvatrix.app tar cf - files/computational_camera > /tmp/luvatrix_camera_artifacts.tar
mkdir -p /tmp/luvatrix_camera_artifacts
tar xf /tmp/luvatrix_camera_artifacts.tar -C /tmp/luvatrix_camera_artifacts
```

Inspect burst manifests:

```bash
find /tmp/luvatrix_camera_artifacts -name burst_manifest.json -print
```

Process a burst once Packet 6 exists:

```bash
uv run python tools/camera/process_burst.py /tmp/luvatrix_camera_artifacts/files/computational_camera/bursts/BURST_ID --out /tmp/luvatrix_processed --mode sharpest
```

## Minimum Test Set Before Calling A Device Fix Done

Run:

```bash
uv run pytest \
  tests/test_android_runner.py \
  tests/test_android_packaging.py \
  tests/test_android_scene_target.py \
  tests/test_android_sensors.py \
  tests/test_camera_example.py
```

Then upload:

```bash
uv run python main.py run-app examples/camera --render android-device --native-project android
```

Then watch logs for at least 30 seconds:

```bash
adb logcat -s Luvatrix python stderr AndroidRuntime
```

The fix is done only when tests are green and the app is healthy on the phone.

## Branch Hygiene

Before committing:

```bash
git status --short
```

Stage only files that belong to the Android camera work. Do not stage generated camera captures, Gradle build output, `.cxx`, `.gradle`, APKs, DNGs, PNG captures, or local logs.

Useful final diff checks:

```bash
git diff -- docs android/app/src/main/java/com/luvatrix/app luvatrix_core/platform/android examples/camera tests/test_android*
git diff --stat
```

Commit message examples:

```text
android: fix camera app asset bundle upload
android: accept scene target present timing hint
camera: add burst capture HUD tests
```

## On-Device First Milestone Checklist

The on-device computational camera loop is ready for the next phase when:

1. Upload command works repeatedly without manual cleanup.
2. Runtime boot finds the configured camera app.
3. Preview starts and recovers after app relaunch.
4. HUD telemetry updates.
5. Logcat is clean after launch.
6. Focused tests are green.
7. Any new camera failure has a documented classifier entry in this guide.
