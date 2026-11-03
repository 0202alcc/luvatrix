# Hello iOS

Minimal iOS-only Luvatrix app: a white square centered on a dark background.
`ios/` is the app-owned native scaffold created with
`luvatrix init-native examples/hello_ios --target ios --out examples/hello_ios/ios`.

Validate from any host (run from the repository root):

```bash
uv run luvatrix validate-app examples/hello_ios --render ios-simulator
uv run luvatrix run-app examples/hello_ios --render headless --ticks 1 --energy-safety off
```

Run in the iOS Simulator (macOS with Xcode, xcodegen, and `pip3` on PATH):

```bash
uv sync --extra desktop
brew install xcodegen
uv run bash examples/hello_ios/ios/scripts/setup_ios.sh
uv run luvatrix run-app examples/hello_ios --render ios-simulator \
  --native-project examples/hello_ios/ios --simulator "iPhone 16"
```

`setup_ios.sh` must run under `uv run` because it imports `luvatrix_core` with
`python3` to copy the Luvatrix packages into the bundle. It downloads the
embedded Python 3.12 support framework into `ios/Python/` and installs iOS
wheels into `ios/PyPackages-simulator/` and `ios/PyPackages-device/`; those
directories are gitignored.
