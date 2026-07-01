# Luvatrix

Luvatrix is a Python app protocol and rendering runtime for building custom apps
that can run headless, on macOS, as static browser-side web apps, and through
scaffolded native Android/iOS projects.

## Install

Base install:

```bash
pip install luvatrix
```

Optional platform/runtime extras:

```bash
pip install "luvatrix[macos]"
pip install "luvatrix[vulkan]"
pip install "luvatrix[macos,vulkan]"
pip install "luvatrix[web]"
pip install "luvatrix[android]"
pip install "luvatrix[ios]"
```

The base package intentionally includes common raster/data dependencies
(`numpy` and `Pillow`). Platform-specific renderers still live behind extras.
Extras are target-scoped: installing `luvatrix[ios]` does not install macOS
PyObjC bindings, Vulkan bindings, web socket runtimes, or Android-only helpers.
iOS ABI-specific packages are prepared by the native scaffold's
`ios/scripts/setup_ios.sh` and copied into the app-owned `PyPackages` bundle.

## Create An External App

Create a standalone app outside this repository:

```bash
luvatrix init-app my_app
cd my_app
luvatrix validate-app . --render headless
luvatrix run-app . --render headless --ticks 1
```

Build and serve a browser-side app:

```bash
luvatrix build-web . --out dist/web
luvatrix serve-web .
```

Run with macOS rendering:

```bash
pip install "luvatrix[macos,vulkan]"
luvatrix validate-app . --render macos
luvatrix run-app . --render macos
```

## Native Scaffolds

Native Android and iOS projects are app-owned. Scaffold them into your app
repository when you need native targets:

```bash
luvatrix init-native . --target android --out android
luvatrix init-native . --target ios --out ios
```

Then run with the app-owned native project:

```bash
luvatrix run-app . --render android-emulator --native-project android
luvatrix run-app . --render ios-simulator --native-project ios
```

Native prerequisites:

- Android: Android SDK, ADB, Gradle/Android Gradle Plugin support, and a
  configured emulator or device.
- iOS: Xcode, xcodegen, signing for physical devices, and the iOS Python support
  assets prepared by the scaffold's `ios/scripts/setup_ios.sh`.
- Vulkan on macOS: the Python `vulkan` binding plus a native Vulkan SDK/loader
  such as Vulkan SDK or MoltenVK.

Native package sync also prunes unrelated platform runtimes from app bundles.
Android bundles keep the Android runtime tree, iOS bundles keep the iOS runtime
tree, and sibling macOS/web/native-template trees are left out unless that target
is being packaged.

## App Layout

A minimal Luvatrix app is just:

```text
my_app/
├── app.toml
└── app_main.py
```

`app.toml` declares the app id, protocol version, entrypoint, capabilities,
platform support, display metadata, and render preferences. The Python
entrypoint returns an object compatible with `init(ctx)`, `loop(ctx, dt)`, and
`stop(ctx)`, or a subclass of `luvatrix.app.App`.

Public app-developer API:

```python
from luvatrix.app import App, AppContext, validate_app_install
```

See `docs/app_protocol.md` in the repository for the detailed protocol contract.
