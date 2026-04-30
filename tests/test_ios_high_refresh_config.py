from __future__ import annotations

from pathlib import Path
import plistlib
import unittest


ROOT = Path(__file__).resolve().parents[1]


class IOSHighRefreshConfigTests(unittest.TestCase):
    def test_info_plist_disables_minimum_frame_duration_on_phone(self) -> None:
        with (ROOT / "ios" / "Luvatrix" / "Info.plist").open("rb") as fh:
            plist = plistlib.load(fh)
        self.assertIs(plist.get("CADisableMinimumFrameDurationOnPhone"), True)

    def test_xcodegen_project_preserves_high_refresh_plist_key(self) -> None:
        project_yml = (ROOT / "ios" / "project.yml").read_text(encoding="utf-8")
        self.assertIn("CADisableMinimumFrameDurationOnPhone: true", project_yml)

    def test_ios_package_sync_includes_public_luvatrix_api(self) -> None:
        project_yml = (ROOT / "ios" / "project.yml").read_text(encoding="utf-8")
        setup_script = (ROOT / "ios" / "scripts" / "setup_ios.sh").read_text(encoding="utf-8")
        self.assertIn('"$REPO_ROOT/luvatrix/"', project_yml)
        self.assertIn('"$REPO_ROOT/luvatrix/"', setup_script)


if __name__ == "__main__":
    unittest.main()
