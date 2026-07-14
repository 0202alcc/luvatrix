from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android"
BENCHMARK = ANDROID / "benchmark"
ANDROID_TEMPLATE = ROOT / "luvatrix_core/templates/native/android"


def test_android_template_mirrors_startup_benchmark_support() -> None:
    mirrored_files = (
        "build.gradle.kts",
        "settings.gradle.kts",
        "app/build.gradle.kts",
        "app/proguard-rules.pro",
        "benchmark/build.gradle.kts",
        "benchmark/src/main/java/com/luvatrix/benchmark/BaselineProfileGenerator.kt",
        "benchmark/src/main/java/com/luvatrix/benchmark/StartupBenchmark.kt",
        "benchmark/src/main/java/com/luvatrix/benchmark/StartupJourney.kt",
        "app/src/release/generated/baselineProfiles/baseline-prof.txt",
        "app/src/release/generated/baselineProfiles/startup-prof.txt",
    )

    for relative_path in mirrored_files:
        assert (ANDROID_TEMPLATE / relative_path).read_bytes() == (
            ANDROID / relative_path
        ).read_bytes()


def test_profiled_release_build_has_explicit_gradle_memory_budget() -> None:
    expected = "org.gradle.jvmargs=-Xmx1024m -XX:MaxMetaspaceSize=768m -Dfile.encoding=UTF-8"

    for project in (ANDROID, ANDROID_TEMPLATE):
        properties = (project / "gradle.properties").read_text(encoding="utf-8")
        assert expected in properties


def test_android_project_wires_baseline_profile_producer() -> None:
    settings = (ANDROID / "settings.gradle.kts").read_text(encoding="utf-8")
    root_build = (ANDROID / "build.gradle.kts").read_text(encoding="utf-8")
    app_build = (ANDROID / "app/build.gradle.kts").read_text(encoding="utf-8")

    assert 'include(":benchmark")' in settings
    assert 'id("com.android.test") version "8.7.3" apply false' in root_build
    assert 'id("androidx.baselineprofile") version "1.4.1" apply false' in root_build
    assert 'id("androidx.baselineprofile")' in app_build
    assert 'baselineProfile(project(":benchmark"))' in app_build
    assert 'implementation("androidx.profileinstaller:profileinstaller:1.4.1")' in app_build
    assert "automaticGenerationDuringBuild = false" in app_build
    assert "isMinifyEnabled = true" in app_build
    assert 'getDefaultProguardFile("proguard-android-optimize.txt")' in app_build
    assert '"proguard-rules.pro"' in app_build


def test_benchmark_module_is_device_isolated_and_targets_the_app() -> None:
    build = (BENCHMARK / "build.gradle.kts").read_text(encoding="utf-8")

    assert 'id("com.android.test")' in build
    assert 'id("androidx.baselineprofile")' in build
    assert 'targetProjectPath = ":app"' in build
    assert 'experimentalProperties["android.experimental.self-instrumenting"] = true' in build
    assert 'testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"' in build
    assert 'implementation("androidx.benchmark:benchmark-macro-junit4:1.4.1")' in build
    assert 'implementation("androidx.test.ext:junit:1.2.1")' in build
    assert "useConnectedDevices = true" in build
    assert "managedDevices" not in build


def test_startup_benchmark_measures_cold_and_warm_activity_launches() -> None:
    source = (
        BENCHMARK
        / "src/main/java/com/luvatrix/benchmark/StartupBenchmark.kt"
    ).read_text(encoding="utf-8")

    assert "StartupTimingMetric()" in source
    assert "StartupMode.COLD" in source
    assert "StartupMode.WARM" in source
    assert "CompilationMode.Partial" in source
    assert "BaselineProfileMode.UseIfAvailable" in source
    assert "startMainActivityAndWait()" in source


def test_baseline_profile_captures_the_critical_activity_startup_path() -> None:
    source = (
        BENCHMARK
        / "src/main/java/com/luvatrix/benchmark/BaselineProfileGenerator.kt"
    ).read_text(encoding="utf-8")
    journey = (
        BENCHMARK
        / "src/main/java/com/luvatrix/benchmark/StartupJourney.kt"
    ).read_text(encoding="utf-8")

    assert "BaselineProfileRule()" in source
    assert "includeInStartupProfile = true" in source
    assert "startMainActivityAndWait()" in source
    assert 'TARGET_PACKAGE = "com.luvatrix.app"' in journey
    assert 'TARGET_ACTIVITY = "$TARGET_PACKAGE.MainActivity"' in journey
    assert "setClassName(TARGET_PACKAGE, TARGET_ACTIVITY)" in journey


def test_android_performance_runbook_separates_host_and_device_gates() -> None:
    runbook = (ROOT / "docs/android_startup_benchmarking.md").read_text(encoding="utf-8")

    assert "./gradlew :app:assembleDebug :app:testDebugUnitTest" in runbook
    assert "./gradlew :benchmark:assemble" in runbook
    assert "./gradlew :benchmark:connectedBenchmarkReleaseAndroidTest" in runbook
    assert "./gradlew :app:generateBaselineProfile" in runbook
    assert "physical device" in runbook


def test_generated_profiles_cover_luvatrix_and_chaquopy_startup() -> None:
    profile_dir = ANDROID / "app/src/release/generated/baselineProfiles"
    baseline = (profile_dir / "baseline-prof.txt").read_text(encoding="utf-8")
    startup = (profile_dir / "startup-prof.txt").read_text(encoding="utf-8")

    for profile in (baseline, startup):
        assert "Lcom/luvatrix/app/MainActivity;" in profile
        assert "Lcom/luvatrix/app/LuvatrixApplication;" in profile
        assert "Lcom/luvatrix/app/LuvatrixVulkanView;" in profile
        assert "Lcom/luvatrix/app/SceneReplayCoordinator;" in profile
        assert "Lcom/luvatrix/app/SharedStartup;" in profile
        assert "Lcom/chaquo/python/Python;" in profile
        assert "Lcom/chaquo/python/android/AndroidPlatform;" in profile
