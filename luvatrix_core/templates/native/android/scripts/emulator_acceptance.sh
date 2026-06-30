#!/usr/bin/env bash
set -euo pipefail

NATIVE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "$(basename "$(dirname "$NATIVE_DIR")")" = ".luvatrix" ]; then
  DEFAULT_APP_DIR="$(cd "$NATIVE_DIR/../.." && pwd)"
else
  DEFAULT_APP_DIR="$(cd "$NATIVE_DIR/.." && pwd)"
fi
APP_DIR="${1:-$DEFAULT_APP_DIR}"

if ! command -v adb >/dev/null 2>&1; then
  echo "error: adb is required for Android emulator acceptance." >&2
  exit 127
fi

if ! "$NATIVE_DIR/gradlew" --version >/dev/null 2>&1; then
  echo "error: Gradle is required for Android emulator acceptance." >&2
  "$NATIVE_DIR/gradlew" --version
  exit 127
fi

bash "$NATIVE_DIR/scripts/sync_python_assets.sh" "$APP_DIR"
cd "$NATIVE_DIR"
./gradlew assembleDebug connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=com.luvatrix.app.FullSuiteEmulatorAcceptanceTest

echo "luvatrix full_suite emulator ok"
