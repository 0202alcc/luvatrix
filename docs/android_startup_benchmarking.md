# Android Startup Benchmarking

The `android/benchmark` module measures launches of
`com.luvatrix.app.MainActivity` and generates the Baseline Profile consumed by
the app. It is a test-only, self-instrumenting module and is never packaged in
the application.

## Host-only checks

Install JDK 17, Android SDK 35, and a Gradle version compatible with Android
Gradle Plugin 8.7.3. These commands configure and compile the benchmark code,
but do not start an emulator or require a connected device:

```bash
cd android
./gradlew :app:assembleDebug :app:testDebugUnitTest
./gradlew :benchmark:assemble
```

Baseline Profile generation is deliberately not attached to ordinary assemble
tasks. Release and CI builds therefore do not wait for a device.

## Startup measurements

Use a physical device for representative startup numbers. Disable animations,
avoid thermally throttled runs, and keep the device and build constant when
comparing results. The benchmark runs ten cold and ten warm launches with
`StartupTimingMetric`, using a generated Baseline Profile when one is present:

```bash
cd android
adb devices
./gradlew :benchmark:connectedBenchmarkReleaseAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=com.luvatrix.benchmark.StartupBenchmark
```

Results and Perfetto traces are written below
`benchmark/build/outputs/connected_android_test_additional_output/` and the
connected Android test reports below `benchmark/build/reports/androidTests/`.

## Baseline Profile generation

Connect a rooted device or an Android 13 (API 33) or newer device. Generate the
profile from the critical launcher Activity path with:

```bash
cd android
./gradlew :app:generateBaselineProfile \
  -Pandroid.testInstrumentationRunnerArguments.androidx.benchmark.enabledRules=BaselineProfile
```

The Baseline Profile Gradle plugin copies the generated rules into
`app/src/release/generated/baselineProfiles/`. Review and commit the generated
profile when startup code changes, then rebuild the release artifact so the
profile is packaged. A generated profile is device- and code-path-derived; do
not replace it with hand-written rules.
