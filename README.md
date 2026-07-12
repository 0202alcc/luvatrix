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

For an Android-only app, validate against the Android runtime from your
development machine:

```bash
luvatrix init-app my_android_app --template camera
cd my_android_app
luvatrix validate-app . --render android-emulator
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

## Google Sign-In

Luvatrix provides an in-app sign-in control and an event-driven controller. The
user starts inside the app, authenticates in Google's trusted system browser
surface, and returns to the same app through its configured callback URL.

```python
from luvatrix.app import App
from luvatrix.auth import (
    GoogleOAuthClient,
    GoogleOAuthConfig,
    GoogleSignInController,
    PlatformGoogleAuthSession,
    SecureTokenStore,
)
from luvatrix.auth.ui import GoogleSignInButton


class MyApp(App):
    def init(self, ctx):
        session = PlatformGoogleAuthSession(open_browser=my_native_bridge.open_google_auth)
        store = SecureTokenStore(
            read_secret=my_native_bridge.read_secret,
            write_secret=my_native_bridge.write_secret,
            delete_secret=my_native_bridge.delete_secret,
            key="google-account",
        )
        oauth = GoogleOAuthClient(
            GoogleOAuthConfig(
                client_id="YOUR_CLIENT_ID.apps.googleusercontent.com",
                redirect_uri="com.example.app:/oauth2redirect",
                scopes=("openid", "email", "profile"),
            ),
            token_store=store,
        )
        self.google = GoogleSignInController(
            oauth,
            session=session,
            invalidate=self.invalidate,
        )
        self.google_button = GoogleSignInButton(self.google)

    def loop(self, ctx, dt):
        state = self.input.snapshot()
        self.google_button.update(state, x=24, y=24, width=220, height=44)

    def render(self):
        with self.frame(clear=(14, 18, 26, 255)) as frame:
            self.google_button.render(frame, x=24, y=24, width=220, height=44)
```

The native callback handler calls `session.deliver_callback(callback_url)`.
Android bridges should open a Custom Tab and back `SecureTokenStore` with
Android Keystore. iOS bridges should use `ASWebAuthenticationSession` and
Keychain. `InMemoryTokenStore` remains available for tests, but production apps
should not use it for long-lived refresh tokens. Mobile apps must not embed a
Google client secret.

## Prepared Text Wrapping

Luvatrix includes an optional, dependency-free prepared wrapping style inspired
by the MIT-licensed [Pretext](https://github.com/chenglou/pretext) architecture.
Text is segmented and measured once; changing only the available width reuses
those native measurements.

Scene/UI text uses `TextWrapping` on `TextComponent`:

```python
from luvatrix.app import TextWrapping
from luvatrix_ui.text import TextComponent

body = TextComponent(
    component_id="body",
    text="A paragraph which should wrap across multiple lines.",
    max_width_px=320,
    wrapping=TextWrapping(white_space="normal"),
)
```

Matrix text uses the same layout engine and its matrix-font measurements:

```python
from luvatrix.app import draw_text_to_matrix

draw_text_to_matrix(
    matrix,
    "A paragraph rendered into an RGBA matrix.",
    x=12,
    y=12,
    font_size_px=12,
    max_width_px=240,
    wrapping="pretext",
    line_height_multiplier=1.2,
)
```

`white_space="pre-wrap"` preserves repeated spaces and hard line breaks.
Ordinary wrapping collapses whitespace and uses grapheme-safe emergency breaks
for content wider than a complete line.
