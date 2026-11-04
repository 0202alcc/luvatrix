"""Per-app iOS bundle identifiers derived from an app's ``app.toml``.

Matrix tours install every example under the same simulator, so a shared
bundle id means each new install clobbers the previous app — including one a
keep-open tour just relaunched for the user. Deriving the id from ``app_id``
gives every app its own install slot; apps without an ``app_id`` keep the
legacy ``com.luvatrix.app``.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

LEGACY_BUNDLE_ID = "com.luvatrix.app"
_BUNDLE_PREFIX = "com.luvatrix.app"


def ios_bundle_id(app_dir: str | Path) -> str:
    """Return the iOS bundle id for the app at ``app_dir``.

    Uses the last segment of ``app.toml``'s ``app_id``, lowercased and
    sanitized to ``[a-z0-9-]`` (runs of invalid characters collapse to one
    dash). Falls back to :data:`LEGACY_BUNDLE_ID` when there is no readable
    ``app.toml`` or no usable ``app_id``.
    """
    try:
        data = tomllib.loads((Path(app_dir) / "app.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return LEGACY_BUNDLE_ID
    app_id = data.get("app_id")
    if not isinstance(app_id, str):
        return LEGACY_BUNDLE_ID
    segment = app_id.strip().rsplit(".", 1)[-1].lower()
    segment = re.sub(r"[^a-z0-9-]+", "-", segment).strip("-")
    if not segment:
        return LEGACY_BUNDLE_ID
    return f"{_BUNDLE_PREFIX}.{segment}"


def sync_project_bundle_id(ios_dir: str | Path, bundle_id: str) -> None:
    """Point an app-owned Xcode spec at the app's derived bundle id.

    Scaffolds created before per-app ids (or shared dev scaffolds) hardcode
    ``com.luvatrix.app``; left stale, the built app would not match the id the
    runner launches. Rewrites only when they disagree, so app-owned files are
    touched once.
    """
    spec = Path(ios_dir) / "project.yml"
    try:
        text = spec.read_text(encoding="utf-8")
    except OSError:
        return
    # Boundary-aware so an already-derived id (com.luvatrix.app.<app>) is never
    # extended again; the shell default `:-com.luvatrix.app` still matches.
    updated = re.sub(r"(?<![\w.])com\.luvatrix\.app(?![\w.-])", bundle_id, text)
    if updated != text:
        spec.write_text(updated, encoding="utf-8")