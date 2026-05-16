from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android"


class AndroidPackagingTests(unittest.TestCase):
    def test_android_project_shape_exists(self) -> None:
        for rel in (
            "settings.gradle.kts",
            "build.gradle.kts",
            "gradle.properties",
            "gradlew",
            "app/build.gradle.kts",
            "app/src/main/AndroidManifest.xml",
            "app/src/main/java/com/luvatrix/app/MainActivity.kt",
            "app/src/main/python/luvatrix_android_boot.py",
        ):
            self.assertTrue((ANDROID / rel).exists(), rel)

    def test_chaquopy_python_314_is_configured(self) -> None:
        build = (ANDROID / "app" / "build.gradle.kts").read_text(encoding="utf-8")

        self.assertIn("com.chaquo.python", build)
        self.assertIn('version = "3.14"', build)
        self.assertIn("arm64-v8a", build)
        self.assertIn("x86_64", build)
        self.assertIn("JavaVersion.VERSION_17", build)
        self.assertIn("JvmTarget.JVM_17", build)
        self.assertNotIn('install("numpy")', build)
        self.assertNotIn('install("Pillow")', build)

    def test_emulator_acceptance_script_exists(self) -> None:
        script = ANDROID / "scripts" / "emulator_acceptance.sh"

        self.assertTrue(script.exists())
        self.assertIn("FullSuiteEmulatorAcceptanceTest", script.read_text(encoding="utf-8"))

    def test_androidx_is_enabled_for_instrumentation_dependencies(self) -> None:
        props = (ANDROID / "gradle.properties").read_text(encoding="utf-8")

        self.assertIn("android.useAndroidX=true", props)


if __name__ == "__main__":
    unittest.main()
