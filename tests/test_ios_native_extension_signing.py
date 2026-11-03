from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_YMLS = (
    ROOT / "ios" / "project.yml",
    ROOT / "luvatrix_core" / "templates" / "native" / "ios" / "project.yml",
    ROOT / "examples" / "hello_ios" / "ios" / "project.yml",
)
PHASE_NAME = "Process PyPackages native extensions"
# Mirrors install_dylib in Python-Apple-support's build/utils.sh.
STUB_UTILS = """\
process_dylibs() {{
  template="$PROJECT_DIR/$1/build/$PLATFORM_FAMILY_NAME-dylib-Info-template.plist"
  [ -f "$template" ] || {{ echo "missing $template" >&2; return 1; }}
  printf '{{"identity": "%s", "template": "%s"}}' "$EXPANDED_CODE_SIGN_IDENTITY" "$(basename "$template")" > "{seen}"
}}
"""


def _phase_script(project_yml: Path, phase_name: str) -> str:
    lines = project_yml.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f"- name: {phase_name}")
    script_line = lines[start + 1]
    assert script_line.strip() == "script: |", script_line
    script_indent = len(script_line) - len(script_line.lstrip())
    body: list[str] = []
    for line in lines[start + 2 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= script_indent:
            break
        body.append(line)
    return textwrap.dedent("\n".join(body))


@unittest.skipIf(shutil.which("bash") is None, "bash is required to run Xcode script phases")
class IOSNativeExtensionSigningTests(unittest.TestCase):
    def _run_phase(
        self,
        project_yml: Path,
        *,
        templates: tuple[str, ...] = ("iOS",),
        **env: str,
    ) -> dict[str, str]:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            build_dir = project_dir / "Python" / "PythonSupport.xcframework" / "build"
            build_dir.mkdir(parents=True)
            for family in templates:
                (build_dir / f"{family}-dylib-Info-template.plist").write_text("<plist/>", encoding="utf-8")
            seen = Path(td) / "seen.json"
            (build_dir / "utils.sh").write_text(STUB_UTILS.format(seen=seen), encoding="utf-8")
            run_env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PROJECT_DIR": str(project_dir),
                "BUILT_PRODUCTS_DIR": str(Path(td) / "products"),
                "PRODUCT_NAME": "Luvatrix",
                "PLATFORM_NAME": "iphonesimulator",
                **env,
            }
            subprocess.run(
                ["bash", "-c", _phase_script(project_yml, PHASE_NAME)],
                check=True,
                cwd=project_dir,
                env=run_env,
            )
            return json.loads(seen.read_text(encoding="utf-8"))

    def test_unsigned_simulator_build_ad_hoc_signs_python_extensions(self) -> None:
        for project_yml in PROJECT_YMLS:
            with self.subTest(project_yml=str(project_yml.relative_to(ROOT))):
                seen = self._run_phase(
                    project_yml,
                    CODE_SIGN_IDENTITY="",
                    CODE_SIGNING_ALLOWED="NO",
                    EXPANDED_CODE_SIGN_IDENTITY="",
                )
                self.assertEqual(seen["identity"], "-")

    def test_signed_build_keeps_xcode_identity(self) -> None:
        for project_yml in PROJECT_YMLS:
            with self.subTest(project_yml=str(project_yml.relative_to(ROOT))):
                seen = self._run_phase(project_yml, EXPANDED_CODE_SIGN_IDENTITY="ABC123")
                self.assertEqual(seen["identity"], "ABC123")

    def test_simulator_build_uses_shared_ios_template_when_no_simulator_template(self) -> None:
        for project_yml in PROJECT_YMLS:
            with self.subTest(project_yml=str(project_yml.relative_to(ROOT))):
                seen = self._run_phase(project_yml, PLATFORM_NAME="iphonesimulator")
                self.assertEqual(seen["template"], "iOS-dylib-Info-template.plist")

    def test_simulator_build_prefers_simulator_template_when_shipped(self) -> None:
        for project_yml in PROJECT_YMLS:
            with self.subTest(project_yml=str(project_yml.relative_to(ROOT))):
                seen = self._run_phase(
                    project_yml,
                    templates=("iOS", "iOS-simulator"),
                    PLATFORM_NAME="iphonesimulator",
                )
                self.assertEqual(seen["template"], "iOS-simulator-dylib-Info-template.plist")

    def test_device_build_uses_ios_template(self) -> None:
        for project_yml in PROJECT_YMLS:
            with self.subTest(project_yml=str(project_yml.relative_to(ROOT))):
                seen = self._run_phase(
                    project_yml,
                    templates=("iOS", "iOS-simulator"),
                    PLATFORM_NAME="iphoneos",
                )
                self.assertEqual(seen["template"], "iOS-dylib-Info-template.plist")


if __name__ == "__main__":
    unittest.main()
