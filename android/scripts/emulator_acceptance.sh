#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if ! command -v adb >/dev/null 2>&1; then
  echo "error: adb is required for Android emulator acceptance." >&2
  exit 127
fi

if ! "$REPO_ROOT/android/gradlew" --version >/dev/null 2>&1; then
  echo "error: Gradle is required for Android emulator acceptance." >&2
  "$REPO_ROOT/android/gradlew" --version
  exit 127
fi

bash "$REPO_ROOT/android/scripts/sync_python_assets.sh" examples/full_suite_interactive
cd "$REPO_ROOT/android"
./gradlew assembleDebug connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=com.luvatrix.app.FullSuiteEmulatorAcceptanceTest

echo "luvatrix full_suite emulator ok"
